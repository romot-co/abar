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
from abar.research.planner import item_roles
from abar.research.results import calculate_result


def test_standard_repeat_is_separated_from_original() -> None:
    roles = item_roles("standard", same_check=False, repeat_check=True)
    assert roles[0].role == "evidence"
    assert roles[-1].role == "repeat"
    assert len(roles) == 4


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
    comparison = ComparisonPlan(
        "cmp",
        (
            ResolvedOperand("p1", "a1", {"variant_ref": "v1"}),
            ResolvedOperand("p2", "a2", {"variant_ref": "v2"}),
        ),
        RecipeRef(),
        "pp",
    )
    delivery = Delivery("d", "ses", "item", "cmp", {"A": "p2", "B": "p1"}, "blind", 0)
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
