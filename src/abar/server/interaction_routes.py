# pyright: reportUnusedFunction=false
"""Human interaction routes and sealed browser audio delivery."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from abar.app import commands
from abar.app.actors import Actor
from abar.app.queries import active_deck, session_completion
from abar.app.repository import WorkspaceRepository
from abar.app.views import ActionView, ActiveDeckView, SessionCompletionView
from abar.compare.models import BlockerInput, Telemetry
from abar.server.audio_tokens import AudioTokenStore
from abar.server.dependencies import ServerDependencies
from abar.server.errors import error_response
from abar.server.request_models import (
    JudgmentRequest,
    ManualBestRequest,
    MemoRequest,
    SessionStartRequest,
    SimplificationDecisionRequest,
    SkipRequest,
)


def build_interaction_router(
    dependencies: ServerDependencies, audio_tokens: AudioTokenStore
) -> APIRouter:
    router = APIRouter()
    repository_dependency = Depends(dependencies.repository)

    @router.post("/api/project/current-best/manual", response_model=ActionView)
    def manual_best(
        body: ManualBestRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.set_current_best_manual(
            repository,
            body.variant_id,
            ack=body.ack,
            actor=Actor("human", "human"),
            idempotency_key=key,
        )
        return ActionView(result="changed", id=body.variant_id)

    @router.post("/api/simplifications/{plan_id}/decision", response_model=ActionView)
    def simplification_decision(
        plan_id: str,
        body: SimplificationDecisionRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.decide_simplification(
            repository,
            plan_id,
            decision=body.decision,
            actor=Actor("human", "human"),
            idempotency_key=key,
        )
        return ActionView(result=body.decision, id=plan_id)

    @router.post("/api/sessions/{session_id}/start", response_model=ActionView)
    def start(
        session_id: str,
        body: SessionStartRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.start_session(
            repository,
            session_id,
            allocation_seed=body.allocation_seed,
            idempotency_key=key,
        )
        return ActionView(result="started", id=session_id)

    @router.post("/api/sessions/{session_id}/pause", response_model=ActionView)
    def pause(
        session_id: str,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.pause_session(repository, session_id, paused=True, idempotency_key=key)
        return ActionView(result="paused", id=session_id)

    @router.post("/api/sessions/{session_id}/resume", response_model=ActionView)
    def resume(
        session_id: str,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.pause_session(repository, session_id, paused=False, idempotency_key=key)
        return ActionView(result="active", id=session_id)

    @router.post("/api/sessions/{session_id}/abandon", response_model=ActionView)
    def abandon(
        session_id: str,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.abandon_session(repository, session_id, idempotency_key=key)
        return ActionView(result="ended", id=session_id)

    @router.post("/api/sessions/{session_id}/reveal", response_model=ActionView)
    def reveal(
        session_id: str,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.reveal_session(repository, session_id, idempotency_key=key)
        return ActionView(result="revealed", id=session_id)

    @router.get("/api/deck/active", response_model=ActiveDeckView)
    def deck(
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActiveDeckView:
        return active_deck(
            repository,
            audio_url=lambda _delivery_id, _slot, audio_id: audio_tokens.issue(
                repository.root, audio_id
            ),
        )

    @router.get("/api/sessions/{session_id}/completion", response_model=SessionCompletionView)
    def completion(
        session_id: str,
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> SessionCompletionView:
        return session_completion(
            repository,
            session_id,
            audio_url=lambda _delivery_id, _slot, audio_id: audio_tokens.issue(
                repository.root, audio_id
            ),
        )

    @router.post("/api/deliveries/{delivery_id}/judgments", response_model=ActionView)
    def judgment(
        delivery_id: str,
        body: JudgmentRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        judgment_id = commands.record_judgment(
            repository,
            delivery_id,
            preference=body.preference,
            blocker_a=BlockerInput(**body.blockers["a"].model_dump()),
            blocker_b=BlockerInput(**body.blockers["b"].model_dump()),
            comment=body.comment,
            telemetry=Telemetry(**body.telemetry.model_dump()),
            idempotency_key=key,
        )
        state = repository.state()
        session_id = state.compare.deliveries[delivery_id].session_id
        result = (
            "ended" if state.compare.session_runtime[session_id].status == "ended" else "recorded"
        )
        return ActionView(result=result, id=judgment_id)

    @router.post("/api/deliveries/{delivery_id}/skip", response_model=ActionView)
    def skip(
        delivery_id: str,
        body: SkipRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.skip_delivery(
            repository, delivery_id, confirmed=body.confirmed, idempotency_key=key
        )
        return ActionView(result="skipped", id=delivery_id)

    @router.post("/api/project-sessions/{project_session_id}/memo", response_model=ActionView)
    def memo(
        project_session_id: str,
        body: MemoRequest,
        key: Annotated[str, Depends(dependencies.idempotency_key)],
        _human: Annotated[None, Depends(dependencies.interaction)],
        repository: WorkspaceRepository = repository_dependency,
    ) -> ActionView:
        commands.record_session_memo(repository, project_session_id, body.text, idempotency_key=key)
        return ActionView(result="recorded", id=project_session_id)

    @router.get("/api/audio/{token}")
    def audio(token: str) -> Response:
        record = audio_tokens.consume(token)
        if record is None:
            return error_response(404, "audio_token_invalid", "audio token is missing or expired")
        root, audio_id = record
        repository = WorkspaceRepository.open(root)
        try:
            audio_object = repository.state().compare.audio[audio_id]
            return Response(
                content=repository.objects.read(audio_object.object_id),
                media_type="audio/wav",
                headers={"Cache-Control": "no-store"},
            )
        finally:
            repository.close()

    return router
