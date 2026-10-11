"""Projection for Sessions, Indicator ledger, Note, and memo."""

from dataclasses import dataclass, field, replace
from typing import Literal, cast

from abar.compare.models import RecipeRef, TimeRange
from abar.foundation.events import EventEnvelope
from abar.foundation.json_types import JSONValue
from abar.research.models import (
    BestFlag,
    DictionaryEntry,
    Indicator,
    IndicatorValue,
    NoteRevision,
    ProjectSession,
    Symptom,
)
from abar.research.verification import VerificationReport


@dataclass(frozen=True, slots=True)
class ResearchState:
    project_sessions: dict[str, ProjectSession] = field(default_factory=dict[str, ProjectSession])
    indicators: dict[str, Indicator] = field(default_factory=dict[str, Indicator])
    indicator_values: dict[tuple[str, str, str], tuple[IndicatorValue, ...]] = field(
        default_factory=dict[tuple[str, str, str], tuple[IndicatorValue, ...]]
    )
    notes: tuple[NoteRevision, ...] = ()
    symptoms: dict[str, Symptom] = field(default_factory=dict[str, Symptom])
    verifications: dict[str, VerificationReport] = field(
        default_factory=dict[str, VerificationReport]
    )
    baselines: dict[str, str] = field(default_factory=dict[str, str])
    current_best_flags: tuple[BestFlag, ...] = ()
    dictionary: dict[str, DictionaryEntry] = field(default_factory=dict[str, DictionaryEntry])
    prescreen_indicator_id: str | None = None


def reduce_research(state: ResearchState, event: EventEnvelope) -> ResearchState:
    p = event.payload
    if event.event_type in {"dictionary.entry.recorded", "dictionary.entry.updated"}:
        entry = DictionaryEntry(
            term=_dictionary_text(p, "term"),
            definition=_dictionary_text(p, "definition"),
            indicator_id=cast(str | None, p.get("indicator_id")),
            status=cast(Literal["candidate", "validated", "rejected"], p["status"]),
            evidence_session_ids=tuple(cast(list[str], p["evidence_session_ids"])),
            scope=_dictionary_text(p, "scope"),
            symptom_ids=tuple(cast(list[str], p["symptom_ids"])),
        )
        if entry.indicator_id is not None and entry.indicator_id not in state.indicators:
            raise ValueError("dictionary references an unknown Indicator")
        if any(session not in state.project_sessions for session in entry.evidence_session_ids):
            raise ValueError("dictionary references an unknown Project Session")
        if any(symptom not in state.symptoms for symptom in entry.symptom_ids):
            raise ValueError("dictionary references an unknown Symptom")
        existing = state.dictionary.get(entry.term)
        if (event.event_type == "dictionary.entry.recorded") != (existing is None):
            raise ValueError("dictionary entry must be registered before updating")
        symptoms = {
            key: replace(
                symptom,
                dictionary_terms=(
                    *tuple(term for term in symptom.dictionary_terms if term != entry.term),
                    *((entry.term,) if key in entry.symptom_ids else ()),
                ),
            )
            for key, symptom in state.symptoms.items()
        }
        return replace(state, dictionary={**state.dictionary, entry.term: entry}, symptoms=symptoms)
    if event.event_type == "project.prescreen_indicator.changed":
        indicator_id = cast(str | None, p["indicator_id"])
        if indicator_id is not None and indicator_id not in state.indicators:
            raise ValueError("prescreen setting references an unknown Indicator")
        return replace(state, prescreen_indicator_id=indicator_id)
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
            symptom_id=cast(str | None, p.get("symptom_id")) if event.schema_version == 2 else None,
            warnings=tuple(cast(list[str], p.get("warnings", [])))
            if event.schema_version == 2
            else (),
        )
        return replace(
            state,
            project_sessions={**state.project_sessions, project_session.id: project_session},
        )
    if event.event_type == "symptom.opened":
        symptom = Symptom(
            id=_str(p, "id"),
            project_id=_str(p, "project_id"),
            title=_str(p, "title"),
            source_delivery_id=_str(p, "source_delivery_id"),
            source_slot=cast(Literal["a", "b"], p["source_slot"]),
            variant_id=_str(p, "variant_id"),
            material_id=_str(p, "material_id"),
            clip_id=_str(p, "clip_id"),
            range=TimeRange(**cast(dict[str, float], p["range"])),
            context_seconds=cast(float, p["context_seconds"]),
            audio_pcm_sha=_str(p, "audio_pcm_sha"),
            status=cast(Literal["open", "resolved", "withdrawn"], p["status"]),
            facts=_str(p, "facts"),
            hypotheses=_str(p, "hypotheses"),
            dictionary_terms=tuple(cast(list[str], p["dictionary_terms"])),
            created_event_seq=event.event_seq,
        )
        return replace(state, symptoms={**state.symptoms, symptom.id: symptom})
    if event.event_type == "symptom.updated":
        symptom_id = _str(p, "symptom_id")
        symptom = replace(
            state.symptoms[symptom_id],
            facts=_str(p, "facts"),
            hypotheses=_str(p, "hypotheses"),
            dictionary_terms=tuple(cast(list[str], p["dictionary_terms"])),
        )
        return replace(state, symptoms={**state.symptoms, symptom_id: symptom})
    if event.event_type in {"symptom.resolved", "symptom.reopened", "symptom.withdrawn"}:
        symptom_id = _str(p, "symptom_id")
        status = {
            "symptom.resolved": "resolved",
            "symptom.reopened": "open",
            "symptom.withdrawn": "withdrawn",
        }[event.event_type]
        symptom = replace(
            state.symptoms[symptom_id],
            status=cast(Literal["open", "resolved", "withdrawn"], status),
        )
        return replace(state, symptoms={**state.symptoms, symptom_id: symptom})
    if event.event_type == "verification.recorded":
        report = VerificationReport.model_validate(p["report"])
        return replace(
            state, verifications={**state.verifications, _str(p, "verification_id"): report}
        )
    if event.event_type == "baseline.recorded":
        return replace(
            state, baselines={**state.baselines, _str(p, "variant_id"): _str(p, "label")}
        )
    if event.event_type == "current_best.flagged":
        if _str(p, "symptom_id") not in state.symptoms:
            raise ValueError("flag references an unknown Symptom")
        flag = BestFlag(
            _str(p, "symptom_id"),
            _str(p, "session_id"),
            _str(p, "reason"),
            _str(p, "variant_id"),
            event.event_seq,
        )
        return replace(state, current_best_flags=(*state.current_best_flags, flag))
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
        id=cast(Literal["native", "aligned", "matched", "level-matched"], payload["id"]),
        version=cast(Literal[1, 2], payload["version"]),
        config=cast(dict[str, JSONValue], payload.get("config", {})),
    )


def _str(payload: dict[str, JSONValue], key: str) -> str:
    return cast(str, payload[key])


def _dictionary_text(payload: dict[str, JSONValue], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"dictionary {key} must be text")
    return value


def _int(payload: dict[str, JSONValue], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value
