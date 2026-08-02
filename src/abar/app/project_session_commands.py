"""Project Session planning and inventory lifecycle commands."""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, cast

from abar.app.command_support import (
    CommandError,
    operation_key,
)
from abar.app.command_support import (
    existing_operation as _existing_operation,
)
from abar.app.command_support import (
    request_hash as _request_hash,
)
from abar.app.comparison_events import append_prepared_comparisons
from abar.app.event_payloads import (
    criterion_payload as _criterion_payload,
)
from abar.app.event_payloads import (
    recipe_payload as _recipe_payload,
)
from abar.app.event_payloads import (
    session_payload as _session_payload,
)
from abar.app.events import child_key, draft
from abar.app.repository import WorkspaceRepository
from abar.app.state import ABARState
from abar.compare.models import (
    AudioObject,
    ComparisonPlan,
    CriterionSnapshot,
    PreparedPair,
    RecipeRef,
    ResolvedOperand,
)
from abar.compare.planning import comparison_plan, core_session
from abar.compare.service import PreparedComparison, build_comparison
from abar.foundation.canonical_json import canonical_sha256
from abar.foundation.json_types import JSONValue
from abar.foundation.time_ids import new_id
from abar.project.models import BestUpdatePlan
from abar.research.clip_selection import (
    EvidenceClipSelection,
    explicit_selection,
    random_selection,
)
from abar.research.models import ProjectSession
from abar.research.planner import (
    best_update_session_fingerprint,
    item_roles,
    observation_session_fingerprint,
)
from abar.research.session_sizes import SessionSize, resolve_evidence_count

__all__ = [
    "SessionPreparationProgress",
    "close_project_session",
    "create_best_update_session",
    "create_observation_session",
]


@dataclass(frozen=True, slots=True)
class SessionPreparationProgress:
    stage: Literal["started", "completed"]
    current: int
    total: int
    clip_id: str
    material_id: str


def create_observation_session(
    repository: WorkspaceRepository,
    *,
    first_variant: str,
    second_variant: str,
    focus: str,
    size: SessionSize = "short",
    evidence_count: int | None = None,
    recipe: RecipeRef | None = None,
    topic_key: str | None = None,
    clip_ids: tuple[str, ...] = (),
    same_check: bool = False,
    repeat_check: bool = False,
    actor_id: str,
    actor_type: Literal["agent", "human"] = "agent",
    idempotency_key: str | None = None,
    progress: Callable[[SessionPreparationProgress], None] | None = None,
) -> str:
    return _create_project_session(
        repository,
        first_variant=first_variant,
        second_variant=second_variant,
        focus=focus,
        size=size,
        evidence_count=evidence_count,
        recipe=recipe,
        topic_key=topic_key,
        clip_ids=clip_ids,
        same_check=same_check,
        repeat_check=repeat_check,
        actor_id=actor_id,
        actor_type=actor_type,
        idempotency_key=idempotency_key,
        progress=progress,
    )


def create_best_update_session(
    repository: WorkspaceRepository,
    *,
    proposed_variant: str,
    topic_key: str | None = None,
    clip_ids: tuple[str, ...] = (),
    actor_id: str,
    actor_type: Literal["agent", "human"] = "agent",
    idempotency_key: str | None = None,
    progress: Callable[[SessionPreparationProgress], None] | None = None,
) -> str:
    return _create_project_session(
        repository,
        proposed_variant=proposed_variant,
        update_best=True,
        topic_key=topic_key,
        clip_ids=clip_ids,
        actor_id=actor_id,
        actor_type=actor_type,
        idempotency_key=idempotency_key,
        progress=progress,
    )


