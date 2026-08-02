"""Project-independent Core Session lifecycle commands."""

import hashlib
import secrets
from dataclasses import replace
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
    delivery_payload as _delivery_payload,
)
from abar.app.event_payloads import (
    judgment_payload as _judgment_payload,
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
from abar.compare.audio.content import decode_wav_bytes
from abar.compare.audio.importing import import_input_audio_file
from abar.compare.audio.signal import common_active_range
from abar.compare.models import (
    BlockerInput,
    Judgment,
    RecipeRef,
    Session,
    Telemetry,
)
from abar.compare.operands import parse_file_operand
from abar.compare.planning import allocate_deliveries, core_session
from abar.compare.service import PreparedComparison, build_comparison
from abar.foundation.json_types import JSONValue
from abar.foundation.time_ids import new_id
from abar.project.current_best import evaluate_best_update
from abar.project.models import BestEvidence, BestUpdatePlan
from abar.research.models import ProjectSession

__all__ = [
    "abandon_session",
    "create_quick_listen",
    "pause_session",
    "record_judgment",
    "reveal_session",
    "skip_delivery",
    "start_session",
]


def create_quick_listen(
    repository: WorkspaceRepository,
    first: str,
    second: str,
    *,
    recipe: RecipeRef | None = None,
    presentation: Literal["open", "blind"] = "open",
    idempotency_key: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    selected_recipe = recipe or RecipeRef("aligned")
    request_hash = _request_hash(
        "quick_listen.create",
        {
            "first": first,
            "second": second,
            "recipe": _recipe_payload(selected_recipe),
            "presentation": presentation,
        },
    )
    existing = _existing_operation(
        repository,
        key,
        "session.planned",
        request_hash=request_hash,
    )
    if existing is not None:
        return cast(str, existing.payload["session_id"])
    first, second = _apply_automatic_file_range(repository, first, second)
    state = repository.state()
    built = build_comparison(
        first,
        second,
        selected_recipe,
        state=state.compare,
        objects=repository.objects,
    )
    session = core_session(
        (built.comparison.id,),
        presentation=presentation,
        reveal_policy="immediate" if presentation == "open" else "after_answer_or_manual",
        criterion=None,
    )
    _persist_comparison_session(
        repository,
        key=key,
        comparisons=(built,),
        session=session,
        request_hash=request_hash,
    )
    return session.id


def start_session(
    repository: WorkspaceRepository,
    session_id: str,
    *,
    allocation_seed: int | None = None,
    idempotency_key: str | None = None,
) -> None:
    key = operation_key(idempotency_key)
    request_hash = _request_hash(
        "session.start",
        {"session_id": session_id, "allocation_seed": allocation_seed},
    )
    prior = repository.events.read_operation(key)
    prior_blocked = next((item for item in prior if item.event_type == "session.blocked"), None)
    if prior_blocked is not None:
        if prior_blocked.payload.get("request_hash") != request_hash:
            raise CommandError("idempotency key was reused with a different request")
        raise CommandError(str(prior_blocked.payload["reason"]))
    if (
        _existing_operation(
            repository,
            key,
            "session.started",
            request_hash=request_hash,
        )
        is not None
    ):
        return
    selected_seed = secrets.randbits(63) if allocation_seed is None else allocation_seed
    state = repository.state()
    session = state.compare.sessions.get(session_id)
    if session is None or state.compare.session_runtime[session_id].status != "ready":
        raise CommandError("Session is not ready")
    linked = _project_session_for_core(state, session_id)
    if linked is not None:
        for other in state.research.project_sessions.values():
            runtime = state.compare.session_runtime[other.core_session_id]
            if other.core_session_id != session_id and runtime.status in {"active", "paused"}:
                raise CommandError("another Project Session is active")
    invalid_items: list[tuple[str, str]] = []
    for item in session.items:
        comparison = state.compare.comparisons[item.comparison_id]
        pair = state.compare.prepared_pairs[comparison.prepared_pair_id]
        for audio_id in pair.output_audio_by_input_key.values():
            audio = state.compare.audio[audio_id]
            if not repository.objects.exists(audio.object_id):
                invalid_items.append((item.id, "object_missing"))
                break
            decoded = decode_wav_bytes(repository.objects.read(audio.object_id))
            pcm_sha = f"sha256:{hashlib.sha256(decoded.pcm.tobytes(order='C')).hexdigest()}"
            if pcm_sha != audio.pcm_sha:
                invalid_items.append((item.id, "object_hash_mismatch"))
                break
    evidence_invalid = False
    if linked is not None:
        evidence_invalid = any(item_id in linked.evidence_item_ids for item_id, _ in invalid_items)
    deliveries = list(allocate_deliveries(session, seed=selected_seed))
    if linked is not None and linked.repeat_check_item_id is not None:
        original = next(
            item for item in deliveries if item.session_item_id == linked.repeat_of_item_id
        )
        repeat_index = next(
            index
            for index, item in enumerate(deliveries)
            if item.session_item_id == linked.repeat_check_item_id
        )
        opposite = {"A": original.slot_assignment["B"], "B": original.slot_assignment["A"]}
        deliveries[repeat_index] = replace(deliveries[repeat_index], slot_assignment=opposite)
    invalid_ids = {item_id for item_id, _ in invalid_items}
    deliveries = [item for item in deliveries if item.session_item_id not in invalid_ids]
    with repository.events.transaction(causation_id=key) as tx:
        index = 0
        for item_id, reason in invalid_items:
            tx.append(
                draft(
                    "comparison.protocol_invalidated",
                    {"session_id": session_id, "session_item_id": item_id, "reason": reason},
                    idempotency_key=child_key(key, index),
                )
            )
            index += 1
        if evidence_invalid:
            tx.append(
                draft(
                    "session.blocked",
                    {
                        "session_id": session_id,
                        "reason": "evidence protocol invalid",
                        "request_hash": request_hash,
                    },
                    idempotency_key=child_key(key, index),
                )
            )
        else:
            tx.append(
                draft(
                    "session.started",
                    {
                        "session_id": session_id,
                        "allocation_seed": selected_seed,
                        "request_hash": request_hash,
                    },
                    idempotency_key=child_key(key, index),
                )
            )
            index += 1
            for delivery in deliveries:
                tx.append(
                    draft(
                        "comparison.delivered",
                        _delivery_payload(delivery),
                        idempotency_key=child_key(key, index),
                    )
                )
                index += 1
    if evidence_invalid:
        raise CommandError("evidence protocol invalid")


def record_judgment(
    repository: WorkspaceRepository,
    delivery_id: str,
    *,
    preference: Literal[1, 2, 3, 4, 5],
    blocker_a: BlockerInput | None = None,
    blocker_b: BlockerInput | None = None,
    comment: str | None = None,
    telemetry: Telemetry | None = None,
    idempotency_key: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    expected_blocker_a = blocker_a or BlockerInput()
    expected_blocker_b = blocker_b or BlockerInput()
    expected_telemetry = telemetry or Telemetry({"a": 0, "b": 0}, 0, 0)
    expected_judgment_payload: dict[str, JSONValue] = {
        "delivery_id": delivery_id,
        "preference": preference,
        "blockers": {
            "a": {
                "selected": expected_blocker_a.selected,
                "note": expected_blocker_a.note,
            },
            "b": {
                "selected": expected_blocker_b.selected,
                "note": expected_blocker_b.note,
            },
        },
        "comment": comment,
        "telemetry": {
            "listen_ms": {
                "a": expected_telemetry.listen_ms["a"],
                "b": expected_telemetry.listen_ms["b"],
            },
            "switches": expected_telemetry.switches,
            "answer_ms": expected_telemetry.answer_ms,
        },
    }
    request_hash = _request_hash("judgment.record", expected_judgment_payload)
    existing = _existing_operation(
        repository,
        key,
        "judgment.recorded",
        request_hash=request_hash,
    )
    if existing is not None:
        return cast(str, existing.payload["judgment_id"])
    state = repository.state()
    delivery = state.compare.deliveries.get(delivery_id)
    if delivery is None:
        raise CommandError("unknown Delivery")
    session = state.compare.sessions[delivery.session_id]
    runtime = state.compare.session_runtime[session.id]
    if state.compare.effective_judgment(delivery_id) is not None:
        raise CommandError("Judgment is immutable once recorded")
    if runtime.status not in {"active", "paused"}:
        raise CommandError("Judgment requires an active Session")
    identity_visible = session.presentation == "open" or runtime.revealed
    judgment = Judgment(
        id=new_id("j_"),
        delivery_id=delivery_id,
        preference=preference,
        blockers={"a": expected_blocker_a, "b": expected_blocker_b},
        comment=comment,
        identity_visible_at_answer=identity_visible,
        telemetry=expected_telemetry,
    )
    should_end = runtime.status in {"active", "paused"} and _would_complete(
        state, session.id, delivery_id
    )
    with repository.events.transaction(causation_id=key) as tx:
        tx.append(
            draft(
                "judgment.recorded",
                {**_judgment_payload(judgment), "request_hash": request_hash},
                idempotency_key=child_key(key, 0),
            )
        )
        if should_end:
            tx.append(
                draft(
                    "session.ended",
                    {
                        "session_id": session.id,
                        "outcome": _completion_outcome(
                            state,
                            session.id,
                            answered_item_id=delivery.session_item_id,
                        ),
                        "abandoned": False,
                    },
                    idempotency_key=child_key(key, 1),
                )
            )
            linked = _project_session_for_core(state, session.id)
            next_index = 2
            if linked is None and session.reveal_policy == "after_answer_or_manual":
                tx.append(
                    draft(
                        "session.revealed",
                        {"session_id": session.id},
                        idempotency_key=child_key(key, next_index),
                    )
                )
            elif linked is not None:
                tx.append(
                    draft(
                        "session.revealed",
                        {"session_id": session.id},
                        idempotency_key=child_key(key, next_index),
                    )
                )
                next_index += 1
                plan = next(
                    (
                        item
                        for item in state.project.best_update_plans.values()
                        if item.session_id == session.id
                    ),
                    None,
                )
                if plan is not None:
                    evidence = _best_evidence(state, plan, replacement=judgment)
                    decision = evaluate_best_update(
                        state.project.authority_snapshot(), plan, evidence
                    )
                    if decision.update:
                        project = state.project.project
                        assert project is not None
                        tx.append(
                            draft(
                                "current_best.changed",
                                {
                                    "project_id": project.id,
                                    "from_variant_id": plan.incumbent_variant_id,
                                    "to_variant_id": plan.proposed_variant_id,
                                    "basis": "comparison",
                                    "basis_ref": plan.id,
                                    "ack": None,
                                },
                                idempotency_key=child_key(key, next_index),
                            )
                        )
    return judgment.id


def reveal_session(
    repository: WorkspaceRepository,
    session_id: str,
    *,
    idempotency_key: str | None = None,
) -> None:
    key = operation_key(idempotency_key)
    request_hash = _request_hash("session.reveal", {"session_id": session_id})
    if (
        _existing_operation(repository, key, "session.revealed", request_hash=request_hash)
        is not None
    ):
        return
    state = repository.state()
    session = state.compare.sessions.get(session_id)
    if session is None:
        raise CommandError("unknown Session")
    runtime = state.compare.session_runtime[session_id]
    if _project_session_for_core(state, session_id) is not None:
        raise CommandError("Project Session identity is sealed until Session end")
    if session.presentation != "blind" or session.reveal_policy != "after_answer_or_manual":
        raise CommandError("Session does not support manual reveal")
    if runtime.revealed:
        return
    repository.events.append(
        draft(
            "session.revealed",
            {"session_id": session_id, "request_hash": request_hash},
            idempotency_key=key,
        )
    )


def skip_delivery(
    repository: WorkspaceRepository,
    delivery_id: str,
    *,
    confirmed: bool = False,
    idempotency_key: str | None = None,
) -> None:
    key = operation_key(idempotency_key)
    request_hash = _request_hash(
        "delivery.skip", {"delivery_id": delivery_id, "confirmed": confirmed}
    )
    if (
        _existing_operation(repository, key, "comparison.skipped", request_hash=request_hash)
        is not None
    ):
        return
    state = repository.state()
    delivery = state.compare.deliveries.get(delivery_id)
    if delivery is None:
        raise CommandError("unknown Delivery")
    if state.compare.effective_judgment(delivery_id) is not None:
        raise CommandError("answered Delivery cannot be skipped")
    runtime = state.compare.session_runtime[delivery.session_id]
    if runtime.status not in {"active", "paused"}:
        raise CommandError("Delivery can only be skipped in an active Session")
    plan = next(
        (
            item
            for item in state.project.best_update_plans.values()
            if item.session_id == delivery.session_id
        ),
        None,
    )
    if plan is not None and delivery.session_item_id in plan.evidence_item_ids and not confirmed:
        raise CommandError("skip_confirmation_required")
    session = state.compare.sessions[delivery.session_id]
    should_end = _would_complete(state, session.id, skipped_delivery_id=delivery_id)
    with repository.events.transaction(causation_id=key) as tx:
        tx.append(
            draft(
                "comparison.skipped",
                {
                    "session_id": session.id,
                    "session_item_id": delivery.session_item_id,
                    "delivery_id": delivery_id,
                    "request_hash": request_hash,
                },
                idempotency_key=child_key(key, 0),
            )
        )
        if should_end:
            tx.append(
                draft(
                    "session.ended",
                    {"session_id": session.id, "outcome": "incomplete", "abandoned": False},
                    idempotency_key=child_key(key, 1),
                )
            )
            if _project_session_for_core(state, session.id) is not None:
                tx.append(
                    draft(
                        "session.revealed",
                        {"session_id": session.id},
                        idempotency_key=child_key(key, 2),
                    )
                )


def pause_session(
    repository: WorkspaceRepository,
    session_id: str,
    *,
    paused: bool,
    idempotency_key: str | None = None,
) -> None:
    key = operation_key(idempotency_key)
    request_hash = _request_hash("session.pause", {"session_id": session_id, "paused": paused})
    if (
        _existing_operation(
            repository,
            key,
            "session.paused",
            request_hash=request_hash,
        )
        is not None
    ):
        return
    state = repository.state()
    status = state.compare.session_runtime[session_id].status
    if (paused and status != "active") or (not paused and status != "paused"):
        raise CommandError("invalid pause transition")
    repository.events.append(
        draft(
            "session.paused",
            {"session_id": session_id, "paused": paused, "request_hash": request_hash},
            idempotency_key=key,
        )
    )


def abandon_session(
    repository: WorkspaceRepository, session_id: str, *, idempotency_key: str | None = None
) -> None:
    key = operation_key(idempotency_key)
    request_hash = _request_hash("session.abandon", {"session_id": session_id})
    if _existing_operation(repository, key, "session.ended", request_hash=request_hash) is not None:
        return
    state = repository.state()
    if state.compare.session_runtime[session_id].status not in {"active", "paused"}:
        raise CommandError("Session is not active")
    with repository.events.transaction(causation_id=key) as tx:
        tx.append(
            draft(
                "session.ended",
                {
                    "session_id": session_id,
                    "outcome": "incomplete",
                    "abandoned": True,
                    "request_hash": request_hash,
                },
                idempotency_key=child_key(key, 0),
            )
        )
        if _project_session_for_core(state, session_id) is not None:
            tx.append(
                draft(
                    "session.revealed",
                    {"session_id": session_id},
                    idempotency_key=child_key(key, 1),
                )
            )


def _persist_comparison_session(
    repository: WorkspaceRepository,
    *,
    key: str,
    comparisons: tuple[PreparedComparison, ...],
    session: Session,
    request_hash: str,
) -> None:
    with repository.events.transaction(causation_id=key) as tx:
        index = append_prepared_comparisons(tx, key, comparisons)
        tx.append(
            draft(
                "session.planned",
                {**_session_payload(session), "request_hash": request_hash},
                idempotency_key=child_key(key, index),
            )
        )


def _best_evidence(
    state: ABARState, plan: BestUpdatePlan, *, replacement: Judgment
) -> tuple[BestEvidence, BestEvidence, BestEvidence]:
    output: list[BestEvidence] = []
    for item_id in plan.evidence_item_ids:
        delivery = next(
            item for item in state.compare.deliveries.values() if item.session_item_id == item_id
        )
        judgment = (
            replacement
            if replacement.delivery_id == delivery.id
            else state.compare.effective_judgment(delivery.id)
        )
        if judgment is None:
            output.append(BestEvidence(item_id, None, False, None))
            continue
        comparison = state.compare.comparisons[delivery.comparison_id]
        by_key = {item.input_key: item for item in comparison.pair}
        proposed_key = next(
            key
            for key, item in by_key.items()
            if item.provenance_ref.get("variant_ref") == plan.proposed_variant_id
        )
        proposed_slot = next(
            slot for slot, key in delivery.slot_assignment.items() if key == proposed_key
        )
        score_a = 3 - judgment.preference
        score = score_a if proposed_slot == "A" else -score_a
        blocker_slot: Literal["a", "b"] = "a" if proposed_slot == "A" else "b"
        blocked = judgment.blockers[blocker_slot].selected
        output.append(BestEvidence(item_id, score, blocked, judgment.identity_visible_at_answer))
    return cast(tuple[BestEvidence, BestEvidence, BestEvidence], tuple(output))


def _apply_automatic_file_range(
    repository: WorkspaceRepository, first: str, second: str
) -> tuple[str, str]:
    try:
        first_path, first_range = parse_file_operand(first)
        second_path, second_range = parse_file_operand(second)
    except ValueError:
        return first, second
    if first_range is not None or second_range is not None:
        return first, second
    left = import_input_audio_file(first_path, objects=repository.objects).audio
    right = import_input_audio_file(second_path, objects=repository.objects).audio
    selected = common_active_range(
        decode_wav_bytes(repository.objects.read(left.object_id)),
        decode_wav_bytes(repository.objects.read(right.object_id)),
    )
    suffix = f"#{selected.start_seconds}+{selected.duration_seconds}"
    return f"file:{first_path}{suffix}", f"file:{second_path}{suffix}"


def _project_session_for_core(state: ABARState, session_id: str) -> ProjectSession | None:
    return next(
        (
            item
            for item in state.research.project_sessions.values()
            if item.core_session_id == session_id
        ),
        None,
    )


def _would_complete(
    state: ABARState,
    session_id: str,
    replacement_delivery_id: str | None = None,
    skipped_delivery_id: str | None = None,
) -> bool:
    session = state.compare.sessions[session_id]
    runtime = state.compare.session_runtime[session_id]
    delivery_by_item = {
        item.session_item_id: item
        for item in state.compare.deliveries.values()
        if item.session_id == session_id
    }
    for item in session.items:
        delivery = delivery_by_item.get(item.id)
        if delivery is None:
            if item.id in runtime.invalid_item_ids:
                continue
            return False
        if delivery.id in {replacement_delivery_id, skipped_delivery_id}:
            continue
        if (
            state.compare.effective_judgment(delivery.id) is None
            and item.id not in runtime.skipped_item_ids
        ):
            return False
    return True


def _completion_outcome(
    state: ABARState,
    session_id: str,
    *,
    answered_item_id: str | None = None,
) -> str:
    skipped = state.compare.session_runtime[session_id].skipped_item_ids
    if answered_item_id is not None:
        skipped = skipped - {answered_item_id}
    return "incomplete" if skipped else "completed"
