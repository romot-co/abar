"""Non-authoritative Session result projection."""

from dataclasses import dataclass
from typing import Literal

from abar.compare.models import ComparisonPlan, Delivery, Judgment
from abar.research.models import ProjectSession
from abar.research.session_sizes import favored_count


@dataclass(frozen=True, slots=True)
class ProjectSessionResult:
    evidence_direction_counts: dict[str, int]
    score_by_variant: dict[str, int]
    favored_variant_id: str | None
    blockers_by_variant: dict[str, tuple[str, ...]]
    same_result: Literal["tie", "difference_reported", "missing"]
    repeat_result: Literal["same_category", "same_direction", "near", "reversed", "missing"]
    difference_profile: Literal["clear", "mixed", "subtle"]


def calculate_result(
    project_session: ProjectSession,
    *,
    comparisons: dict[str, ComparisonPlan],
    deliveries_by_item: dict[str, Delivery],
    judgments_by_delivery: dict[str, Judgment],
) -> ProjectSessionResult:
    pair = project_session.pair
    counts: dict[str, int] = {pair[0]: 0, pair[1]: 0, "tie": 0}
    scores: dict[str, int] = {pair[0]: 0, pair[1]: 0}
    blockers: dict[str, list[str]] = {pair[0]: [], pair[1]: []}
    magnitudes: list[int] = []
    for item_id in project_session.evidence_item_ids:
        delivery = deliveries_by_item.get(item_id)
        judgment = judgments_by_delivery.get(delivery.id) if delivery is not None else None
        if delivery is None or judgment is None:
            continue
        comparison = comparisons[delivery.comparison_id]
        by_key = {entry.input_key: entry for entry in comparison.pair}
        variant_by_key = {
            key: str(entry.provenance_ref.get("variant_ref", "source"))
            for key, entry in by_key.items()
        }
        signed_for_a = 3 - judgment.preference
        variant_a = variant_by_key[delivery.slot_assignment["A"]]
        variant_b = variant_by_key[delivery.slot_assignment["B"]]
        if signed_for_a > 0:
            counts[variant_a] += 1
        elif signed_for_a < 0:
            counts[variant_b] += 1
        else:
            counts["tie"] += 1
        scores[variant_a] += signed_for_a
        scores[variant_b] -= signed_for_a
        magnitudes.append(signed_for_a if variant_a == pair[0] else -signed_for_a)
        for slot, variant in (("a", variant_a), ("b", variant_b)):
            blocker = judgment.blockers[slot]  # type: ignore[index]
            if blocker.selected:
                blockers[variant].append(blocker.note or "blocker")
    favored: str | None = None
    required = favored_count(len(project_session.evidence_item_ids))
    for variant in pair:
        if counts[variant] >= required and scores[variant] > 0:
            favored = variant
    same_result: Literal["tie", "difference_reported", "missing"] = "missing"
    if project_session.same_check_item_id is not None:
        delivery = deliveries_by_item.get(project_session.same_check_item_id)
        judgment = judgments_by_delivery.get(delivery.id) if delivery is not None else None
        if judgment is not None:
            same_result = "tie" if judgment.preference == 3 else "difference_reported"
    repeat_result = _repeat_result(
        project_session,
        deliveries_by_item=deliveries_by_item,
        judgments_by_delivery=judgments_by_delivery,
    )
    nonzero = [value for value in magnitudes if value]
    if (
        nonzero
        and len(nonzero) == len(magnitudes)
        and len({value > 0 for value in nonzero}) == 1
        and any(abs(value) == 2 for value in nonzero)
    ):
        profile: Literal["clear", "mixed", "subtle"] = "clear"
    elif any(value > 0 for value in nonzero) and any(value < 0 for value in nonzero):
        profile = "mixed"
    else:
        profile = "subtle"
    return ProjectSessionResult(
        evidence_direction_counts=counts,
        score_by_variant=scores,
        favored_variant_id=favored,
        blockers_by_variant={key: tuple(value) for key, value in blockers.items()},
        same_result=same_result,
        repeat_result=repeat_result,
        difference_profile=profile,
    )


def _repeat_result(
    project_session: ProjectSession,
    *,
    deliveries_by_item: dict[str, Delivery],
    judgments_by_delivery: dict[str, Judgment],
) -> Literal["same_category", "same_direction", "near", "reversed", "missing"]:
    repeated = project_session.repeat_check_item_id
    original = project_session.repeat_of_item_id
    if repeated is None or original is None:
        return "missing"
    first_delivery = deliveries_by_item.get(original)
    second_delivery = deliveries_by_item.get(repeated)
    if first_delivery is None or second_delivery is None:
        return "missing"
    first = judgments_by_delivery.get(first_delivery.id)
    second = judgments_by_delivery.get(second_delivery.id)
    if first is None or second is None:
        return "missing"

    def normalized(judgment: Judgment, delivery: Delivery) -> int:
        score_a = 3 - judgment.preference
        return score_a if delivery.slot_assignment["A"] == "p1" else -score_a

    left = normalized(first, first_delivery)
    right = normalized(second, second_delivery)
    if left == right:
        return "same_category"
    if left == 0 or right == 0:
        return "near"
    if (left > 0) == (right > 0):
        return "same_direction"
    return "reversed"
