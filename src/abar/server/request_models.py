"""Strict HTTP request boundary models."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from abar.foundation.json_types import JSONValue
from abar.research.session_sizes import resolve_evidence_count


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QuickListenRequest(RequestModel):
    first: str
    second: str
    recipe: Literal["native", "aligned", "matched"] = "aligned"
    presentation: Literal["open", "blind"] = "open"


class ObservationSessionRequest(RequestModel):
    first_variant: str
    second_variant: str
    focus: Annotated[str, Field(min_length=1, max_length=200)]
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
    recipe: Literal["native", "aligned", "matched"] | None = None
    topic_key: str | None = None
    clip_ids: tuple[str, ...] = ()
    same_check: bool = False
    repeat_check: bool = False

    @model_validator(mode="after")
    def validate_evidence_count(self) -> "ObservationSessionRequest":
        resolve_evidence_count(self.size, self.evidence_count)
        return self


class BestUpdateSessionRequest(RequestModel):
    proposed_variant: str
    topic_key: str | None = None
    clip_ids: tuple[str, ...] = ()


class ClipRequest(RequestModel):
    start_seconds: Annotated[float, Field(ge=0)]
    duration_seconds: Annotated[float, Field(gt=0)]
    role: str | None = None


class SessionStartRequest(RequestModel):
    allocation_seed: Annotated[int | None, Field(ge=0)] = None


class BlockerRequest(RequestModel):
    selected: bool = False
    note: Annotated[str | None, Field(max_length=500)] = None


class TelemetryRequest(RequestModel):
    listen_ms: dict[Literal["a", "b"], Annotated[int, Field(ge=0)]]
    switches: Annotated[int, Field(ge=0)]
    answer_ms: Annotated[int, Field(ge=0)]


class JudgmentRequest(RequestModel):
    preference: Literal[1, 2, 3, 4, 5]
    blockers: dict[Literal["a", "b"], BlockerRequest]
    comment: Annotated[str | None, Field(max_length=500)] = None
    telemetry: TelemetryRequest


class SkipRequest(RequestModel):
    confirmed: bool = False


class BriefRequest(RequestModel):
    text: Annotated[str, Field(min_length=1, max_length=200)]
    human_quote: str


class ConfigRequest(RequestModel):
    recipe: Literal["native", "aligned", "matched"] | None = None
    ready_session_limit: Annotated[int | None, Field(gt=0)] = None


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
