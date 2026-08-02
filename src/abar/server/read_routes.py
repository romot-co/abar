# pyright: reportUnusedFunction=false
"""Browser bootstrap and read-only API routes."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from abar.app.queries import entity, history, project_dashboard, project_view, status
from abar.app.repository import WorkspaceRepository
from abar.app.views import (
    ActionView,
    EntityView,
    HistoryView,
    ProjectDashboardView,
    ProjectView,
    StatusView,
    WorkspaceCatalogView,
    WorkspaceSummaryView,
)
from abar.server.dependencies import ServerDependencies
from abar.server.workspaces import WorkspaceCatalog


def build_read_router(
    catalog: WorkspaceCatalog,
    dependencies: ServerDependencies,
    *,
    interaction_token: str,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/browser-sessions", response_model=ActionView)
    def connect_browser(
        response: Response,
        _human: Annotated[None, Depends(dependencies.interaction)],
    ) -> ActionView:
        response.set_cookie(
            "abar_interaction",
            interaction_token,
            max_age=90 * 24 * 3600,
            httponly=True,
            samesite="strict",
            path="/",
        )
        response.set_cookie(
            "abar_workspace",
            catalog.primary_id,
            max_age=90 * 24 * 3600,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return ActionView(result="connected")

    @router.get("/api/workspaces", response_model=WorkspaceCatalogView)
    def get_workspaces(
        root: Annotated[Path, Depends(dependencies.selected_workspace)],
        _human: Annotated[None, Depends(dependencies.interaction)],
    ) -> WorkspaceCatalogView:
        selected = next(item for item in catalog.entries if item.root == root)
        return WorkspaceCatalogView(
            selected_id=selected.id,
            workspaces=tuple(
                WorkspaceSummaryView(id=item.id, name=item.name) for item in catalog.entries
            ),
        )

    @router.post("/api/workspaces/{workspace_id}/select", response_model=ActionView)
    def select_workspace(
        workspace_id: str,
        response: Response,
        _human: Annotated[None, Depends(dependencies.interaction)],
    ) -> ActionView:
        catalog.resolve(workspace_id)
        response.set_cookie(
            "abar_workspace",
            workspace_id,
            max_age=90 * 24 * 3600,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return ActionView(result="selected", id=workspace_id)

    @router.get("/api/status", response_model=StatusView)
    def get_status(
        repository: Annotated[WorkspaceRepository, Depends(dependencies.repository)],
        cursor: int = 0,
    ) -> StatusView:
        return status(repository, cursor=cursor)

    @router.get("/api/project", response_model=ProjectDashboardView)
    def get_project(
        repository: Annotated[WorkspaceRepository, Depends(dependencies.repository)],
        _human: Annotated[None, Depends(dependencies.interaction)],
    ) -> ProjectDashboardView:
        return project_dashboard(repository)

    @router.get("/api/project/snapshot", response_model=ProjectView)
    def get_project_snapshot(
        repository: Annotated[WorkspaceRepository, Depends(dependencies.repository)],
        _automation: Annotated[None, Depends(dependencies.automation)],
        since: int = 0,
    ) -> ProjectView:
        return project_view(repository, since=since)

    @router.get("/api/history", response_model=HistoryView)
    def get_history(
        repository: Annotated[WorkspaceRepository, Depends(dependencies.repository)],
        since: int = 0,
    ) -> HistoryView:
        return history(repository, since=since)

    @router.get("/api/entities/{entity_id}", response_model=EntityView)
    def get_entity(
        entity_id: str,
        repository: Annotated[WorkspaceRepository, Depends(dependencies.repository)],
        _automation: Annotated[None, Depends(dependencies.automation)],
    ) -> EntityView:
        return entity(repository, entity_id)

    @router.post("/api/rebuild", response_model=ActionView)
    def rebuild(
        _actor: Annotated[str, Depends(dependencies.actor_id)],
        repository: Annotated[WorkspaceRepository, Depends(dependencies.repository)],
    ) -> ActionView:
        result = repository.replay()
        return ActionView(result="ok" if result.degraded is None else "degraded")

    return router