def _create_project_session(
    repository: WorkspaceRepository,
    *,
    first_variant: str | None = None,
    second_variant: str | None = None,
    proposed_variant: str | None = None,
    update_best: bool = False,
    focus: str | None = None,
    size: SessionSize = "short",
    evidence_count: int | None = None,
    recipe: RecipeRef | None = None,
    topic_key: str | None = None,
    clip_ids: tuple[str, ...] = (),
    same_check: bool = False,
    repeat_check: bool = False,
    actor_id: str,
    actor_type: Literal["agent", "human"] = "agent",
    idempotency_key: str | None = None,
    progress: Callable[[SessionPreparationProgress], None] | None = None,
) -> str:
    key = operation_key(idempotency_key)
    request_data: dict[str, JSONValue] = {
        "first_variant": first_variant,
        "second_variant": second_variant,
        "proposed_variant": proposed_variant,
        "focus": focus,
        "size": size,
        "recipe": None if recipe is None else _recipe_payload(recipe),
        "topic_key": topic_key,
        "clip_ids": list(clip_ids),
        "same_check": same_check,
        "repeat_check": repeat_check,
        "actor_id": actor_id,
        "actor_type": actor_type,
    }
    if evidence_count is not None:
        request_data["evidence_count"] = evidence_count
    request_hash = _request_hash(
        "best_update_session.create" if update_best else "observation_session.create",
        request_data,
    )
    existing = _existing_operation(
        repository, key, "project_session.created", request_hash=request_hash
    )
    if existing is not None:
        return cast(str, existing.payload["project_session_id"])
    state = repository.state()
    project = state.project.project
    if project is None:
        raise CommandError("Project does not exist")
    if update_best:
        if proposed_variant is None:
            raise CommandError("--update-best requires proposed Variant")
        first_variant, second_variant = project.current_best_variant_id, proposed_variant
        if first_variant == second_variant:
            raise CommandError("Best Update proposal must differ from Current Best")
        size = "standard"
        evidence_count = 3
        selected_recipe = project.primary_recipe
        selected_focus = focus or "現在最良を更新できるか"
    else:
        if first_variant is None or second_variant is None or focus is None:
            raise CommandError("general Session requires pair and focus")
        selected_recipe = recipe or project.primary_recipe
        selected_focus = focus
    assert first_variant is not None and second_variant is not None
    count = resolve_evidence_count(size, evidence_count)
    selection = _select_evidence_clips(state, clip_ids, count)
    selected_clips = selection.clip_ids
    _check_wip(state, project.id)
    fingerprint = (
        best_update_session_fingerprint(
            brief_revision=project.brief_revision,
            incumbent_variant_id=first_variant,
            proposed_variant_id=second_variant,
            evidence_clip_ids=selected_clips,
            recipe=selected_recipe,
        )
        if update_best
        else observation_session_fingerprint(
            pair=(first_variant, second_variant),
            focus=selected_focus,
            evidence_clip_ids=selected_clips,
            recipe=selected_recipe,
            same_check=same_check,
            repeat_check=repeat_check,
        )
    )
    for existing in state.research.project_sessions.values():
        runtime = state.compare.session_runtime[existing.core_session_id]
        if existing.fingerprint == fingerprint and runtime.status not in {"ended", "closed"}:
            raise CommandError("an unfinished Session with the same fingerprint already exists")
    evidence_data: list[PreparedComparison] = []
    render_cache: dict[str, AudioObject] = {}
    for index, clip_id in enumerate(selected_clips, start=1):
        material_id = state.compare.clips[clip_id].material_id
        if progress is not None:
            progress(SessionPreparationProgress("started", index, count, clip_id, material_id))
        left_text = _variant_operand(first_variant, clip_id, state)
        right_text = _variant_operand(second_variant, clip_id, state)
        built = build_comparison(
            left_text,
            right_text,
            selected_recipe,
            state=state.compare,
            objects=repository.objects,
            render_cache=render_cache,
        )
        evidence_data.append(built)
        if progress is not None:
            progress(SessionPreparationProgress("completed", index, count, clip_id, material_id))
    roles = item_roles(
        size,
        evidence_count=count,
        same_check=same_check,
        repeat_check=repeat_check,
    )
    ordered_comparisons: list[ComparisonPlan] = []
    same_comparison: ComparisonPlan | None = None
    for role in roles:
        if role.role == "evidence" or role.role == "repeat":
            ordered_comparisons.append(evidence_data[role.evidence_index].comparison)
        else:
            if same_comparison is None:
                source_pair = evidence_data[role.evidence_index].prepared_pair
                audio_id = source_pair.output_audio_by_input_key["p1"]
                operand_a = ResolvedOperand("p1", audio_id, {"kind": "check"})
                operand_b = ResolvedOperand("p2", audio_id, {"kind": "check"})
                same_identity: dict[str, JSONValue] = {
                    "same_audio_id": audio_id,
                    "recipe": _recipe_payload(selected_recipe),
                }
                same_pair = PreparedPair(
                    id=f"pp_{canonical_sha256(same_identity)}",
                    input_audio_ids=(audio_id, audio_id),
                    recipe=selected_recipe,
                    output_audio_by_input_key={"p1": audio_id, "p2": audio_id},
                    features={},
                    warnings=(),
                    no_effect=True,
                )
                same_comparison = comparison_plan(operand_a, operand_b, same_pair, selected_recipe)
            ordered_comparisons.append(same_comparison)
    criterion = CriterionSnapshot(
        text=project.brief_text if update_best else selected_focus,
        source="project_brief" if update_best else "focus",
        source_event_seq=state.project.last_brief_change_seq if update_best else None,
    )
    session = core_session(
        tuple(item.id for item in ordered_comparisons),
        presentation="blind",
        reveal_policy="on_end",
        criterion=criterion,
    )
    evidence_items = tuple(
        session.items[index].id for index, role in enumerate(roles) if role.role == "evidence"
    )
    same_item = next(
        (session.items[index].id for index, role in enumerate(roles) if role.role == "same"), None
    )
    repeat_item = next(
        (session.items[index].id for index, role in enumerate(roles) if role.role == "repeat"), None
    )
    project_session_id = new_id("ps_")
    project_session_payload: dict[str, JSONValue] = {
        "project_session_id": project_session_id,
        "project_id": project.id,
        "core_session_id": session.id,
        "focus": selected_focus,
        "topic_key": topic_key,
        "size": size,
        "pair": [first_variant, second_variant],
        "recipe": _recipe_payload(selected_recipe),
        "evidence_item_ids": list(evidence_items),
        "evidence_clip_ids": list(selected_clips),
        "selection_algorithm_id": selection.algorithm_id,
        "selection_algorithm_version": selection.algorithm_version,
        "selection_seed": selection.seed,
        "same_check_item_id": same_item,
        "repeat_check_item_id": repeat_item,
        "repeat_of_item_id": evidence_items[0] if repeat_item else None,
        "created_by_type": actor_type,
        "created_by_id": actor_id,
        "fingerprint": fingerprint,
        "request_hash": request_hash,
    }
    ProjectSession(
        id=project_session_id,
        project_id=project.id,
        core_session_id=session.id,
        focus=selected_focus,
        topic_key=topic_key,
        size=size,
        pair=(first_variant, second_variant),
        recipe=selected_recipe,
        evidence_item_ids=evidence_items,
        evidence_clip_ids=selected_clips,
        selection_algorithm_id=selection.algorithm_id,
        selection_algorithm_version=selection.algorithm_version,
        selection_seed=selection.seed,
        same_check_item_id=same_item,
        repeat_check_item_id=repeat_item,
        repeat_of_item_id=evidence_items[0] if repeat_item else None,
        created_by_type=actor_type,
        created_by_id=actor_id,
        fingerprint=fingerprint,
    )
    plan_id: str | None = None
    if update_best:
        if all(item.prepared_pair.no_effect for item in evidence_data):
            raise CommandError(
                "Best Update has no audible evidence; create a Simplification Plan instead"
            )
        plan_id = new_id("best_")
        BestUpdatePlan(
            id=plan_id,
            project_id=project.id,
            session_id=session.id,
            incumbent_variant_id=first_variant,
            proposed_variant_id=second_variant,
            evidence_item_ids=cast(tuple[str, str, str], evidence_items),
            brief_revision=project.brief_revision,
            brief_text=project.brief_text,
            recipe_snapshot=selected_recipe,
            created_event_seq=0,
        )
    with repository.events.transaction(causation_id=key) as tx:
        index = append_prepared_comparisons(tx, key, evidence_data, same_comparison=same_comparison)
        created = tx.append(
            draft(
                "project_session.created",
                project_session_payload,
                idempotency_key=child_key(key, index),
            )
        )
        index += 1
        criterion_payload = _criterion_payload(session.criterion)
        if not update_best and criterion_payload is not None:
            criterion_payload["source_event_seq"] = created.event_seq
        tx.append(
            draft(
                "session.planned",
                _session_payload(session, criterion_override=criterion_payload),
                idempotency_key=child_key(key, index),
            )
        )
        index += 1
        if update_best:
            assert plan_id is not None
            tx.append(
                draft(
                    "best_update.planned",
                    {
                        "plan_id": plan_id,
                        "project_id": project.id,
                        "session_id": session.id,
                        "incumbent_variant_id": first_variant,
                        "proposed_variant_id": second_variant,
                        "evidence_item_ids": list(evidence_items),
                        "brief_revision": project.brief_revision,
                        "brief_text": project.brief_text,
                        "recipe_snapshot": _recipe_payload(selected_recipe),
                        "warning": None
                        if selected_recipe.id == "matched"
                        else "primary_recipe_not_matched",
                    },
                    idempotency_key=child_key(key, index),
                )
            )
    return project_session_id


