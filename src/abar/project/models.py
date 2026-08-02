"""Project Authority data contracts."""

from dataclasses import dataclass

from abar.compare.models import RecipeRef, VariantRef


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    brief_text: str
    brief_revision: int
    material_ids: tuple[str, ...]
    primary_recipe: RecipeRef
    current_best_variant_id: VariantRef
    in_use_variant_id: VariantRef | None
    ready_session_limit: int = 12

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Project name is required")
        if not self.brief_text.strip() or len(self.brief_text) > 200:
            raise ValueError("brief must contain 1 to 200 code points")
        if self.ready_session_limit < 1:
            raise ValueError("ready Session limit must be positive")


@dataclass(frozen=True, slots=True)
class BestUpdatePlan:
    id: str
    project_id: str
    session_id: str
    incumbent_variant_id: VariantRef
    proposed_variant_id: VariantRef
    evidence_item_ids: tuple[str, str, str]
    brief_revision: int
    brief_text: str
    recipe_snapshot: RecipeRef
    created_event_seq: int

    def __post_init__(self) -> None:
        if len(set(self.evidence_item_ids)) != 3:
            raise ValueError("Best Update Plan requires three distinct evidence items")
        if self.incumbent_variant_id == self.proposed_variant_id:
            raise ValueError("Best Update Plan variants must differ")


@dataclass(frozen=True, slots=True)
class SimplificationPlan:
    id: str
    project_id: str
    incumbent_variant_id: VariantRef
    simple_variant_id: VariantRef
    reason: str
    scope_clip_ids: tuple[str, ...]
    recipe_snapshot: RecipeRef
    created_event_seq: int

    def __post_init__(self) -> None:
        if not self.scope_clip_ids:
            raise ValueError("Simplification scope must not be empty")
        if not self.reason.strip():
            raise ValueError("Simplification reason is required")
        if self.incumbent_variant_id == self.simple_variant_id:
            raise ValueError("Simplification variants must differ")


@dataclass(frozen=True, slots=True)
class CurrentAuthoritySnapshot:
    current_best: VariantRef
    last_current_best_change_seq: int
    brief_revision: int
    last_brief_change_seq: int
    primary_recipe: RecipeRef
    last_primary_recipe_change_seq: int


@dataclass(frozen=True, slots=True)
class BestEvidence:
    item_id: str
    score_for_proposed: int | None
    proposed_blocked: bool
    identity_visible_at_answer: bool | None

    def __post_init__(self) -> None:
        if self.score_for_proposed not in (-2, -1, 0, 1, 2, None):
            raise ValueError("evidence score must be between -2 and 2")


@dataclass(frozen=True, slots=True)
class BestUpdateDecision:
    update: bool
    reason: str
    score_sum: int
    positive_count: int
