"""Perceptual vocabulary and its external evidence, without adoption authority."""

from dataclasses import asdict, replace
from typing import Literal, cast

from abar.app.command_support import CommandError, existing_operation, operation_key, request_hash
from abar.app.events import draft
from abar.app.repository import WorkspaceRepository
from abar.foundation.json_types import JSONValue
from abar.research.models import DictionaryEntry


def add_dictionary_entry(
    repository: WorkspaceRepository,
    *,
    term: str,
    definition: str,
    indicator_id: str | None = None,
    status: Literal["candidate", "validated", "rejected"] = "candidate",
    evidence_session_ids: tuple[str, ...] = (),
    scope: str = "",
    symptom_ids: tuple[str, ...] = (),
    actor_id: str,
    idempotency_key: str | None = None,
) -> str:
    try:
        entry = DictionaryEntry(
            term, definition, indicator_id, status, evidence_session_ids, scope, symptom_ids
        )
    except ValueError as error:
        raise CommandError("invalid_dictionary_entry", str(error)) from error
    return _record_entry(
        repository,
        entry,
        event_type="dictionary.entry.recorded",
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )


def update_dictionary_entry(
    repository: WorkspaceRepository,
    term: str,
    *,
    definition: str | None = None,
    indicator_id: str | None = None,
    clear_indicator: bool = False,
    status: Literal["candidate", "validated", "rejected"] | None = None,
    evidence_session_ids: tuple[str, ...] | None = None,
    scope: str | None = None,
    symptom_ids: tuple[str, ...] | None = None,
    actor_id: str,
    idempotency_key: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    data: dict[str, JSONValue] = {
        "term": term,
        "definition": definition,
        "indicator_id": indicator_id,
        "clear_indicator": clear_indicator,
        "status": status,
        "evidence_session_ids": None
        if evidence_session_ids is None
        else list(evidence_session_ids),
        "scope": scope,
        "symptom_ids": None if symptom_ids is None else list(symptom_ids),
        "actor_id": actor_id,
    }
    fingerprint = request_hash("dictionary.entry.updated", data)
    if (
        existing_operation(repository, key, "dictionary.entry.updated", request_hash=fingerprint)
        is not None
    ):
        return term
    if clear_indicator and indicator_id is not None:
        raise CommandError("choose either an Indicator or --clear-indicator")
    current = repository.state().research.dictionary.get(term)
    if current is None:
        raise CommandError("unknown dictionary term")
    try:
        entry = replace(
            current,
            definition=current.definition if definition is None else definition,
            indicator_id=None if clear_indicator else indicator_id or current.indicator_id,
            status=current.status if status is None else status,
            evidence_session_ids=current.evidence_session_ids
            if evidence_session_ids is None
            else evidence_session_ids,
            scope=current.scope if scope is None else scope,
            symptom_ids=current.symptom_ids if symptom_ids is None else symptom_ids,
        )
    except ValueError as error:
        raise CommandError("invalid_dictionary_entry", str(error)) from error
    return _record_entry(
        repository,
        entry,
        event_type="dictionary.entry.updated",
        actor_id=actor_id,
        idempotency_key=key,
        fingerprint=fingerprint,
    )


def _record_entry(
    repository: WorkspaceRepository,
    entry: DictionaryEntry,
    *,
    event_type: str,
    actor_id: str,
    idempotency_key: str | None,
    fingerprint: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    data = cast(dict[str, JSONValue], asdict(entry))
    data["evidence_session_ids"] = list(entry.evidence_session_ids)
    data["symptom_ids"] = list(entry.symptom_ids)
    data["actor_id"] = actor_id
    fingerprint = fingerprint or request_hash(event_type, data)
    if existing_operation(repository, key, event_type, request_hash=fingerprint) is not None:
        return entry.term
    state = repository.state()
    project = state.project.project
    if project is None:
        raise CommandError("Project does not exist")
    if event_type == "dictionary.entry.recorded" and entry.term in state.research.dictionary:
        raise CommandError("dictionary term already exists; use dictionary set")
    if entry.indicator_id is not None and entry.indicator_id not in state.research.indicators:
        raise CommandError("unknown dictionary Indicator")
    for session_id in entry.evidence_session_ids:
        session = state.research.project_sessions.get(session_id)
        if (
            session is None
            or state.compare.session_runtime[session.core_session_id].status != "ended"
        ):
            raise CommandError("dictionary evidence requires a completed Project Session")
    if any(symptom_id not in state.research.symptoms for symptom_id in entry.symptom_ids):
        raise CommandError("unknown dictionary Symptom")
    repository.events.append(
        draft(
            event_type,
            {**data, "project_id": project.id, "request_hash": fingerprint},
            idempotency_key=key,
        )
    )
    return entry.term
