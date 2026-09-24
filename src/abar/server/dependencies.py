"""FastAPI authentication, actor, workspace, and repository dependencies."""

import secrets
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import Cookie, Depends, Header, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from abar.app.actors import Actor
from abar.app.command_support import operation_key
from abar.app.replay_cache import ReplayCache
from abar.app.repository import WorkspaceRepository
from abar.server.workspaces import WorkspaceCatalog

type Capability = Literal["automation", "interaction"]


class AccessError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ServerDependencies:
    capability: Callable[..., Capability]
    interaction: Callable[..., None]
    automation: Callable[..., None]
    actor_id: Callable[..., str]
    actor: Callable[..., Actor]
    idempotency_key: Callable[..., str]
    selected_workspace: Callable[..., Path]
    repository: Callable[..., Iterator[WorkspaceRepository]]


WORKSPACE_COOKIE = "abar_workspace"
INTERACTION_COOKIE = "abar_interaction"
_SCOPED_COOKIES = (INTERACTION_COOKIE, WORKSPACE_COOKIE)
_COOKIE_MAX_AGE = 90 * 24 * 3600


def set_workspace_cookie(response: Response, workspace_id: str) -> None:
    response.set_cookie(
        WORKSPACE_COOKIE,
        workspace_id,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        path="/",
    )


def _same_secret(presented: str, expected: str) -> bool:
    return secrets.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


class PortScopedCookies:
    """Give the browser-session cookies a per-port name on the wire.

    Browsers share cookies across ports of one host, so two ``abar ui`` servers on
    127.0.0.1 would overwrite each other's capability and Workspace selection.
    Routes keep reading and setting the plain names; this middleware renames them
    to ``<name>_<port>`` in Set-Cookie and maps them back on requests. A plain
    cookie left by an older server is used only when no scoped one is present.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        port = _request_port(scope) if scope["type"] == "http" else None
        if port is None:
            await self.app(scope, receive, send)
            return
        suffix = f"_{port}"
        headers = [
            (name, _scoped_request_cookies(value, suffix) if name == b"cookie" else value)
            for name, value in cast(list[tuple[bytes, bytes]], scope["headers"])
        ]

        async def send_scoped(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        (
                            name,
                            _scoped_set_cookie(value, suffix)
                            if name.lower() == b"set-cookie"
                            else value,
                        )
                        for name, value in cast(
                            list[tuple[bytes, bytes]], message.get("headers", [])
                        )
                    ],
                }
            await send(message)

        await self.app({**scope, "headers": headers}, receive, send_scoped)


def _request_port(scope: Scope) -> str | None:
    for name, value in cast(list[tuple[bytes, bytes]], scope["headers"]):
        if name == b"host":
            host = value.decode("latin-1")
            _, separator, port = host.rpartition(":")
            return port if separator and port.isdigit() else None
    return None


def _scoped_request_cookies(header: bytes, suffix: str) -> bytes:
    pairs = [item.strip() for item in header.decode("latin-1").split(";") if item.strip()]
    names = {item.split("=", 1)[0].strip() for item in pairs}
    kept: list[str] = []
    for item in pairs:
        name, separator, value = item.partition("=")
        name = name.strip()
        if name in _SCOPED_COOKIES:
            if f"{name}{suffix}" in names:
                continue
            kept.append(item)
        elif name.endswith(suffix) and name.removesuffix(suffix) in _SCOPED_COOKIES:
            kept.append(f"{name.removesuffix(suffix)}{separator}{value}")
        else:
            kept.append(item)
    return "; ".join(kept).encode("latin-1")


def _scoped_set_cookie(header: bytes, suffix: str) -> bytes:
    for name in _SCOPED_COOKIES:
        prefix = f"{name}=".encode("latin-1")
        if header.startswith(prefix):
            return f"{name}{suffix}=".encode("latin-1") + header[len(prefix) :]
    return header


def build_dependencies(
    catalog: WorkspaceCatalog,
    *,
    automation_token: str,
    interaction_token: str,
) -> ServerDependencies:
    primary_root = catalog.resolve(None)
    replay_cache = ReplayCache()

    def capability(
        authorization: Annotated[str | None, Header()] = None,
        abar_interaction: Annotated[str | None, Cookie()] = None,
    ) -> Capability:
        if authorization is not None:
            # Check both tokens unconditionally so timing reveals neither.
            is_interaction = _same_secret(authorization, f"Bearer {interaction_token}")
            is_automation = _same_secret(authorization, f"Bearer {automation_token}")
            if is_interaction:
                return "interaction"
            if is_automation:
                return "automation"
        elif abar_interaction is not None and _same_secret(abar_interaction, interaction_token):
            return "interaction"
        raise AccessError("capability token is missing or invalid")

    def interaction(value: Annotated[Capability, Depends(capability)]) -> None:
        if value != "interaction":
            raise AccessError("interaction capability is required")

    def automation(value: Annotated[Capability, Depends(capability)]) -> None:
        if value != "automation":
            raise AccessError("automation capability is required")

    def actor(
        access: Annotated[Capability, Depends(capability)],
        x_abar_actor: Annotated[str | None, Header()] = None,
    ) -> Actor:
        if access == "automation" and not x_abar_actor:
            raise AccessError("X-ABAR-Actor is required for automation writes")
        return Actor(x_abar_actor or "human", "agent" if access == "automation" else "human")

    def actor_id(value: Annotated[Actor, Depends(actor)]) -> str:
        return value.id

    def idempotency_key(
        value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> str:
        return value or operation_key()

    def selected_workspace(
        access: Annotated[Capability, Depends(capability)],
        response: Response,
        abar_workspace: Annotated[str | None, Cookie()] = None,
    ) -> Path:
        if access == "automation":
            return primary_root
        try:
            return catalog.resolve(abar_workspace)
        except ValueError:
            # A stale selection (a Workspace that is gone or belongs to another
            # server) must not lock the browser out; reselect the primary one.
            set_workspace_cookie(response, catalog.primary_id)
            return primary_root

    def repository(
        root: Annotated[Path, Depends(selected_workspace)],
    ) -> Iterator[WorkspaceRepository]:
        value = WorkspaceRepository.open(root, cache=replay_cache)
        try:
            yield value
        finally:
            value.close()

    return ServerDependencies(
        capability=capability,
        interaction=interaction,
        automation=automation,
        actor_id=actor_id,
        actor=actor,
        idempotency_key=idempotency_key,
        selected_workspace=selected_workspace,
        repository=repository,
    )
