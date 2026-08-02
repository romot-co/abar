"""Sealed, bounded application queries."""

from collections.abc import Mapping
from dataclasses import asdict
from typing import Literal, cast

from abar.app.dashboard_queries import indicator_summaries, session_cards
from abar.app.query_support import timeline_entry, variant_label
from abar.app.repository import WorkspaceRepository
from abar.app.session_queries import current_best_evidence, session_result_from_state
from abar.app.state import ABARState
from abar.app.views import (
    BriefHistoryView,
    ClipSnapshotView,
    CriterionSnapshotView,
    EntityView,
    HistoryView,
    IndicatorValueSnapshotView,
    MaterialSnapshotView,
    ProjectSessionJudgmentView,
    ProjectSessionSnapshotView,
    ProjectView,
    ResolvedOperandSnapshotView,
    ResultBlockerView,
    TelemetryView,
)


def project_view(repository: WorkspaceRepository, *, since: int = 0) -> ProjectView:
    state = repository.state()
    project = state.project.project
    if project is None:
        raise ValueError("Project does not exist")
    all_events = repository.events.read_all()
    events = tuple(item for item in all_events if item.event_seq > since)[:1000]
    return ProjectView(
        project_id=project.id,
        name=project.name,
        brief=project.brief_text,
        brief_revision=project.brief_revision,
        brief_history=tuple(
            BriefHistoryView(
                revision=item.revision,
                text=item.text,
                human_quote=item.human_quote,
                event_seq=item.event_seq,
            )
            for item in state.project.brief_history
        ),
        current_best=variant_label(state, project.current_best_variant_id),
        current_best_evidence=current_best_evidence(state),
        previous_best=None
        if state.project.previous_best() is None
        else variant_label(state, state.project.previous_best() or "source"),
        in_use=None
        if project.in_use_variant_id is None
        else variant_label(state, project.in_use_variant_id),
        primary_recipe=f"{project.primary_recipe.id}-v{project.primary_recipe.version}",
        sessions=session_cards(state, all_events),
        indicators=indicator_summaries(state, project.current_best_variant_id),
        note_markdown=state.research.notes[-1].markdown if state.research.notes else None,
        materials=tuple(
            MaterialSnapshotView(
                id=item.id,
                name=item.name,
                source_group=item.source_group,
                clips=tuple(
                    ClipSnapshotView(
                        id=clip.id,
                        start_seconds=clip.start_frame
                        / state.compare.audio[item.source_audio_id].sample_rate,
                        duration_seconds=clip.frames
                        / state.compare.audio[item.source_audio_id].sample_rate,
                        role=clip.role,
                    )
                    for clip_id in item.clip_ids
                    if (clip := state.compare.clips.get(clip_id)) is not None
                ),
            )
            for item in state.compare.materials.values()
            if item.id in project.material_ids
        ),
        session_details=_project_session_documents(state),
        indicator_values=tuple(
            IndicatorValueSnapshotView(
                indicator_id=indicator_id,
                subject_id=subject_id,
                variant_id=value.variant_id,
                value=value.value,
                guard_result=value.guard_result,
                producer=value.producer,
                artifact_id=value.artifact_id,
                event_seq=value.event_seq,
            )
            for (
                indicator_id,
                subject_id,
                _variant_id,
            ), values in state.research.indicator_values.items()
            for value in values
        ),
        timeline=tuple(timeline_entry(event.event_seq, event.event_type) for event in events),
    )


def history(repository: WorkspaceRepository, *, since: int = 0) -> HistoryView:
    events = repository.events.read_all(since=since, limit=101)
    visible = events[:100]
    return HistoryView(
        entries=tuple(timeline_entry(item.event_seq, item.event_type) for item in visible),
        next_cursor=visible[-1].event_seq if len(events) > 100 else None,
    )


def entity(repository: WorkspaceRepository, entity_id: str) -> EntityView:
    state = repository.state()
    registries: tuple[tuple[str, Mapping[str, object]], ...] = (
        ("audio", state.compare.audio),
        ("material", state.compare.materials),
        ("clip", state.compare.clips),
        ("variant", state.compare.variants),
        ("prepared_pair", state.compare.prepared_pairs),
        ("comparison", state.compare.comparisons),
        ("session", state.compare.sessions),
        ("delivery", state.compare.deliveries),
        ("project_session", state.research.project_sessions),
        ("indicator", state.research.indicators),
        ("best_update_plan", state.project.best_update_plans),
        ("simplification_plan", state.project.simplification_plans),
    )
    for kind, registry in registries:
        value = registry.get(entity_id)
        if value is not None:
            document = cast(dict[str, object], asdict(value))  # type: ignore[arg-type]
            return EntityView(entity_id=entity_id, kind=kind, document=document)
    raise ValueError("entity does not exist")


def _project_session_documents(state: ABARState) -> tuple[ProjectSessionSnapshotView, ...]:
    output: list[ProjectSessionSnapshotView] = []
    for project_session in state.research.project_sessions.values():
        session = state.compare.sessions[project_session.core_session_id]
        runtime = state.compare.session_runtime[session.id]
        revealed = session.presentation == "open" or runtime.revealed
        deliveries = sorted(
            (item for item in state.compare.deliveries.values() if item.session_id == session.id),
            key=lambda item: item.sequence_index,
        )
        judgments: list[ProjectSessionJudgmentView] = []
        for delivery in deliveries:
            judgment = state.compare.effective_judgment(delivery.id)
            if judgment is None:
                continue
            identity_by_slot: dict[Literal["A", "B"], ResolvedOperandSnapshotView] | None = None
            if revealed:
                comparison = state.compare.comparisons[delivery.comparison_id]
                by_key = {item.input_key: item for item in comparison.pair}
                identity_by_slot = {
                    slot: ResolvedOperandSnapshotView(
                        input_key=by_key[input_key].input_key,
                        audio_id=by_key[input_key].audio_id,
                        provenance_ref=by_key[input_key].provenance_ref,
                    )
                    for slot, input_key in delivery.slot_assignment.items()
                }
            judgments.append(
                ProjectSessionJudgmentView(
                    delivery_id=delivery.id,
                    sequence_index=delivery.sequence_index,
                    preference=judgment.preference,
                    blockers={
                        slot: ResultBlockerView(
                            selected=blocker.selected,
                            note=blocker.note,
                        )
                        for slot, blocker in judgment.blockers.items()
                    },
                    comment=judgment.comment,
                    identity_visible_at_answer=judgment.identity_visible_at_answer,
                    telemetry=TelemetryView(
                        listen_ms=judgment.telemetry.listen_ms,
                        switches=judgment.telemetry.switches,
                        answer_ms=judgment.telemetry.answer_ms,
                    ),
                    identity_by_slot=identity_by_slot,
                )
            )
        result = (
            session_result_from_state(state, project_session.id)
            if runtime.status == "ended"
            else None
        )
        memos = state.research.session_memos.get(project_session.id, ())
        output.append(
            ProjectSessionSnapshotView(
                project_session_id=project_session.id,
                core_session_id=session.id,
                focus=project_session.focus,
                topic_key=project_session.topic_key,
                size=project_session.size,
                status=cast(
                    Literal["ready", "active", "paused", "ended", "closed", "blocked"],
                    runtime.status,
                ),
                criterion=None
                if session.criterion is None
                else CriterionSnapshotView(
                    text=session.criterion.text,
                    source=session.criterion.source,
                    source_event_seq=session.criterion.source_event_seq,
                ),
                judgments=tuple(judgments),
                result=result,
                memo=memos[-1].text if memos else None,
            )
        )
    return tuple(output)
