"""Project Authority use cases: policy, Current Best, simplification, and export."""

from pathlib import Path
from typing import Literal, cast

from abar.app.actors import Actor
from abar.app.command_support import CommandError, existing_operation, operation_key, request_hash
from abar.app.comparison_events import append_prepared_comparisons
from abar.app.event_payloads import recipe_payload
from abar.app.events import child_key, draft
from abar.app.exporting import ExportResult, write_project_export
from abar.app.repository import WorkspaceRepository
from abar.app.state import ABARState
from abar.compare.models import AudioObject, RecipeRef
from abar.compare.service import PreparedComparison, build_comparison
from abar.foundation.json_types import JSONValue
from abar.foundation.time_ids import new_id
from abar.project.models import SimplificationPlan
from abar.project.service import simplification_can_be_decided


def change_brief(
    repository: WorkspaceRepository,
    *,
    text: str,
    human_quote: str,
    actor_id: str,
    idempotency_key: str | None = None,
) -> bool:
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "project.brief.change",
        {"text": text, "human_quote": human_quote, "actor_id": actor_id},
    )
    if (
        existing_operation(
            repository,
            key,
            "project.brief.changed",
            request_hash=fingerprint,
        )
        is not None
    ):
        return True
    project = repository.state().project.project
    if project is None:
        raise CommandError("Project does not exist")
    normalized = text.strip()
    if normalized == project.brief_text:
        return False
    if not human_quote.strip():
        raise CommandError("human quote is required")
    repository.events.append(
        draft(
            "project.brief.changed",
            {
                "project_id": project.id,
                "revision": project.brief_revision + 1,
                "text": normalized,
                "human_quote": human_quote,
                "actor_id": actor_id,
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )
    return True


def configure_project(
    repository: WorkspaceRepository,
    *,
    recipe: RecipeRef | None = None,
    ready_session_limit: int | None = None,
    idempotency_key: str | None = None,
) -> bool:
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "project.configure",
        {
            "recipe": None if recipe is None else recipe_payload(recipe),
            "ready_session_limit": ready_session_limit,
        },
    )
    if (
        existing_operation(
            repository,
            key,
            "project.config.changed",
            request_hash=fingerprint,
        )
        is not None
    ):
        return True
    project = repository.state().project.project
    if project is None:
        raise CommandError("Project does not exist")
    payload: dict[str, JSONValue] = {
        "project_id": project.id,
        "request_hash": fingerprint,
    }
    if recipe is not None and recipe != project.primary_recipe:
        payload["primary_recipe"] = recipe_payload(recipe)
    if ready_session_limit is not None and ready_session_limit != project.ready_session_limit:
        if ready_session_limit < 1:
            raise CommandError("ready Session limit must be positive")
        payload["ready_session_limit"] = ready_session_limit
    if len(payload) == 2:
        return False
    repository.events.append(draft("project.config.changed", payload, idempotency_key=key))
    return True


def set_current_best_manual(
    repository: WorkspaceRepository,
    variant_id: str,
    *,
    ack: str,
    actor: Actor,
    idempotency_key: str | None = None,
) -> None:
    try:
        actor.require_human()
    except PermissionError as error:
        raise CommandError("human authority is required") from error
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "current_best.set_manual",
        {"variant_id": variant_id, "ack": ack, "actor_id": actor.id},
    )
    if (
        existing_operation(
            repository,
            key,
            "current_best.changed",
            request_hash=fingerprint,
        )
        is not None
    ):
        return
    state = repository.state()
    project = state.project.project
    if project is None:
        raise CommandError("Project does not exist")
    if any(
        runtime.status in {"active", "paused"} for runtime in state.compare.session_runtime.values()
    ):
        raise CommandError("manual current best change is disabled during an active Session")
    if variant_id == project.current_best_variant_id or (
        variant_id != "source" and variant_id not in state.compare.variants
    ):
        raise CommandError("manual current best target is invalid")
    if not ack.strip():
        raise CommandError("acknowledgement is required")
    repository.events.append(
        draft(
            "current_best.changed",
            {
                "project_id": project.id,
                "from_variant_id": project.current_best_variant_id,
                "to_variant_id": variant_id,
                "basis": "manual",
                "basis_ref": None,
                "ack": ack,
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )


def create_simplification(
    repository: WorkspaceRepository,
    *,
    simple_variant_id: str,
    reason: str,
    scope_clip_ids: tuple[str, ...],
    idempotency_key: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "simplification.create",
        {
            "simple_variant_id": simple_variant_id,
            "reason": reason,
            "scope_clip_ids": list(scope_clip_ids),
        },
    )
    existing = existing_operation(
        repository,
        key,
        "simplification.planned",
        request_hash=fingerprint,
    )
    if existing is not None:
        return cast(str, existing.payload["plan_id"])
    state = repository.state()
    project = state.project.project
    if project is None:
        raise CommandError("Project does not exist")
    if not reason.strip() or not scope_clip_ids or len(set(scope_clip_ids)) != len(scope_clip_ids):
        raise CommandError("reason and distinct scope Clips are required")
    if simple_variant_id == project.current_best_variant_id:
        raise CommandError("simple Variant must differ from current best")
    if simple_variant_id != "source" and simple_variant_id not in state.compare.variants:
        raise CommandError("unknown simple Variant")
    project_clips = {
        clip_id
        for material_id in project.material_ids
        for clip_id in state.compare.materials[material_id].clip_ids
    }
    if any(clip_id not in project_clips for clip_id in scope_clip_ids):
        raise CommandError("Simplification scope must contain attached Project Clips")

    plan_id = new_id("simple_")
    comparisons: list[PreparedComparison] = []
    render_cache: dict[str, AudioObject] = {}
    try:
        for clip_id in scope_clip_ids:
            built = build_comparison(
                _variant_operand(project.current_best_variant_id, clip_id, state),
                _variant_operand(simple_variant_id, clip_id, state),
                project.primary_recipe,
                state=state.compare,
                objects=repository.objects,
                render_cache=render_cache,
            )
            comparisons.append(built)
            if not built.byte_identical:
                raise CommandError("Simplification outputs are not byte-identical")
    except (OSError, ValueError) as error:
        raise CommandError(str(error)) from error

    SimplificationPlan(
        id=plan_id,
        project_id=project.id,
        incumbent_variant_id=project.current_best_variant_id,
        simple_variant_id=simple_variant_id,
        reason=reason.strip(),
        scope_clip_ids=scope_clip_ids,
        recipe_snapshot=project.primary_recipe,
        created_event_seq=0,
    )

    with repository.events.transaction(causation_id=key) as tx:
        tx.append(
            draft(
                "simplification.planned",
                {
                    "plan_id": plan_id,
                    "project_id": project.id,
                    "incumbent_variant_id": project.current_best_variant_id,
                    "simple_variant_id": simple_variant_id,
                    "reason": reason.strip(),
                    "scope_clip_ids": list(scope_clip_ids),
                    "recipe_snapshot": recipe_payload(project.primary_recipe),
                    "request_hash": fingerprint,
                },
                idempotency_key=child_key(key, 0),
            )
        )
        append_prepared_comparisons(tx, key, comparisons, start_index=1)
    return plan_id


def decide_simplification(
    repository: WorkspaceRepository,
    plan_id: str,
    *,
    decision: Literal["accept", "keep"],
    actor: Actor,
    idempotency_key: str | None = None,
) -> None:
    try:
        actor.require_human()
    except PermissionError as error:
        raise CommandError("human authority is required") from error
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "simplification.decide",
        {"plan_id": plan_id, "decision": decision, "actor_id": actor.id},
    )
    if (
        existing_operation(
            repository,
            key,
            "simplification.decided",
            request_hash=fingerprint,
        )
        is not None
    ):
        return
    state = repository.state()
    try:
        plan = simplification_can_be_decided(state.project, plan_id)
    except ValueError as error:
        raise CommandError(str(error)) from error
    project = state.project.project
    assert project is not None
    with repository.events.transaction(causation_id=key) as tx:
        tx.append(
            draft(
                "simplification.decided",
                {
                    "plan_id": plan_id,
                    "decision": decision,
                    "request_hash": fingerprint,
                },
                idempotency_key=child_key(key, 0),
            )
        )
        if decision == "accept":
            tx.append(
                draft(
                    "current_best.changed",
                    {
                        "project_id": project.id,
                        "from_variant_id": plan.incumbent_variant_id,
                        "to_variant_id": plan.simple_variant_id,
                        "basis": "simplification",
                        "basis_ref": plan.id,
                        "ack": None,
                    },
                    idempotency_key=child_key(key, 1),
                )
            )


def export_project(
    repository: WorkspaceRepository,
    variant_id: str,
    *,
    output: Path,
    actor: Actor,
    render_clips: Path | None = None,
    idempotency_key: str | None = None,
) -> ExportResult:
    try:
        actor.require_human()
    except PermissionError as error:
        raise CommandError("human authority is required") from error
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "project.export",
        {
            "variant_id": variant_id,
            "output": str(output.expanduser().resolve()),
            "render_clips": None
            if render_clips is None
            else str(render_clips.expanduser().resolve()),
        },
    )
    existing = existing_operation(repository, key, "in_use.recorded", request_hash=fingerprint)
    if existing is not None:
        if not output.is_file():
            raise CommandError("export event exists but output file is missing")
        return ExportResult(variant_id, output, ())
    state = repository.state()
    try:
        result = write_project_export(
            state.compare,
            state.project,
            variant_id,
            output,
            objects=repository.objects,
            render_clips=render_clips,
        )
    except (OSError, ValueError) as error:
        raise CommandError(str(error)) from error
    project = state.project.project
    assert project is not None
    repository.events.append(
        draft(
            "in_use.recorded",
            {
                "project_id": project.id,
                "variant_id": variant_id,
                "output": str(output.resolve()),
                "render_clips": None if render_clips is None else str(render_clips.resolve()),
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )
    return result


def _variant_operand(variant: str, clip_id: str, state: ABARState) -> str:
    if variant == "source":
        material_id = state.compare.clips[clip_id].material_id
        return f"source:{material_id}#{clip_id}"
    return f"variant:{variant}#{clip_id}"
