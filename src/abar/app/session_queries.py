"""Sealed, bounded application queries."""

from collections.abc import Callable
from typing import Literal, cast

from abar.app.query_support import labeled_identity, variant_label
from abar.app.repository import WorkspaceRepository
from abar.app.state import ABARState
from abar.app.views import (
    ActiveDeckView,
    BestUpdateEvidenceView,
    DeckAudioView,
    RelistenItemView,
    ResultBlockerView,
    ResultJudgmentView,
    SessionCompletionView,
    SessionResultView,
)
from abar.compare.sealing import public_delivery
from abar.research.models import ProjectSession
from abar.research.results import ProjectSessionResult, calculate_result


def session_result(repository: WorkspaceRepository, project_session_id: str) -> SessionResultView:
    return session_result_from_state(repository.state(), project_session_id)


def _project_session_for_core(state: ABARState, session_id: str) -> ProjectSession | None:
    return next(
        (
            item
            for item in state.research.project_sessions.values()
            if item.core_session_id == session_id
        ),
        None,
    )


def session_result_from_state(state: ABARState, project_session_id: str) -> SessionResultView:
    project_session = state.research.project_sessions[project_session_id]
    runtime = state.compare.session_runtime[project_session.core_session_id]
    if runtime.status != "ended":
        raise ValueError("Session has not ended")
    deliveries = {
        item.session_item_id: item
        for item in state.compare.deliveries.values()
        if item.session_id == project_session.core_session_id
    }
    judgments = {
        delivery.id: judgment
        for delivery in deliveries.values()
        if (judgment := state.compare.effective_judgment(delivery.id)) is not None
    }
    result = calculate_result(
        project_session,
        comparisons=state.compare.comparisons,
        deliveries_by_item=deliveries,
        judgments_by_delivery=judgments,
    )
    plan = next(
        (
            item
            for item in state.project.best_update_plans.values()
            if item.session_id == project_session.core_session_id
        ),
        None,
    )
    updated = plan is not None and any(
        item.basis_ref == plan.id for item in state.project.best_history
    )
    memos = state.research.session_memos.get(project_session_id, ())
    return SessionResultView(
        project_session_id=project_session_id,
        evidence_direction_counts=result.evidence_direction_counts,
        score_by_variant=result.score_by_variant,
        favored_variant_id=result.favored_variant_id,
        favored_variant_label=None
        if result.favored_variant_id is None
        else variant_label(state, result.favored_variant_id),
        blockers_by_variant=result.blockers_by_variant,
        same_result=result.same_result,
        repeat_result=result.repeat_result,
        difference_profile=result.difference_profile,
        current_best_updated=updated,
        best_update_evidence=None
        if plan is None
        else best_update_evidence_view(plan.proposed_variant_id, plan.evidence_item_ids, result),
        memo=memos[-1].text if memos else None,
    )


def current_best_evidence(state: ABARState) -> BestUpdateEvidenceView | None:
    if not state.project.best_history:
        return None
    change = state.project.best_history[-1]
    if change.basis != "comparison" or change.basis_ref is None:
        return None
    plan = state.project.best_update_plans[change.basis_ref]
    project_session = next(
        item
        for item in state.research.project_sessions.values()
        if item.core_session_id == plan.session_id
    )
    deliveries = {
        item.session_item_id: item
        for item in state.compare.deliveries.values()
        if item.session_id == plan.session_id
    }
    judgments = {
        delivery.id: judgment
        for delivery in deliveries.values()
        if (judgment := state.compare.effective_judgment(delivery.id)) is not None
    }
    result = calculate_result(
        project_session,
        comparisons=state.compare.comparisons,
        deliveries_by_item=deliveries,
        judgments_by_delivery=judgments,
    )
    return best_update_evidence_view(
        plan.proposed_variant_id,
        plan.evidence_item_ids,
        result,
    )


def best_update_evidence_view(
    proposed_variant_id: str,
    evidence_item_ids: tuple[str, str, str],
    result: ProjectSessionResult,
) -> BestUpdateEvidenceView:
    answered_count = sum(result.evidence_direction_counts.values())
    return BestUpdateEvidenceView(
        proposed_variant_id=proposed_variant_id,
        favorable_count=result.evidence_direction_counts[proposed_variant_id],
        answered_count=answered_count,
        evidence_count=len(evidence_item_ids),
        score_sum=result.score_by_variant[proposed_variant_id],
        blocker_count=len(result.blockers_by_variant[proposed_variant_id]),
    )


