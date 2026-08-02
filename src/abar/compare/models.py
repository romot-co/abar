"""Pure data contracts for Compare Core."""

from dataclasses import dataclass, field
from typing import Literal

from abar.foundation.json_types import JSONValue

type Presentation = Literal["open", "blind"]
type VariantRef = str


@dataclass(frozen=True, slots=True)
class RecipeRef:
    id: Literal["native", "aligned", "matched"] = "aligned"
    version: Literal[1] = 1
    config: dict[str, JSONValue] = field(default_factory=dict[str, JSONValue])


@dataclass(frozen=True, slots=True)
class AudioObject:
    id: str
    object_id: str
    pcm_sha: str
    sample_rate: int
    channel_layout: Literal["mono", "stereo"]
    frames: int

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.frames <= 0:
            raise ValueError("audio sample rate and frame count must be positive")


@dataclass(frozen=True, slots=True)
class Clip:
    id: str
    material_id: str
    start_frame: int
    frames: int
    role: str | None = None
    selector_id: str | None = None
    selector_version: int | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        if self.start_frame < 0 or self.frames <= 0:
            raise ValueError("clip range is invalid")


@dataclass(frozen=True, slots=True)
class Material:
    id: str
    name: str
    source_audio_id: str
    source_group: str | None = None
    clip_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Variant:
    id: str
    label: str | None
    manifest_id: str
    resolved_params: dict[str, JSONValue]
    render_contract: Literal["renderable", "finite_rendered"]


@dataclass(frozen=True, slots=True)
class ResolvedOperand:
    input_key: Literal["p1", "p2"]
    audio_id: str
    provenance_ref: dict[str, JSONValue]


@dataclass(frozen=True, slots=True)
class PreparedPair:
    id: str
    input_audio_ids: tuple[str, str]
    recipe: RecipeRef
    output_audio_by_input_key: dict[Literal["p1", "p2"], str]
    features: dict[str, JSONValue]
    warnings: tuple[str, ...]
    no_effect: bool


@dataclass(frozen=True, slots=True)
class ComparisonPlan:
    id: str
    pair: tuple[ResolvedOperand, ResolvedOperand]
    recipe: RecipeRef
    prepared_pair_id: str


@dataclass(frozen=True, slots=True)
class SessionItem:
    id: str
    comparison_id: str
    sequence_index: int


@dataclass(frozen=True, slots=True)
class CriterionSnapshot:
    text: str
    source: Literal["focus", "project_brief"] | None
    source_event_seq: int | None


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    items: tuple[SessionItem, ...]
    presentation: Presentation
    reveal_policy: Literal["immediate", "after_answer_or_manual", "on_end"]
    criterion: CriterionSnapshot | None


@dataclass(frozen=True, slots=True)
class Delivery:
    id: str
    session_id: str
    session_item_id: str
    comparison_id: str
    slot_assignment: dict[Literal["A", "B"], Literal["p1", "p2"]]
    presentation: Presentation
    sequence_index: int


@dataclass(frozen=True, slots=True)
class BlockerInput:
    selected: bool = False
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.selected and self.note is not None:
            raise ValueError("unselected blocker note must be null")
        if self.note is not None and len(self.note) > 500:
            raise ValueError("blocker note exceeds 500 code points")


@dataclass(frozen=True, slots=True)
class Telemetry:
    listen_ms: dict[Literal["a", "b"], int]
    switches: int
    answer_ms: int

    def __post_init__(self) -> None:
        if min((*self.listen_ms.values(), self.switches, self.answer_ms)) < 0:
            raise ValueError("telemetry values must be non-negative")


@dataclass(frozen=True, slots=True)
class Judgment:
    id: str
    delivery_id: str
    preference: Literal[1, 2, 3, 4, 5]
    blockers: dict[Literal["a", "b"], BlockerInput]
    comment: str | None
    identity_visible_at_answer: bool
    telemetry: Telemetry

    def __post_init__(self) -> None:
        if self.comment is not None and len(self.comment) > 500:
            raise ValueError("comparison memo exceeds 500 code points")
