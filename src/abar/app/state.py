"""Aggregate v2 projection and event catalog."""

from dataclasses import dataclass, field, replace

from abar.compare.events import EVENT_SCHEMAS as COMPARE_SCHEMAS
from abar.compare.projection import CompareState, reduce_compare
from abar.foundation.events import EventEnvelope
from abar.project.events import EVENT_SCHEMAS as PROJECT_SCHEMAS
from abar.project.projection import ProjectState, reduce_project
from abar.research.events import EVENT_SCHEMAS as RESEARCH_SCHEMAS
from abar.research.projection import ResearchState, reduce_research


@dataclass(frozen=True, slots=True)
class ABARState:
    compare: CompareState = field(default_factory=CompareState)
    project: ProjectState = field(default_factory=ProjectState)
    research: ResearchState = field(default_factory=ResearchState)


EVENT_SCHEMAS = {
    **COMPARE_SCHEMAS,
    **PROJECT_SCHEMAS,
    **RESEARCH_SCHEMAS,
}


def reduce_state(state: ABARState, event: EventEnvelope) -> ABARState:
    if event.event_type in COMPARE_SCHEMAS:
        return replace(state, compare=reduce_compare(state.compare, event))
    if event.event_type in PROJECT_SCHEMAS:
        return replace(state, project=reduce_project(state.project, event))
    if event.event_type in RESEARCH_SCHEMAS:
        return replace(state, research=reduce_research(state.research, event))
    return state
