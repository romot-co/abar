"""Projection for the single Project in a Workspace."""

from dataclasses import dataclass, field, replace
from typing import Literal, cast

from abar.compare.models import RecipeRef
from abar.foundation.events import EventEnvelope
from abar.foundation.json_types import JSONValue
from abar.project.models import (
    BestUpdatePlan,
    CurrentAuthoritySnapshot,
    Project,
    SimplificationPlan,
)


@dataclass(frozen=True, slots=True)
class BestChange:
    event_seq: int
    from_variant_id: str
    to_variant_id: str
    basis: str
    basis_ref: str | None


@dataclass(frozen=True, slots=True)
class BriefRevision:
    event_seq: int
    revision: int
    text: str
    human_quote: str


@dataclass(frozen=True, slots=True)
class ProjectState:
    project: Project | None = None
    created_event_seq: int = 0
    last_brief_change_seq: int = 0
    last_recipe_change_seq: int = 0
    last_best_change_seq: int = 0
    brief_history: tuple[BriefRevision, ...] = ()
    best_history: tuple[BestChange, ...] = ()
    best_update_plans: dict[str, BestUpdatePlan] = field(default_factory=dict[str, BestUpdatePlan])
    simplification_plans: dict[str, SimplificationPlan] = field(
        default_factory=dict[str, SimplificationPlan]
    )
    simplification_decisions: dict[str, str] = field(default_factory=dict[str, str])

    def authority_snapshot(self) -> CurrentAuthoritySnapshot:
        if self.project is None:
            raise ValueError("Project does not exist")
        return CurrentAuthoritySnapshot(
            current_best=self.project.current_best_variant_id,
            last_current_best_change_seq=self.last_best_change_seq,
            brief_revision=self.project.brief_revision,
            last_brief_change_seq=self.last_brief_change_seq,
            primary_recipe=self.project.primary_recipe,
            last_primary_recipe_change_seq=self.last_recipe_change_seq,
        )

    def previous_best(self) -> str | None:
        return self.best_history[-1].from_variant_id if self.best_history else None


