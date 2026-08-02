# pyright: reportUnusedFunction=false
"""Automation and shared command routes."""

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile

from abar.app import commands
from abar.app.actors import Actor
from abar.app.queries import session_result
from abar.app.repository import WorkspaceRepository
from abar.app.views import ActionView, SessionResultView
from abar.compare.models import RecipeRef
from abar.server.dependencies import Capability, ServerDependencies
from abar.server.request_models import (
    BestUpdateSessionRequest,
    BriefRequest,
    ClipRequest,
    ConfigRequest,
    IndicatorRequest,
    IndicatorUpdateRequest,
    IndicatorValueRequest,
    NoteRequest,
    ObservationSessionRequest,
    ProjectExportRequest,
    QuickListenRequest,
    SimplificationRequest,
    VariantRequest,
)


def build_automation_router(dependencies: ServerDependencies) -> APIRouter:
    router = APIRouter()
    repository_dependency = Depends(dependencies.repository)

    @router.post("/api/quick-listens", response_model=ActionView)
    def quick(
        body: QuickListenRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _capability: Annotated[Capability, Depends(dependencies.capability)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        session_id = commands.create_quick_listen(
            repository,
            body.first,
            body.second,
            recipe=RecipeRef(body.recipe),
            presentation=body.presentation,
            idempotency_key=key,
        )
        return ActionView(result="created", id=session_id)

    @router.post("/api/audio/import", response_model=ActionView)
    async def import_audio(
        file: UploadFile,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _actor: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        suffix = Path(file.filename or "upload.wav").suffix
        temporary = repository.root / f".upload-{secrets.token_urlsafe(12)}{suffix}"
        try:
            temporary.write_bytes(await file.read())
            audio_id = commands.import_audio(repository, temporary, idempotency_key=key)
            return ActionView(result="imported", id=audio_id)
        finally:
            temporary.unlink(missing_ok=True)

    @router.post("/api/materials", response_model=ActionView)
    async def add_material(
        file: UploadFile,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _actor: Annotated[str, Depends(dependencies.actor_id)],
        source_group: str | None = None,
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        suffix = Path(file.filename or "material.wav").suffix
        temporary = repository.root / f".material-{secrets.token_urlsafe(12)}{suffix}"
        try:
            temporary.write_bytes(await file.read())
            material_id = commands.add_material(
                repository,
                temporary,
                source_group=source_group,
                name=file.filename,
                idempotency_key=key,
            )
            return ActionView(result="registered", id=material_id)
        finally:
            temporary.unlink(missing_ok=True)

    @router.post("/api/materials/{material_id}/clips", response_model=ActionView)
    def add_clip(
        material_id: str,
        body: ClipRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _actor: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        clip_id = commands.add_clip(
            repository,
            material_id,
            start_seconds=body.start_seconds,
            duration_seconds=body.duration_seconds,
            role=body.role,
            idempotency_key=key,
        )
        return ActionView(result="registered", id=clip_id)

    @router.post("/api/variants", response_model=ActionView)
    def variants(
        body: VariantRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _actor: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        variant_id = commands.add_variant(
            repository,
            body.manifest,
            params=body.params,
            label=body.label,
            provenance=body.provenance,
            idempotency_key=key,
        )
        return ActionView(result="registered", id=variant_id)

    @router.post("/api/project/brief", response_model=ActionView)
    def brief(
        body: BriefRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        actor_id: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        changed = commands.change_brief(
            repository,
            text=body.text,
            human_quote=body.human_quote,
            actor_id=actor_id,
            idempotency_key=key,
        )
        return ActionView(result="changed" if changed else "unchanged")

    @router.post("/api/project/config", response_model=ActionView)
    def config(
        body: ConfigRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _actor: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        changed = commands.configure_project(
            repository,
            recipe=None if body.recipe is None else RecipeRef(body.recipe),
            ready_session_limit=body.ready_session_limit,
            idempotency_key=key,
        )
        return ActionView(result="changed" if changed else "unchanged")

    @router.post("/api/project/export", response_model=ActionView)
    def project_export(
        body: ProjectExportRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        authenticated_actor: Annotated[Actor, Depends(dependencies.actor)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        result = commands.export_project(
            repository,
            body.variant_id,
            output=Path(body.output),
            actor=authenticated_actor,
            render_clips=None if body.render_clips is None else Path(body.render_clips),
            idempotency_key=key,
        )
        return ActionView(result="exported", id=result.variant_id)

    @router.post("/api/project-sessions/observations", response_model=ActionView)
    def observation_sessions(
        body: ObservationSessionRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        actor_id: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        project_session_id = commands.create_observation_session(
            repository,
            first_variant=body.first_variant,
            second_variant=body.second_variant,
            focus=body.focus,
            size=body.size,
            evidence_count=body.evidence_count,
            recipe=None if body.recipe is None else RecipeRef(body.recipe),
            topic_key=body.topic_key,
            clip_ids=body.clip_ids,
            same_check=body.same_check,
            repeat_check=body.repeat_check,
            actor_id=actor_id,
            actor_type="human" if actor_id == "human" else "agent",
            idempotency_key=key,
        )
        return ActionView(result="created", id=project_session_id)

    @router.post("/api/project-sessions/best-updates", response_model=ActionView)
    def best_update_sessions(
        body: BestUpdateSessionRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        actor_id: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        project_session_id = commands.create_best_update_session(
            repository,
            proposed_variant=body.proposed_variant,
            topic_key=body.topic_key,
            clip_ids=body.clip_ids,
            actor_id=actor_id,
            actor_type="human" if actor_id == "human" else "agent",
            idempotency_key=key,
        )
        return ActionView(result="created", id=project_session_id)

    @router.post("/api/project-sessions/{project_session_id}/close", response_model=ActionView)
    def close_project_session(
        project_session_id: str,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        actor_id: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.close_project_session(
            repository, project_session_id, actor_id=actor_id, idempotency_key=key
        )
        return ActionView(result="closed", id=project_session_id)

    @router.post("/api/simplifications", response_model=ActionView)
    def simplification(
        body: SimplificationRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _actor: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        plan_id = commands.create_simplification(
            repository,
            simple_variant_id=body.simple_variant_id,
            reason=body.reason,
            scope_clip_ids=body.scope_clip_ids,
            idempotency_key=key,
        )
        return ActionView(result="pending", id=plan_id)

    @router.get(
        "/api/project-sessions/{project_session_id}/result",
        response_model=SessionResultView,
    )
    def result(
        project_session_id: str,
        _capability: Annotated[Capability, Depends(dependencies.capability)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> SessionResultView:
        return session_result(repository, project_session_id)

    @router.put("/api/note", response_model=ActionView)
    def note(
        body: NoteRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        actor_id: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.write_note(repository, body.markdown, actor_id=actor_id, idempotency_key=key)
        return ActionView(result="recorded")

    @router.post("/api/indicators", response_model=ActionView)
    def indicator(
        body: IndicatorRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        actor_id: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.register_indicator(
            repository,
            indicator_id=body.indicator_id,
            label=body.label,
            description=body.description,
            definition_path=Path(body.definition_path),
            subject_kind=body.subject_kind,
            unit=body.unit,
            role=body.role,
            actor_id=actor_id,
            idempotency_key=key,
        )
        return ActionView(result="registered", id=body.indicator_id)

    @router.patch("/api/indicators/{indicator_id}", response_model=ActionView)
    def indicator_update(
        indicator_id: str,
        body: IndicatorUpdateRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _actor: Annotated[str, Depends(dependencies.actor_id)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.update_indicator(
            repository,
            indicator_id,
            role=body.role,
            evidence_session_ids=body.evidence_session_ids,
            idempotency_key=key,
        )
        return ActionView(result="updated", id=indicator_id)

    @router.post("/api/indicator-values", response_model=ActionView)
    def indicator_value(
        body: IndicatorValueRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        authenticated_actor: Annotated[Actor, Depends(dependencies.actor)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.record_indicator_value(
            repository,
            indicator_id=body.indicator_id,
            subject_id=body.subject_id,
            variant_id=body.variant_id,
            value=body.value,
            guard_result=body.guard_result,
            actor=authenticated_actor,
            idempotency_key=key,
        )
        return ActionView(result="recorded")

    return router
