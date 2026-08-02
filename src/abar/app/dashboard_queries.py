"""Sealed, bounded application queries."""

from collections.abc import Sequence
from typing import Literal, cast

from abar.app.query_support import variant_label
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
from abar.project.service import simplification_is_stale
from abar.research.models import ProjectSession


def status(repository: WorkspaceRepository, *, cursor: int = 0) -> StatusView:
    replay = repository.replay()
    if replay.degraded is not None:
        degraded = replay.degraded
        recovery = (
            "Preserve this Workspace unchanged and create a new Workspace. "
            "ABAR pre-release does not migrate unsupported events."
        )
        return StatusView(
            health=HealthView(
                status="degraded",
                reasons=(degraded.reason,),
                last_event_seq=degraded.event_seq,
                degradation=ReplayDegradationView(
                    event_seq=degraded.event_seq,
                    event_type=degraded.event_type,
                    schema_version=degraded.schema_version,
                    reason=degraded.reason,
                    recovery=recovery,
                ),
            ),
            project_name=None,
            brief=None,
            current_best=None,
            in_use=None,
            indicators=(),
            sessions=(),
            ready_count=0,
            active_count=0,
            ready_limit=None,
            material_count=0,
            pending_simplifications=(),
        )
    state = replay.state
    events = repository.events.read_all(since=cursor, limit=101)
    project = state.project.project
    sessions = session_cards(state, repository.events.read_all())
    return StatusView(
        health=HealthView(
            status="ok",
            reasons=(),
            last_event_seq=events[-1].event_seq if events else cursor,
            degradation=None,
        ),
        project_name=None if project is None else project.name,
        brief=None if project is None else project.brief_text,
        current_best=None
        if project is None
        else variant_label(state, project.current_best_variant_id),
        in_use=None
        if project is None or project.in_use_variant_id is None
        else variant_label(state, project.in_use_variant_id),
        indicators=indicator_summaries(
            state, None if project is None else project.current_best_variant_id
        ),
        sessions=sessions,
        ready_count=sum(item.status == "ready" for item in sessions),
        active_count=sum(item.status in {"active", "paused"} for item in sessions),
        ready_limit=None if project is None else project.ready_session_limit,
        material_count=len(state.compare.materials),
        pending_simplifications=tuple(
            SimplificationPromptView(
                id=plan.id,
                simple_variant_id=plan.simple_variant_id,
                reason=plan.reason,
                scope_clip_ids=plan.scope_clip_ids,
            )
            for plan in state.project.simplification_plans.values()
            if plan.id not in state.project.simplification_decisions
            and not simplification_is_stale(state.project, plan)
        ),
        next_cursor=events[99].event_seq if len(events) > 100 else None,
    )


def project_dashboard(repository: WorkspaceRepository) -> ProjectDashboardView:
    state = repository.state()
    project = state.project.project
    if project is None:
        raise ValueError("Project does not exist")
    return ProjectDashboardView(
        project_id=project.id,
        name=project.name,
        brief=project.brief_text,
        current_best=variant_label(state, project.current_best_variant_id),
        sessions=session_cards(state, repository.events.read_all()),
        indicators=indicator_summaries(state, project.current_best_variant_id),
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
        if runtime.status == "closed":
            status_value = "closed"
        elif runtime.status == "blocked":
            status_value = "blocked"
        elif runtime.status == "ended":
            status_value = "done"
        else:
            status_value = runtime.status
        completed_event = (
            None if runtime.ended_event_seq is None else event_by_seq.get(runtime.ended_event_seq)
        )
        output.append(
            SessionCardView(
                project_session_id=item.id,
                core_session_id=item.core_session_id,
                focus=item.focus,
                comparison_count=len(state.compare.sessions[item.core_session_id].items),
                answered_count=sum(
                    state.compare.effective_judgment(delivery_id) is not None
                    for delivery_id in runtime.deliveries
                ),
                status=cast(
                    Literal["ready", "active", "paused", "done", "closed", "blocked"],
                    status_value,
                ),
                current_best_check=item.core_session_id in plans,
                completed_at=None if completed_event is None else completed_event.ts.isoformat(),
                outcome=_session_outcome(state, item) if runtime.status == "ended" else None,
            )
        )
    return tuple(output)


def indicator_summaries(
    state: ABARState, current_best_variant_id: str | None
) -> tuple[IndicatorSummaryView, ...]:
    output: list[IndicatorSummaryView] = []
    for indicator in state.research.indicators.values():
        values = [
            value
            for (indicator_id, _, _variant_id), records in state.research.indicator_values.items()
            if indicator_id == indicator.id and records
            for value in records
            if value.variant_id == current_best_variant_id
        ]
        ordered = sorted(values, key=lambda item: item.event_seq, reverse=True)
        latest = ordered[0] if ordered else None
        output.append(
            IndicatorSummaryView(
                id=indicator.id,
                label=indicator.label,
                description=indicator.description,
                role=indicator.role,
                unit=indicator.unit,
                latest_value=None if latest is None else latest.value,
                guard_result=None if latest is None else latest.guard_result,
            )
        )
    return tuple(output)


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
    if result.favored_variant_id is None:
        outcome = "互角"
    else:
        outcome = f"{variant_label(state, result.favored_variant_id)} 優勢"
    if any(result.blockers_by_variant.values()):
        outcome += " · blocker"
    return outcome
