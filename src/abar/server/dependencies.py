"""FastAPI authentication, actor, workspace, and repository dependencies."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header

from abar.app.actors import Actor
from abar.app.command_support import operation_key
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


def build_dependencies(
    catalog: WorkspaceCatalog,
    *,
    automation_token: str,
    interaction_token: str,
) -> ServerDependencies:
    primary_root = catalog.resolve(None)

    def capability(
        authorization: Annotated[str | None, Header()] = None,
        abar_interaction: Annotated[str | None, Cookie()] = None,
    ) -> Capability:
        if authorization == f"Bearer {interaction_token}":
            return "interaction"
        if authorization == f"Bearer {automation_token}":
            return "automation"
        if authorization is None and abar_interaction == interaction_token:
            return "interaction"
        raise AccessError("capability token is missing or invalid")

    def interaction(value: Annotated[Capability, Depends(capability)]) -> None:
        if value != "interaction":
            raise AccessError("interaction capability is required")

    def automation(value: Annotated[Capability, Depends(capability)]) -> None:
        if value != "automation":
            raise AccessError("automation capability is required")

    def actor_id(
        access: Annotated[Capability, Depends(capability)],
        x_abar_actor: Annotated[str | None, Header()] = None,
    ) -> str:
        if access == "automation" and not x_abar_actor:
            raise AccessError("X-ABAR-Actor is required for automation writes")
        return x_abar_actor or "human"

    def actor(value: Annotated[str, Depends(actor_id)]) -> Actor:
        return Actor(value, "human" if value == "human" else "agent")

    def idempotency_key(value: Annotated[str | None, Header()] = None) -> str:
        return value or operation_key()

    def selected_workspace(
        access: Annotated[Capability, Depends(capability)],
        abar_workspace: Annotated[str | None, Cookie()] = None,
    ) -> Path:
        if access == "automation":
            return primary_root
        return catalog.resolve(abar_workspace)

    def repository(
        root: Annotated[Path, Depends(selected_workspace)],
    ) -> Iterator[WorkspaceRepository]:
        value = WorkspaceRepository.open(root)
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