def reduce_project(state: ProjectState, event: EventEnvelope) -> ProjectState:
    p = event.payload
    if event.event_type == "project.created":
        if state.project is not None:
            raise ValueError("a Workspace may contain only one Project")
        recipe = _recipe(cast(dict[str, JSONValue], p["primary_recipe"]))
        project = Project(
            id=_str(p, "project_id"),
            name=_str(p, "name"),
            brief_text=_str(p, "brief"),
            brief_revision=1,
            material_ids=(),
            primary_recipe=recipe,
            current_best_variant_id=_str(p, "initial_current_best"),
            in_use_variant_id=None,
            ready_session_limit=_int(p, "ready_session_limit"),
        )
        initial = BriefRevision(event.event_seq, 1, project.brief_text, project.brief_text)
        return replace(
            state,
            project=project,
            created_event_seq=event.event_seq,
            last_brief_change_seq=event.event_seq,
            last_recipe_change_seq=event.event_seq,
            last_best_change_seq=event.event_seq,
            brief_history=(initial,),
        )
    if state.project is None:
        raise ValueError("Project event before project.created")
    project = state.project
    if event.event_type == "project.material.attached":
        material_id = _str(p, "material_id")
        if material_id in project.material_ids:
            return state
        return replace(
            state, project=replace(project, material_ids=(*project.material_ids, material_id))
        )
    if event.event_type == "project.brief.changed":
        revision = _int(p, "revision")
        if revision != project.brief_revision + 1:
            raise ValueError("brief revision must increase by one")
        text = _str(p, "text")
        quote = _str(p, "human_quote")
        item = BriefRevision(event.event_seq, revision, text, quote)
        return replace(
            state,
            project=replace(project, brief_text=text, brief_revision=revision),
            last_brief_change_seq=event.event_seq,
            brief_history=(*state.brief_history, item),
        )
    if event.event_type == "project.config.changed":
        recipe_payload = p.get("primary_recipe")
        ready_limit = p.get("ready_session_limit")
        updated = project
        last_recipe = state.last_recipe_change_seq
        if recipe_payload is not None:
            updated = replace(
                updated, primary_recipe=_recipe(cast(dict[str, JSONValue], recipe_payload))
            )
            last_recipe = event.event_seq
        if ready_limit is not None:
            updated = replace(updated, ready_session_limit=cast(int, ready_limit))
        return replace(state, project=updated, last_recipe_change_seq=last_recipe)
    if event.event_type == "best_update.planned":
        plan = BestUpdatePlan(
            id=_str(p, "plan_id"),
            project_id=_str(p, "project_id"),
            session_id=_str(p, "session_id"),
            incumbent_variant_id=_str(p, "incumbent_variant_id"),
            proposed_variant_id=_str(p, "proposed_variant_id"),
            evidence_item_ids=tuple(cast(list[str], p["evidence_item_ids"])),  # type: ignore[arg-type]
            brief_revision=_int(p, "brief_revision"),
            brief_text=_str(p, "brief_text"),
            recipe_snapshot=_recipe(cast(dict[str, JSONValue], p["recipe_snapshot"])),
            created_event_seq=event.event_seq,
        )
        return replace(state, best_update_plans={**state.best_update_plans, plan.id: plan})
    if event.event_type == "simplification.planned":
        plan = SimplificationPlan(
            id=_str(p, "plan_id"),
            project_id=_str(p, "project_id"),
            incumbent_variant_id=_str(p, "incumbent_variant_id"),
            simple_variant_id=_str(p, "simple_variant_id"),
            reason=_str(p, "reason"),
            scope_clip_ids=tuple(cast(list[str], p["scope_clip_ids"])),
            recipe_snapshot=_recipe(cast(dict[str, JSONValue], p["recipe_snapshot"])),
            created_event_seq=event.event_seq,
        )
        return replace(state, simplification_plans={**state.simplification_plans, plan.id: plan})
    if event.event_type == "simplification.decided":
        plan_id = _str(p, "plan_id")
        if plan_id not in state.simplification_plans:
            raise ValueError("unknown Simplification Plan")
        if plan_id in state.simplification_decisions:
            raise ValueError("Simplification Plan already decided")
        decision = _str(p, "decision")
        if decision not in {"accept", "keep"}:
            raise ValueError("invalid Simplification decision")
        return replace(
            state,
            simplification_decisions={
                **state.simplification_decisions,
                plan_id: decision,
            },
        )
    if event.event_type == "current_best.changed":
        previous = _str(p, "from_variant_id")
        if previous != project.current_best_variant_id:
            raise ValueError("current_best.changed from value does not match projection")
        basis = _str(p, "basis")
        if basis not in {"comparison", "simplification", "manual"}:
            raise ValueError("invalid current best change basis")
        target = _str(p, "to_variant_id")
        if target == previous:
            raise ValueError("current best change must change the value")
        basis_ref = cast(str | None, p.get("basis_ref"))
        ack = cast(str | None, p.get("ack"))
        if basis == "manual":
            if basis_ref is not None or ack is None or not ack.strip():
                raise ValueError("manual current best change requires only a non-empty ack")
        elif basis == "comparison":
            plan = state.best_update_plans.get(basis_ref or "")
            if (
                plan is None
                or plan.incumbent_variant_id != previous
                or plan.proposed_variant_id != target
            ):
                raise ValueError("comparison basis does not match Best Update Plan")
        else:
            plan = state.simplification_plans.get(basis_ref or "")
            if (
                plan is None
                or state.simplification_decisions.get(plan.id) != "accept"
                or plan.incumbent_variant_id != previous
                or plan.simple_variant_id != target
            ):
                raise ValueError("simplification basis does not match accepted Plan")
        change = BestChange(
            event_seq=event.event_seq,
            from_variant_id=previous,
            to_variant_id=target,
            basis=basis,
            basis_ref=basis_ref,
        )
        return replace(
            state,
            project=replace(project, current_best_variant_id=change.to_variant_id),
            last_best_change_seq=event.event_seq,
            best_history=(*state.best_history, change),
        )
    if event.event_type == "in_use.recorded":
        return replace(state, project=replace(project, in_use_variant_id=_str(p, "variant_id")))
    return state


def _recipe(payload: dict[str, JSONValue]) -> RecipeRef:
    return RecipeRef(
        id=cast(Literal["native", "aligned", "matched"], payload["id"]),
        version=cast(Literal[1], payload["version"]),
        config=cast(dict[str, JSONValue], payload.get("config", {})),
    )


def _str(payload: dict[str, JSONValue], key: str) -> str:
    return cast(str, payload[key])


def _int(payload: dict[str, JSONValue], key: str) -> int:
    return cast(int, payload[key])
