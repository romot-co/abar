"""Projection for Sessions, Indicator ledger, Note, and memo."""

from dataclasses import dataclass, field, replace
from typing import Literal, cast

from abar.compare.models import RecipeRef
from abar.foundation.events import EventEnvelope
from abar.foundation.json_types import JSONValue
from abar.research.models import (
    Indicator,
    IndicatorValue,
    NoteRevision,
    ProjectSession,
)


@dataclass(frozen=True, slots=True)
class ResearchState:
    project_sessions: dict[str, ProjectSession] = field(default_factory=dict[str, ProjectSession])
    indicators: dict[str, Indicator] = field(default_factory=dict[str, Indicator])
    indicator_values: dict[tuple[str, str, str], tuple[IndicatorValue, ...]] = field(
        default_factory=dict[tuple[str, str, str], tuple[IndicatorValue, ...]]
    )
    notes: tuple[NoteRevision, ...] = ()


def reduce_research(state: ResearchState, event: EventEnvelope) -> ResearchState:
    p = event.payload
    if event.event_type == "project_session.created":
        project_session = ProjectSession(
            id=_str(p, "project_session_id"),
            project_id=_str(p, "project_id"),
            core_session_id=_str(p, "core_session_id"),
            focus=_str(p, "focus"),
            topic_key=cast(str | None, p.get("topic_key")),
            size=cast(Literal["short", "standard"], p["size"]),
            pair=tuple(cast(list[str], p["pair"])),  # type: ignore[arg-type]
            recipe=_recipe(cast(dict[str, JSONValue], p["recipe"])),
            evidence_item_ids=tuple(cast(list[str], p["evidence_item_ids"])),
            evidence_clip_ids=tuple(cast(list[str], p["evidence_clip_ids"])),
            selection_algorithm_id=_str(p, "selection_algorithm_id"),
            selection_algorithm_version=_int(p, "selection_algorithm_version"),
            selection_seed=cast(int | None, p.get("selection_seed")),
            same_check_item_id=cast(str | None, p.get("same_check_item_id")),
            repeat_check_item_id=cast(str | None, p.get("repeat_check_item_id")),
            repeat_of_item_id=cast(str | None, p.get("repeat_of_item_id")),
            created_by_type=cast(Literal["agent", "human"], p["created_by_type"]),
            created_by_id=_str(p, "created_by_id"),
            fingerprint=_str(p, "fingerprint"),
        )
        return replace(
            state,
            project_sessions={**state.project_sessions, project_session.id: project_session},
        )
    if event.event_type == "indicator.registered":
        indicator = Indicator(
            id=_str(p, "indicator_id"),
            label=_str(p, "label"),
            description=_str(p, "description"),
            definition_ref=_str(p, "definition_ref"),
            definition_sha=_str(p, "definition_sha"),
            subject_kind=cast(Literal["audio", "prepared_pair"], p["subject_kind"]),
            unit=_str(p, "unit"),
            role=cast(Literal["target", "guard", "none"], p["role"]),
            evidence_session_ids=tuple(cast(list[str], p.get("evidence_session_ids", []))),
        )
        existing = state.indicators.get(indicator.id)
        if existing is not None and existing != indicator:
            raise ValueError("Indicator definition is immutable")
        return replace(state, indicators={**state.indicators, indicator.id: indicator})
    if event.event_type == "indicator.updated":
        indicator_id = _str(p, "indicator_id")
        indicator = state.indicators[indicator_id]
        updated = replace(
            indicator,
            role=cast(Literal["target", "guard", "none"], p.get("role", indicator.role)),
            evidence_session_ids=tuple(
                cast(list[str], p.get("evidence_session_ids", list(indicator.evidence_session_ids)))
            ),
        )
        return replace(state, indicators={**state.indicators, indicator_id: updated})
    if event.event_type == "indicator.value.recorded":
        value = IndicatorValue(
            indicator_id=_str(p, "indicator_id"),
            subject_id=_str(p, "subject_id"),
            variant_id=_str(p, "variant_id"),
            value=cast(float, p["value"]),
            guard_result=cast(Literal["pass", "fail"] | None, p.get("guard_result")),
            producer=_str(p, "producer"),
            artifact_id=cast(str | None, p.get("artifact_id")),
            event_seq=event.event_seq,
        )
        if value.guard_result is not None and state.indicators[value.indicator_id].role != "guard":
            raise ValueError("guard result requires a guard Indicator")
        key = (value.indicator_id, value.subject_id, value.variant_id)
        return replace(
            state,
            indicator_values={
                **state.indicator_values,
                key: (*state.indicator_values.get(key, ()), value),
            },
        )
    if event.event_type == "note.updated":
        note = NoteRevision(
            project_id=_str(p, "project_id"),
            markdown=_str(p, "markdown"),
            content_sha=_str(p, "content_sha"),
            actor_id=_str(p, "actor_id"),
            event_seq=event.event_seq,
        )
        return replace(state, notes=(*state.notes, note))
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
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value
