from abar.compare.models import RecipeRef
from abar.project.models import Project, SimplificationPlan
from abar.project.projection import ProjectState
from abar.project.service import simplification_is_stale


def test_simplification_stale_is_monotonic_by_change_sequence() -> None:
    project = Project("p", "name", "brief", 1, (), RecipeRef("matched"), "v_old", None)
    plan = SimplificationPlan(
        "s", "p", "v_old", "v_simple", "reason", ("c",), RecipeRef("matched"), 10
    )
    state = ProjectState(project=project, last_best_change_seq=11, simplification_plans={"s": plan})
    assert simplification_is_stale(state, plan)
