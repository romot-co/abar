"""Research Workflow data contracts."""

import math
import re
from dataclasses import dataclass
from typing import Literal

from abar.compare.models import RecipeRef, VariantRef

_INDICATOR_ID = re.compile(r"^ind_[a-z0-9][a-z0-9_-]*_v[1-9][0-9]*$")


@dataclass(frozen=True, slots=True)
class ProjectSession:
    id: str
    project_id: str
    core_session_id: str
    focus: str
    topic_key: str | None
    size: Literal["short", "standard"]
    pair: tuple[VariantRef, VariantRef]
    recipe: RecipeRef
    evidence_item_ids: tuple[str, ...]
    evidence_clip_ids: tuple[str, ...]
    selection_algorithm_id: str
    selection_algorithm_version: int
    selection_seed: int | None
    same_check_item_id: str | None
    repeat_check_item_id: str | None
    repeat_of_item_id: str | None
    created_by_type: Literal["agent", "human"]
    created_by_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.focus.strip() or len(self.focus) > 200 or "\n" in self.focus:
            raise ValueError("focus must be a non-empty single line of at most 200 code points")
        expected = 1 if self.size == "short" else 3
        if len(self.evidence_item_ids) != expected:
            raise ValueError("Project Session evidence count does not match size")
        if self.selection_algorithm_version < 1:
            raise ValueError("selection algorithm version must be positive")
        if self.selection_algorithm_id == "explicit" and self.selection_seed is not None:
            raise ValueError("explicit Clip selection does not use a seed")
        if self.selection_algorithm_id != "explicit" and self.selection_seed is None:
            raise ValueError("automatic Clip selection requires a seed")


@dataclass(frozen=True, slots=True)
class Indicator:
    id: str
    label: str
    description: str
    definition_ref: str
    definition_sha: str
    subject_kind: Literal["audio", "prepared_pair"]
    unit: str
    role: Literal["target", "guard", "none"]
    evidence_session_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _INDICATOR_ID.fullmatch(self.id) is None:
            raise ValueError("invalid Indicator ID")
        if (
            not self.label.strip()
            or not self.description.strip()
            or not self.definition_ref
            or not self.unit
        ):
            raise ValueError("Indicator label, description, definition, and unit are required")


@dataclass(frozen=True, slots=True)
class IndicatorValue:
    indicator_id: str
    subject_id: str
    variant_id: str
    value: float
    guard_result: Literal["pass", "fail"] | None
    producer: str
    artifact_id: str | None
    event_seq: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError("Indicator value must be finite")


@dataclass(frozen=True, slots=True)
class NoteRevision:
    project_id: str
    markdown: str
    content_sha: str
    actor_id: str
    event_seq: int


@dataclass(frozen=True, slots=True)
class SessionMemo:
    project_session_id: str
    text: str
    event_seq: int
