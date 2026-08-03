"""Sealed, bounded application queries."""

from collections.abc import Sequence
from statistics import median
from typing import Literal

from abar.app.query_support import public_session_status, recipe_label, variant_label
from abar.app.repository import WorkspaceRepository
from abar.app.session_queries import session_result_from_state
from abar.app.state import ABARState
from abar.app.views import (
    HealthView,
    IndicatorSummaryView,
    ProjectDashboardView,
    ReplayDegradationView,
    SessionCardView,
    SimplificationPromptView,
    StatusView,
)
from abar.foundation.events import EventEnvelope
from abar.foundation.replay import ReplayResult
from abar.project.service import simplification_is_stale
from abar.research.models import ProjectSession
from abar.research.session_sizes import favored_count


def status(repository: WorkspaceRepository) -> StatusView:
    replay = repository.replay()
    events = repository.events.read_all()
    health = _health_view(replay, events)
    if replay.degraded is not None:
        return StatusView(
            health=health,
            project_name=None,
            brief=None,
            current_best=None,
            in_use=None,
            ready_count=0,
            active_count=0,
            ready_limit=None,
            material_count=0,
        )
    state = replay.state
    project = state.project.project
    sessions = session_cards(state, repository.events.read_all())
    return StatusView(
        health=health,
        project_name=None if project is None else project.name,
        brief=None if project is None else project.brief_text,
        current_best=None
        if project is None
        else variant_label(state, project.current_best_variant_id),
        in_use=None
        if project is None or project.in_use_variant_id is None
        else variant_label(state, project.in_use_variant_id),
        ready_count=sum(item.status == "ready" for item in sessions),
        active_count=sum(item.status in {"active", "paused"} for item in sessions),
        ready_limit=None if project is None else project.ready_session_limit,
        material_count=0 if project is None else len(project.material_ids),
    )


def project_dashboard(repository: WorkspaceRepository) -> ProjectDashboardView:
    events = repository.events.read_all()
    replay = repository.replay()
    health = _health_view(replay, events)
    if replay.degraded is not None:
        return ProjectDashboardView(
            health=health,
            project_id=None,
            name=None,
            brief=None,
            current_best=None,
            primary_recipe=None,
            sessions=(),
            indicators=(),
            pending_simplifications=(),
        )
    state = replay.state
    project = state.project.project
    if project is None:
        return ProjectDashboardView(
            health=health,
            project_id=None,
            name=None,
            brief=None,
            current_best=None,
            primary_recipe=None,
            sessions=(),
            indicators=(),
            pending_simplifications=(),
        )
    return ProjectDashboardView(
        health=health,
        project_id=project.id,
        name=project.name,
        brief=project.brief_text,
        current_best=variant_label(state, project.current_best_variant_id),
        primary_recipe=recipe_label(project.primary_recipe),
        sessions=session_cards(state, events),
        indicators=indicator_summaries(state, project.current_best_variant_id),
        pending_simplifications=_pending_simplifications(state),
    )


def session_cards(
    state: ABARState,
    events: Sequence[EventEnvelope],
) -> tuple[SessionCardView, ...]:
    plans = {item.session_id for item in state.project.best_update_plans.values()}
    output: list[SessionCardView] = []
    event_by_seq = {item.event_seq: item for item in events}
    for item in state.research.project_sessions.values():
        runtime = state.compare.session_runtime[item.core_session_id]
        completed_event = (
            None if runtime.ended_event_seq is None else event_by_seq.get(runtime.ended_event_seq)
        )
        output.append(
            SessionCardView(
                project_session_id=item.id,
                focus=item.focus,
                recipe=recipe_label(item.recipe),
                comparison_count=len(state.compare.sessions[item.core_session_id].items),
                answered_count=sum(
                    state.compare.effective_judgment(delivery_id) is not None
                    for delivery_id in runtime.deliveries
                ),
                status=public_session_status(runtime.status),
                current_best_check=item.core_session_id in plans,
                completed_at=None if completed_event is None else completed_event.ts.isoformat(),
                outcome=(
                    _session_outcome(state, item)
                    if runtime.status == "ended"
                    else runtime.outcome
                    if runtime.status == "blocked"
                    else None
                ),
            )
        )
    return tuple(output)


