"""Strict HTTP request boundary models."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from abar.compare.models import VariantKind
from abar.foundation.json_types import JSONValue
from abar.research.session_sizes import resolve_evidence_count


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QuickListenRequest(RequestModel):
    first: str
    second: str
    recipe: Literal["native", "aligned", "matched", "matched-v2", "level-matched"] = "aligned"
    presentation: Literal["open", "blind"] = "open"


class ObservationSessionRequest(RequestModel):
    first_variant: str
    second_variant: str
    focus: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    symptom_id: str | None = None
    size: Literal["short", "standard"] = "short"
    evidence_count: (
        Annotated[
            int,
            Field(
                ge=1,
                description=(
                    "Omit for the size default; short accepts 1 and standard accepts 3 or more"
                ),
            ),
        ]
        | None
    ) = None
    recipe: Literal["native", "aligned", "matched", "matched-v2", "level-matched"] | None = None
    topic_key: str | None = None
    clip_ids: list[str] = Field(default_factory=list[str])
    same_check: bool = False
    repeat_check: bool = False

    @model_validator(mode="after")
    def validate_evidence_count(self) -> "ObservationSessionRequest":
        resolve_evidence_count(self.size, self.evidence_count)
        return self


class BestUpdateSessionRequest(RequestModel):
    proposed_variant: str
    topic_key: str | None = None
    clip_ids: list[str] = Field(default_factory=list[str])


class ClipRequest(RequestModel):
    start_seconds: Annotated[float, Field(ge=0)]
    duration_seconds: Annotated[float, Field(gt=0)]
    role: str | None = None


class SessionStartRequest(RequestModel):
    allocation_seed: Annotated[int | None, Field(ge=0)] = None


class TimeRangeRequest(RequestModel):
    start_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    end_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def validate_range(self) -> "TimeRangeRequest":
        if self.start_seconds >= self.end_seconds:
            raise ValueError("range must satisfy start < end")
        return self


class LoopTelemetryRequest(RequestModel):
    range: TimeRangeRequest
    listen_ms: dict[Literal["a", "b"], Annotated[int, Field(ge=0)]]

    @model_validator(mode="after")
    def validate_slots(self) -> "LoopTelemetryRequest":
        if set(self.listen_ms) != {"a", "b"}:
            raise ValueError("both A/B listening times are required")
        return self


class BlockerRequest(RequestModel):
    selected: bool = False
    note: Annotated[str | None, Field(max_length=500)] = None
    range: TimeRangeRequest | None = None

    @model_validator(mode="after")
    def validate_selected(self) -> "BlockerRequest":
        if not self.selected and (self.note is not None or self.range is not None):
            raise ValueError("unselected blocker must have no note or range")
        return self


class TelemetryRequest(RequestModel):
    listen_ms: dict[Literal["a", "b"], Annotated[int, Field(ge=0)]]
    switches: Annotated[int, Field(ge=0)]
    answer_ms: Annotated[int, Field(ge=0)]
    loops: list[LoopTelemetryRequest] = Field(default_factory=list[LoopTelemetryRequest])

    @model_validator(mode="after")
    def validate_slots(self) -> "TelemetryRequest":
        if set(self.listen_ms) != {"a", "b"}:
            raise ValueError("both A/B listening times are required")
        return self


class JudgmentRequest(RequestModel):
    preference: Literal[1, 2, 3, 4, 5] | None = None
    held: bool = False
    comment_range: TimeRangeRequest | None = None
    blockers: dict[Literal["a", "b"], BlockerRequest]
    comment: Annotated[str | None, Field(max_length=500)] = None
    telemetry: TelemetryRequest

    @model_validator(mode="after")
    def validate_answer(self) -> "JudgmentRequest":
        if self.held == (self.preference is not None):
            raise ValueError("choose either preference or held")
        if set(self.blockers) != {"a", "b"}:
            raise ValueError("both A/B blockers are required")
        if self.comment_range is not None and not self.comment:
            raise ValueError("comment range requires a memo")
        return self


class SkipRequest(RequestModel):
    confirmed: bool = False


class BriefRequest(RequestModel):
    # The Project keeps the stripped text, so bound it after stripping.
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    human_quote: str


class ConfigRequest(RequestModel):
    recipe: Literal["native", "aligned", "matched", "matched-v2", "level-matched"] | None = None
    ready_session_limit: Annotated[int | None, Field(gt=0)] = None
    prescreen_indicator_id: str | None = None
    clear_prescreen_indicator: bool = False


class ManualBestRequest(RequestModel):
    variant_id: str
    ack: Annotated[str, Field(min_length=1)]


class ProjectExportRequest(RequestModel):
    variant_id: str
    output: str
    render_clips: str | None = None


class SimplificationRequest(RequestModel):
    simple_variant_id: str
    reason: Annotated[str, Field(min_length=1)]
    scope_clip_ids: Annotated[tuple[str, ...], Field(min_length=1)]


class SimplificationDecisionRequest(RequestModel):
    decision: Literal["accept", "keep"]


class VariantRequest(RequestModel):
    manifest: dict[str, JSONValue]
    params: dict[str, JSONValue] = Field(default_factory=dict[str, JSONValue])
    label: str | None = None
    kind: VariantKind = "candidate"
    provenance: dict[str, JSONValue] | None = None


class VariantMaterializationRequest(RequestModel):
    clip_ids: Annotated[list[str], Field(min_length=1)]
    output: str


class NoteRequest(RequestModel):
    markdown: str


class IndicatorRequest(RequestModel):
    indicator_id: str
    label: str
    description: str
    definition_path: str
    subject_kind: Literal["audio", "prepared_pair"]
    unit: str
    role: Literal["target", "guard", "none"] = "none"


class IndicatorUpdateRequest(RequestModel):
    role: Literal["target", "guard", "none"] | None = None
    evidence_session_ids: tuple[str, ...] | None = None


class IndicatorValueRequest(RequestModel):
    indicator_id: str
    subject_id: str
    variant_id: str
    value: float
    guard_result: Literal["pass", "fail"] | None = None
