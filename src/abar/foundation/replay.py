"""Authority-aware event replay."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from abar.foundation.events import EventEnvelope


class EventAuthority(StrEnum):
    AUTHORITATIVE = "authoritative"
    OBSERVATIONAL = "observational"


@dataclass(frozen=True, slots=True)
class EventSchema:
    authority: EventAuthority
    supported_versions: frozenset[int]

    def __post_init__(self) -> None:
        if not self.supported_versions or any(version < 1 for version in self.supported_versions):
            raise ValueError("event schemas need positive supported versions")


class EventReducer[StateT](Protocol):
    def __call__(self, state: StateT, event: EventEnvelope, /) -> StateT: ...


class ReplayOrderError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayDegradation:
    event_seq: int
    event_type: str
    schema_version: int
    reason: str


@dataclass(frozen=True, slots=True)
class ReplayResult[StateT]:
    state: StateT
    processed_through_event_seq: int = 0
    isolated_event_seqs: tuple[int, ...] = ()
    degraded: ReplayDegradation | None = None


def full_replay[StateT](
    initial_state: StateT,
    events: Iterable[EventEnvelope],
    *,
    schemas: Mapping[str, EventSchema],
    reducer: EventReducer[StateT],
) -> ReplayResult[StateT]:
    return incremental_replay(
        ReplayResult(state=initial_state), events, schemas=schemas, reducer=reducer
    )


def incremental_replay[StateT](
    previous: ReplayResult[StateT],
    events: Iterable[EventEnvelope],
    *,
    schemas: Mapping[str, EventSchema],
    reducer: EventReducer[StateT],
) -> ReplayResult[StateT]:
    result = previous
    if result.degraded is not None:
        return result
    for event in events:
        if event.event_seq <= result.processed_through_event_seq:
            raise ReplayOrderError("event sequence must increase strictly")
        schema = schemas.get(event.event_type)
        if schema is None:
            return _degraded(result, event, "unknown_authoritative_event")
        if event.schema_version not in schema.supported_versions:
            if schema.authority is EventAuthority.OBSERVATIONAL:
                result = _isolated(result, event)
                continue
            return _degraded(result, event, "unsupported_authoritative_schema")
        try:
            state = reducer(result.state, event)
        except (KeyError, TypeError, ValueError):
            if schema.authority is EventAuthority.OBSERVATIONAL:
                result = _isolated(result, event)
                continue
            return _degraded(result, event, "invalid_authoritative_event")
        result = ReplayResult(
            state=state,
            processed_through_event_seq=event.event_seq,
            isolated_event_seqs=result.isolated_event_seqs,
        )
    return result


def _isolated[StateT](result: ReplayResult[StateT], event: EventEnvelope) -> ReplayResult[StateT]:
    return ReplayResult(
        state=result.state,
        processed_through_event_seq=event.event_seq,
        isolated_event_seqs=(*result.isolated_event_seqs, event.event_seq),
    )


def _degraded[StateT](
    result: ReplayResult[StateT], event: EventEnvelope, reason: str
) -> ReplayResult[StateT]:
    return ReplayResult(
        state=result.state,
        processed_through_event_seq=result.processed_through_event_seq,
        isolated_event_seqs=result.isolated_event_seqs,
        degraded=ReplayDegradation(
            event_seq=event.event_seq,
            event_type=event.event_type,
            schema_version=event.schema_version,
            reason=reason,
        ),
    )
