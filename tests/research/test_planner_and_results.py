from dataclasses import replace

import pytest

from abar.compare.models import (
    BlockerInput,
    ComparisonPlan,
    Delivery,
    Judgment,
    RecipeRef,
    ResolvedOperand,
    Telemetry,
)
from abar.research.models import ProjectSession
from abar.research.planner import PlannedRole, item_roles, presentation_order
from abar.research.results import calculate_result


def test_standard_repeat_is_separated_from_original() -> None:
    roles = item_roles("standard", same_check=False, repeat_check=True)
    assert roles[0].role == "evidence"
    assert roles[-1].role == "repeat"
    assert len(roles) == 4


def test_standard_plan_can_contain_ten_evidence_items_and_two_checks() -> None:
    roles = item_roles("standard", evidence_count=10, same_check=True, repeat_check=True)

    assert len(roles) == 12
    assert roles[0] == PlannedRole("evidence", 0)
    assert roles[1] == PlannedRole("same", 0)
    assert roles[-1] == PlannedRole("repeat", 0)
    assert [role.evidence_index for role in roles if role.role == "evidence"] == list(range(10))


def test_standard_evidence_count_has_no_product_maximum() -> None:
    roles = item_roles("standard", evidence_count=12)

    assert len(roles) == 12


def test_presentation_order_is_seeded_and_keeps_checks_unpredictable() -> None:
    evidence = tuple(f"item-{index}" for index in range(5))
    project_session = ProjectSession(
        "ps",
        "p",
        "ses",
        "focus",
        None,
        "standard",
        ("v1", "v2"),
        RecipeRef(),
        evidence,
        tuple(f"clip-{index}" for index in range(5)),
        "explicit",
        1,
        None,
        "same",
        "repeat",
        evidence[0],
        "agent",
        "agent-1",
        "fp",
    )

    first = presentation_order(project_session, seed=42)
    repeated = presentation_order(project_session, seed=42)

    assert repeated == first
    assert set(first) == {*evidence, "same", "repeat"}
    assert first[0] not in {"same", "repeat"}
    assert first.index("repeat") - first.index(evidence[0]) >= 3


def test_short_result_favors_non_tie_direction() -> None:
    project_session = ProjectSession(
        "ps",
        "p",
        "ses",
        "focus",
        None,
        "short",
        ("v1", "v2"),
        RecipeRef(),
        ("item",),
        ("clip",),
        "explicit",
        1,
        None,
        None,
        None,
        None,
        "agent",
        "agent-1",
        "fp",
    )
    with pytest.raises(ValueError, match="one Clip for each evidence item"):
        replace(project_session, evidence_clip_ids=())
    comparison = ComparisonPlan(
        "cmp",
        (
            ResolvedOperand("p1", "a1", {"variant_ref": "v1"}),
            ResolvedOperand("p2", "a2", {"variant_ref": "v2"}),
        ),
        RecipeRef(),
        "pp",
    )
    delivery = Delivery("d", "ses", "item", "cmp", {"A": "p2", "B": "p1"}, 0)
    judgment = Judgment(
        "j",
        "d",
        1,
        {"a": BlockerInput(), "b": BlockerInput()},
        None,
        False,
        Telemetry({"a": 0, "b": 0}, 0, 0),
    )
    result = calculate_result(
        project_session,
        comparisons={"cmp": comparison},
        deliveries_by_item={"item": delivery},
        judgments_by_delivery={"d": judgment},
    )
    assert result.favored_variant_id == "v2"


def test_ten_item_standard_result_requires_seven_directional_wins() -> None:
    def calculate(first_wins: int) -> str | None:
        item_ids = tuple(f"item-{index}" for index in range(10))
        project_session = ProjectSession(
            "ps",
            "p",
            "ses",
            "focus",
            None,
            "standard",
            ("v1", "v2"),
            RecipeRef(),
            item_ids,
            tuple(f"clip-{index}" for index in range(10)),
            "explicit",
            1,
            None,
            None,
            None,
            None,
            "agent",
            "agent-1",
            "fp",
        )
        comparisons: dict[str, ComparisonPlan] = {}
        deliveries: dict[str, Delivery] = {}
        judgments: dict[str, Judgment] = {}
        for index, item_id in enumerate(item_ids):
            comparison_id = f"cmp-{index}"
            delivery_id = f"delivery-{index}"
            comparisons[comparison_id] = ComparisonPlan(
                comparison_id,
                (
                    ResolvedOperand("p1", f"a1-{index}", {"variant_ref": "v1"}),
                    ResolvedOperand("p2", f"a2-{index}", {"variant_ref": "v2"}),
                ),
                RecipeRef(),
                f"pp-{index}",
            )
            deliveries[item_id] = Delivery(
                delivery_id,
                "ses",
                item_id,
                comparison_id,
                {"A": "p1", "B": "p2"},
                index,
            )
            judgments[delivery_id] = Judgment(
                f"judgment-{index}",
                delivery_id,
                1 if index < first_wins else 5,
                {"a": BlockerInput(), "b": BlockerInput()},
                None,
                False,
                Telemetry({"a": 0, "b": 0}, 0, 0),
            )
        return calculate_result(
            project_session,
            comparisons=comparisons,
            deliveries_by_item=deliveries,
            judgments_by_delivery=judgments,
        ).favored_variant_id

    assert calculate(6) is None
    assert calculate(7) == "v1"