def close_project_session(
    repository: WorkspaceRepository,
    project_session_id: str,
    *,
    actor_id: str,
    idempotency_key: str | None = None,
) -> None:
    key = operation_key(idempotency_key)
    request_hash = _request_hash(
        "project_session.close",
        {"project_session_id": project_session_id, "actor_id": actor_id},
    )
    if (
        _existing_operation(
            repository,
            key,
            "session.ended",
            request_hash=request_hash,
        )
        is not None
    ):
        return
    state = repository.state()
    project_session = state.research.project_sessions[project_session_id]
    runtime = state.compare.session_runtime[project_session.core_session_id]
    if runtime.status != "ready" or project_session.created_by_id != actor_id:
        raise CommandError("only the creating actor may close an unstarted Session")
    repository.events.append(
        draft(
            "session.ended",
            {
                "session_id": project_session.core_session_id,
                "outcome": "closed",
                "abandoned": False,
                "actor_id": actor_id,
                "request_hash": request_hash,
            },
            idempotency_key=key,
        )
    )


def _select_evidence_clips(
    state: ABARState, requested: tuple[str, ...], count: int
) -> EvidenceClipSelection:
    project = state.project.project
    assert project is not None
    if requested:
        if len(requested) != count or len(set(requested)) != count:
            raise CommandError(f"Session requires exactly {count} distinct Clip IDs")
        if any(item not in state.compare.clips for item in requested):
            raise CommandError("unknown Clip")
        selection = explicit_selection(requested)
    else:
        try:
            selection = random_selection(
                material_ids=project.material_ids,
                materials=state.compare.materials,
                clips=state.compare.clips,
                count=count,
                seed=secrets.randbits(63),
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
    return selection


def _check_wip(state: ABARState, project_id: str) -> None:
    project = state.project.project
    if project is None:
        raise CommandError("Project does not exist")
    ready = sum(
        state.compare.session_runtime[item.core_session_id].status == "ready"
        for item in state.research.project_sessions.values()
        if item.project_id == project_id
    )
    if ready >= project.ready_session_limit:
        raise CommandError("ready_session_limit_reached")


def _variant_operand(variant: str, clip_id: str, state: ABARState) -> str:
    if variant == "source":
        material_id = state.compare.clips[clip_id].material_id
        return f"source:{material_id}#{clip_id}"
    return f"variant:{variant}#{clip_id}"
