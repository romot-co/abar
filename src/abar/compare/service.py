"""Use-case-neutral orchestration inside Compare Core."""

from dataclasses import dataclass

from abar.compare.models import AudioObject, ComparisonPlan, PreparedPair, RecipeRef
from abar.compare.operands import OperandResolution, resolve_operand
from abar.compare.planning import comparison_plan
from abar.compare.projection import CompareState
from abar.compare.recipes import prepare
from abar.foundation.object_store import ObjectStore


@dataclass(frozen=True, slots=True)
class PreparedComparison:
    left: OperandResolution
    right: OperandResolution
    prepared_pair: PreparedPair
    output_audio: tuple[AudioObject, AudioObject]
    comparison: ComparisonPlan

    @property
    def byte_identical(self) -> bool:
        return self.prepared_pair.no_effect


def build_comparison(
    first: str,
    second: str,
    recipe: RecipeRef,
    *,
    state: CompareState,
    objects: ObjectStore,
    render_cache: dict[str, AudioObject] | None = None,
) -> PreparedComparison:
    """Resolve, prepare, and identify one comparison without writing events."""

    left = resolve_operand(
        first,
        input_key="p1",
        state=state,
        objects=objects,
        render_cache=render_cache,
    )
    right = resolve_operand(
        second,
        input_key="p2",
        state=state,
        objects=objects,
        render_cache=render_cache,
    )
    prepared = prepare(left.audio, right.audio, recipe, objects=objects)
    comparison = comparison_plan(left.operand, right.operand, prepared.pair, recipe)
    return PreparedComparison(
        left=left,
        right=right,
        prepared_pair=prepared.pair,
        output_audio=prepared.output_audio,
        comparison=comparison,
    )