def indicator_summaries(
    state: ABARState, current_best_variant_id: str | None
) -> tuple[IndicatorSummaryView, ...]:
    output: list[IndicatorSummaryView] = []
    for indicator in state.research.indicators.values():
        latest_by_subject = [
            records[-1]
            for (indicator_id, _, _variant_id), records in state.research.indicator_values.items()
            if indicator_id == indicator.id
            and records
            and records[-1].variant_id == current_best_variant_id
        ]
        value = (
            None
            if not latest_by_subject
            else float(median(item.value for item in latest_by_subject))
        )
        guard_result: Literal["pass", "fail"] | None = None
        if indicator.role == "guard" and latest_by_subject:
            results = [item.guard_result for item in latest_by_subject]
            if "fail" in results:
                guard_result = "fail"
            elif all(result == "pass" for result in results):
                guard_result = "pass"
        output.append(
            IndicatorSummaryView(
                id=indicator.id,
                label=indicator.label,
                description=indicator.description,
                role=indicator.role,
                unit=indicator.unit,
                value=value,
                guard_result=guard_result,
            )
        )
    return tuple(output)


def _health_view(replay: ReplayResult[ABARState], events: Sequence[EventEnvelope]) -> HealthView:
    last_event_seq = events[-1].event_seq if events else 0
    degraded = replay.degraded
    if degraded is None:
        return HealthView(status="ok", reasons=(), last_event_seq=last_event_seq)
    recovery = (
        "Preserve this Workspace unchanged and create a new Workspace. "
        "ABAR pre-release does not migrate unsupported events."
    )
    return HealthView(
        status="degraded",
        reasons=(degraded.reason,),
        last_event_seq=last_event_seq,
        degradation=ReplayDegradationView(
            event_seq=degraded.event_seq,
            event_type=degraded.event_type,
            schema_version=degraded.schema_version,
            reason=degraded.reason,
            recovery=recovery,
        ),
    )


def _pending_simplifications(state: ABARState) -> tuple[SimplificationPromptView, ...]:
    return tuple(
        SimplificationPromptView(
            id=plan.id,
            simple_variant_id=plan.simple_variant_id,
            reason=plan.reason,
            scope_clip_ids=plan.scope_clip_ids,
        )
        for plan in state.project.simplification_plans.values()
        if plan.id not in state.project.simplification_decisions
        and not simplification_is_stale(state.project, plan)
    )


def _session_outcome(state: ABARState, project_session: ProjectSession) -> str:
    result = session_result_from_state(state, project_session.id)
    plan = next(
        (
            item
            for item in state.project.best_update_plans.values()
            if item.session_id == project_session.core_session_id
        ),
        None,
    )
    if plan is not None:
        if result.current_best_updated:
            return f"{variant_label(state, plan.proposed_variant_id)} に更新"
        return "現在最良を維持"
    if result.favored_variant_id is not None:
        outcome = f"{variant_label(state, result.favored_variant_id)} 優勢"
    elif result.evidence_direction_counts["tie"] == len(project_session.evidence_item_ids):
        outcome = "全比較で互角"
    else:
        first, second = project_session.pair
        counts = result.evidence_direction_counts
        parts = [
            f"{variant_label(state, first)} {counts[first]}",
            f"{variant_label(state, second)} {counts[second]}",
            f"互角 {counts['tie']}",
        ]
        evidence_count = len(project_session.evidence_item_ids)
        missing = evidence_count - sum(counts.values())
        if missing:
            parts.append(f"未回答 {missing}")
        required = favored_count(evidence_count)
        outcome = f"{' / '.join(parts)}（{required}件の優勢条件に未達）"  # noqa: RUF001
    if any(result.blockers_by_variant.values()):
        outcome += " · blocker"
    return outcome
