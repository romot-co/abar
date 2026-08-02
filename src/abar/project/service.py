"""Project Authority policies other than the isolated current-best rule."""

from abar.project.models import SimplificationPlan
from abar.project.projection import ProjectState


def simplification_is_stale(state: ProjectState, plan: SimplificationPlan) -> bool:
    project = state.project
    if project is None:
        return True
    changed_after_plan = max(state.last_best_change_seq, state.last_recipe_change_seq)
    return (
        changed_after_plan > plan.created_event_seq
        or project.current_best_variant_id != plan.incumbent_variant_id
        or project.primary_recipe != plan.recipe_snapshot
    )


def simplification_can_be_decided(state: ProjectState, plan_id: str) -> SimplificationPlan:
    plan = state.simplification_plans.get(plan_id)
    if plan is None:
        raise ValueError("unknown Simplification Plan")
    if plan_id in state.simplification_decisions:
        raise ValueError("Simplification Plan already decided")
    if simplification_is_stale(state, plan):
        raise ValueError("Simplification Plan is stale")
    return plan
