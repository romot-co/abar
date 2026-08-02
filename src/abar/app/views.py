"""Strict public API views."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from abar.foundation.json_types import JSONValue


class PublicView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ReplayDegradationView(PublicView):
    event_seq: int
    event_type: str
    schema_version: int
    reason: str
    recovery: str


class HealthView(PublicView):
    status: Literal["ok", "degraded"]
    reasons: tuple[str, ...] = ()
    last_event_seq: int = 0
    degradation: ReplayDegradationView | None = None


class WorkspaceSummaryView(PublicView):
    id: str
    name: str


class WorkspaceCatalogView(PublicView):
    schema_version: Literal[2] = 2
    selected_id: str
    workspaces: tuple[WorkspaceSummaryView, ...]


class IndicatorSummaryView(PublicView):
    id: str
    label: str
    description: str
    role: Literal["target", "guard", "none"]
    unit: str
    latest_value: float | None
    guard_result: Literal["pass", "fail"] | None


class SessionCardView(PublicView):
    project_session_id: str
    core_session_id: str
    focus: str
    comparison_count: int
    answered_count: int
    status: Literal["ready", "active", "paused", "done", "closed", "blocked"]
    current_best_check: bool
    completed_at: str | None
    outcome: str | None


class SimplificationPromptView(PublicView):
    id: str
    simple_variant_id: str
    reason: str
    scope_clip_ids: tuple[str, ...]


class StatusView(PublicView):
    schema_version: Literal[2] = 2
    health: HealthView
    project_name: str | None
    brief: str | None
    current_best: str | None
    in_use: str | None
    indicators: tuple[IndicatorSummaryView, ...]
    sessions: tuple[SessionCardView, ...]
    ready_count: int
    active_count: int
    ready_limit: int | None
    material_count: int
    pending_simplifications: tuple[SimplificationPromptView, ...]
    next_cursor: int | None = None


class BriefHistoryView(PublicView):
    revision: int
    text: str
    human_quote: str
    event_seq: int


class TimelineEntryView(PublicView):
    event_seq: int
    event_type: str
    summary: str


class BestUpdateEvidenceView(PublicView):
    proposed_variant_id: str
    favorable_count: int
    answered_count: int
    evidence_count: int
    score_sum: int
    blocker_count: int


class ClipSnapshotView(PublicView):
    id: str
    start_seconds: float
    duration_seconds: float
    role: str | None


class MaterialSnapshotView(PublicView):
    id: str
    name: str
    source_group: str | None
    clips: tuple[ClipSnapshotView, ...]


class IndicatorValueSnapshotView(PublicView):
    indicator_id: str
    subject_id: str
    variant_id: str
    value: float
    guard_result: Literal["pass", "fail"] | None
    producer: str
    artifact_id: str | None
    event_seq: int


class CriterionSnapshotView(PublicView):
    text: str
    source: Literal["focus", "project_brief"] | None
    source_event_seq: int | None


class TelemetryView(PublicView):
    listen_ms: dict[Literal["a", "b"], int]
    switches: int
    answer_ms: int


class ResolvedOperandSnapshotView(PublicView):
    input_key: Literal["p1", "p2"]
    audio_id: str
    provenance_ref: dict[str, JSONValue]


class RevealedIdentityView(PublicView):
    audio_id: str
    provenance: dict[str, JSONValue]
    label: str | None = None


class ProjectSessionJudgmentView(PublicView):
    delivery_id: str
    sequence_index: int
    preference: Literal[1, 2, 3, 4, 5]
    blockers: dict[Literal["a", "b"], "ResultBlockerView"]
    comment: str | None
    identity_visible_at_answer: bool
    telemetry: TelemetryView
    identity_by_slot: dict[Literal["A", "B"], ResolvedOperandSnapshotView] | None = None


class ProjectSessionSnapshotView(PublicView):
    project_session_id: str
    core_session_id: str
    focus: str
    topic_key: str | None
    size: Literal["short", "standard"]
    status: Literal["ready", "active", "paused", "ended", "closed", "blocked"]
    criterion: CriterionSnapshotView | None
    judgments: tuple[ProjectSessionJudgmentView, ...]
    result: "SessionResultView | None"
    memo: str | None


class ProjectDashboardView(PublicView):
    schema_version: Literal[2] = 2
    project_id: str
    name: str
    brief: str
    current_best: str
    sessions: tuple[SessionCardView, ...]
    indicators: tuple[IndicatorSummaryView, ...]


class ProjectView(PublicView):
    schema_version: Literal[2] = 2
    project_id: str
    name: str
    brief: str
    brief_revision: int
    brief_history: tuple[BriefHistoryView, ...]
    current_best: str
    current_best_evidence: BestUpdateEvidenceView | None
    previous_best: str | None
    in_use: str | None
    primary_recipe: str
    sessions: tuple[SessionCardView, ...]
    indicators: tuple[IndicatorSummaryView, ...]
    note_markdown: str | None
    materials: tuple[MaterialSnapshotView, ...]
    session_details: tuple[ProjectSessionSnapshotView, ...]
    indicator_values: tuple[IndicatorValueSnapshotView, ...]
    timeline: tuple[TimelineEntryView, ...]


class HistoryView(PublicView):
    schema_version: Literal[2] = 2
    entries: tuple[TimelineEntryView, ...]
    next_cursor: int | None


class EntityView(PublicView):
    schema_version: Literal[2] = 2
    entity_id: str
    kind: str
    document: dict[str, object]


class DeckAudioView(PublicView):
    slot: Literal["A", "B"]
    url: str


class ActiveDeckView(PublicView):
    schema_version: Literal[2] = 2
    session_id: str | None
    project_session_id: str | None
    status: Literal["active", "paused"] | None
    delivery_id: str | None
    sequence_index: int | None
    comparison_count: int
    presentation: Literal["open", "blind"] | None
    criterion_label: str | None
    criterion_text: str | None
    question: str | None
    current_best_check: bool
    audio: tuple[DeckAudioView, ...]
    identity_by_slot: dict[Literal["A", "B"], RevealedIdentityView] | None
    can_reveal: bool
    ended: bool


class EvidenceResultView(PublicView):
    item_id: str
    clip_id: str
    material_id: str
    material_name: str
    sequence_index: int | None
    preference: Literal[1, 2, 3, 4, 5] | None
    variant_by_slot: dict[Literal["A", "B"], str]
    variant_label_by_slot: dict[Literal["A", "B"], str]
    favored_variant_id: str | None
    favored_variant_label: str | None
    score_by_variant: dict[str, int]
    blockers_by_variant: dict[str, tuple[str, ...]]


class SessionResultView(PublicView):
    project_session_id: str
    evidence_count: int
    favored_required_count: int
    variant_labels: dict[str, str]
    evidence_direction_counts: dict[str, int]
    score_by_variant: dict[str, int]
    favored_variant_id: str | None
    favored_variant_label: str | None
    blockers_by_variant: dict[str, tuple[str, ...]]
    same_result: str
    repeat_result: str
    difference_profile: str
    current_best_updated: bool
    best_update_evidence: BestUpdateEvidenceView | None
    memo: str | None
    evidence: tuple[EvidenceResultView, ...]


class ResultBlockerView(PublicView):
    selected: bool
    note: str | None


class ResultJudgmentView(PublicView):
    preference: Literal[1, 2, 3, 4, 5]
    blockers: dict[Literal["a", "b"], ResultBlockerView]
    comment: str | None


class RelistenItemView(PublicView):
    delivery_id: str
    session_item_id: str
    sequence_index: int
    role: Literal["evidence", "same", "repeat", "other"]
    clip_id: str | None
    material_id: str | None
    material_name: str | None
    audio: tuple[DeckAudioView, ...]
    identity_by_slot: dict[Literal["A", "B"], RevealedIdentityView]
    judgment: ResultJudgmentView | None
    skipped: bool


class SessionCompletionView(PublicView):
    schema_version: Literal[2] = 2
    session_id: str
    project_session_id: str | None
    focus: str | None
    current_best_check: bool
    comparison_count: int
    items: tuple[RelistenItemView, ...]
    result: SessionResultView | None


class ActionView(PublicView):
    schema_version: Literal[2] = 2
    result: str
    id: str | None = None


class ErrorView(PublicView):
    code: str
    message: str


class ErrorEnvelope(PublicView):
    schema_version: Literal[2] = 2
    error: ErrorView


MemoText = Annotated[str, Field(max_length=500)]
