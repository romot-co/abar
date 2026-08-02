# pyright: reportUnusedFunction=false
"""FastAPI composition root for the local ABAR application."""

from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from abar.app import commands
from abar.app.repository import WorkspaceError
from abar.server.audio_tokens import AudioTokenStore
from abar.server.automation_routes import build_automation_router
from abar.server.dependencies import AccessError, build_dependencies
from abar.server.errors import error_response
from abar.server.interaction_routes import build_interaction_router
from abar.server.read_routes import build_read_router
from abar.server.workspaces import WorkspaceCatalog


def create_app(
    workspace_root: Path,
    *,
    workspace_roots: tuple[Path, ...] | None = None,
    automation_token: str,
    interaction_token: str,
    allowed_origins: frozenset[str],
) -> FastAPI:
    catalog = WorkspaceCatalog.build(workspace_root, workspace_roots)
    dependencies = build_dependencies(
        catalog,
        automation_token=automation_token,
        interaction_token=interaction_token,
    )
    application = FastAPI(
        title="ABAR local application",
        version="2.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    allowed_hosts = frozenset(
        host for origin in allowed_origins if (host := urlsplit(origin).netloc)
    )

    @application.middleware("http")
    async def enforce_local_origin(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get("host") not in allowed_hosts:
            return error_response(403, "host_rejected", "request Host is not allowed")
        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            return error_response(403, "origin_rejected", "request Origin is not allowed")
        return await call_next(request)

    @application.exception_handler(AccessError)
    async def access_error(_request: Request, error: AccessError) -> JSONResponse:
        return error_response(403, "capability_rejected", str(error))

    @application.exception_handler(commands.CommandError)
    async def command_error(_request: Request, error: commands.CommandError) -> JSONResponse:
        return error_response(409, error.code, str(error))

    @application.exception_handler(WorkspaceError)
    async def workspace_error(_request: Request, error: WorkspaceError) -> JSONResponse:
        return error_response(409, error.code, str(error))

    @application.exception_handler(ValueError)
    async def value_error(_request: Request, error: ValueError) -> JSONResponse:
        return error_response(409, "request_rejected", str(error))

    audio_tokens = AudioTokenStore()
    application.include_router(
        build_read_router(catalog, dependencies, interaction_token=interaction_token)
    )
    application.include_router(build_automation_router(dependencies))
    application.include_router(build_interaction_router(dependencies, audio_tokens))

    static_root = Path(__file__).with_name("static")
    if static_root.is_dir():
        application.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")
        fonts_root = static_root / "fonts"
        if fonts_root.is_dir():
            application.mount("/fonts", StaticFiles(directory=fonts_root), name="fonts")

        @application.get("/")
        def index() -> FileResponse:
            return FileResponse(static_root / "index.html")

    return application