def active_deck(
    repository: WorkspaceRepository,
    *,
    audio_url: Callable[[str, str, str], str],
) -> ActiveDeckView:
    state = repository.state()
    session_id = next(
        (
            session_id
            for session_id, runtime in state.compare.session_runtime.items()
            if runtime.status in {"active", "paused"}
        ),
        None,
    )
    if session_id is None:
        return ActiveDeckView(
            session_id=None,
            project_session_id=None,
            status=None,
            delivery_id=None,
            sequence_index=None,
            comparison_count=0,
            presentation=None,
            criterion_label=None,
            criterion_text=None,
            question=None,
            current_best_check=False,
            audio=(),
            identity_by_slot=None,
            can_reveal=False,
            ended=False,
        )
    session = state.compare.sessions[session_id]
    runtime = state.compare.session_runtime[session_id]
    deliveries = sorted(
        (item for item in state.compare.deliveries.values() if item.session_id == session_id),
        key=lambda item: item.sequence_index,
    )
    delivery = next(
        (
            item
            for item in deliveries
            if state.compare.effective_judgment(item.id) is None
            and item.session_item_id not in runtime.skipped_item_ids
        ),
        deliveries[-1],
    )
    comparison = state.compare.comparisons[delivery.comparison_id]
    prepared = state.compare.prepared_pairs[comparison.prepared_pair_id]
    public = public_delivery(
        session,
        delivery,
        comparison,
        session_revealed=runtime.revealed,
        delivery_answered=state.compare.effective_judgment(delivery.id) is not None,
    )
    project_session = next(
        (
            item
            for item in state.research.project_sessions.values()
            if item.core_session_id == session_id
        ),
        None,
    )
    plan = next(
        (
            item
            for item in state.project.best_update_plans.values()
            if item.session_id == session_id
        ),
        None,
    )
    audio = tuple(
        DeckAudioView(
            slot=slot,  # type: ignore[arg-type]
            url=audio_url(
                delivery.id,
                slot,
                prepared.output_audio_by_input_key[input_key],
            ),
        )
        for slot, input_key in delivery.slot_assignment.items()
    )
    if project_session is None:
        label = None
        question = "どちらを残しますか?"
    elif plan is not None:
        label = "目的"
        question = "今の目的なら、どちらを残しますか?"
    else:
        label = "今回の確認"
        question = "この焦点では、どちらを残しますか?"
    return ActiveDeckView(
        session_id=session_id,
        project_session_id=None if project_session is None else project_session.id,
        status=cast(Literal["active", "paused"], runtime.status),
        delivery_id=delivery.id,
        sequence_index=delivery.sequence_index,
        comparison_count=len(session.items),
        presentation=session.presentation,
        criterion_label=label,
        criterion_text=public.criterion,
        question=question,
        current_best_check=plan is not None,
        audio=audio,
        identity_by_slot=labeled_identity(state, public.identity_by_slot),
        can_reveal=project_session is None and session.presentation == "blind",
        ended=False,
    )


def session_completion(
    repository: WorkspaceRepository,
    session_id: str,
    *,
    audio_url: Callable[[str, str, str], str],
) -> SessionCompletionView:
    state = repository.state()
    session = state.compare.sessions.get(session_id)
    if session is None:
        raise ValueError("Session does not exist")
    runtime = state.compare.session_runtime[session_id]
    if runtime.status != "ended" or not (session.presentation == "open" or runtime.revealed):
        raise ValueError("Session is not available for completion view")
    deliveries = sorted(
        (item for item in state.compare.deliveries.values() if item.session_id == session_id),
        key=lambda item: item.sequence_index,
    )
    items: list[RelistenItemView] = []
    for delivery in deliveries:
        comparison = state.compare.comparisons[delivery.comparison_id]
        prepared = state.compare.prepared_pairs[comparison.prepared_pair_id]
        public = public_delivery(
            session,
            delivery,
            comparison,
            session_revealed=runtime.revealed,
            delivery_answered=state.compare.effective_judgment(delivery.id) is not None,
        )
        assert public.identity_by_slot is not None
        revealed_identity = labeled_identity(state, public.identity_by_slot)
        assert revealed_identity is not None
        judgment = state.compare.effective_judgment(delivery.id)
        items.append(
            RelistenItemView(
                delivery_id=delivery.id,
                sequence_index=delivery.sequence_index,
                audio=tuple(
                    DeckAudioView(
                        slot=slot,  # type: ignore[arg-type]
                        url=audio_url(
                            delivery.id,
                            slot,
                            prepared.output_audio_by_input_key[input_key],
                        ),
                    )
                    for slot, input_key in delivery.slot_assignment.items()
                ),
                identity_by_slot=revealed_identity,
                judgment=None
                if judgment is None
                else ResultJudgmentView(
                    preference=judgment.preference,
                    blockers={
                        slot: ResultBlockerView(
                            selected=blocker.selected,
                            note=blocker.note,
                        )
                        for slot, blocker in judgment.blockers.items()
                    },
                    comment=judgment.comment,
                ),
                skipped=delivery.session_item_id in runtime.skipped_item_ids,
            )
        )
    linked = _project_session_for_core(state, session_id)
    current_best_check = any(
        item.session_id == session_id for item in state.project.best_update_plans.values()
    )
    result = None if linked is None else session_result_from_state(state, linked.id)
    return SessionCompletionView(
        session_id=session_id,
        project_session_id=None if linked is None else linked.id,
        focus=None if linked is None else linked.focus,
        current_best_check=current_best_check,
        comparison_count=len(session.items),
        items=tuple(items),
        result=result,
    )
