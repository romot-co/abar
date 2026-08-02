from datetime import UTC, datetime

from abar.foundation.events import EventEnvelope
from abar.foundation.replay import EventAuthority, EventSchema, full_replay


def _event(sequence: int, event_type: str) -> EventEnvelope:
    return EventEnvelope(
        event_seq=sequence,
        event_id=f"ev_{sequence}",
        event_type=event_type,
        schema_version=1,
        ts=datetime.now(UTC),
        causation_id=None,
        idempotency_key=f"key_{sequence}",
        payload_hash="sha256:" + "0" * 64,
        payload={},
    )


def test_unknown_event_degrades_without_a_registered_schema() -> None:
    result = full_replay(
        0,
        (_event(1, "indicator.future.observed"),),
        schemas={},
        reducer=lambda state, _event: state + 1,
    )
    assert result.degraded is not None
    assert result.degraded.reason == "unknown_authoritative_event"


def test_unknown_authoritative_event_degrades() -> None:
    result = full_replay(
        0,
        (_event(1, "project.future.changed"),),
        schemas={"known": EventSchema(EventAuthority.AUTHORITATIVE, frozenset({1}))},
        reducer=lambda state, _event: state,
    )
    assert result.degraded is not None
    assert result.degraded.reason == "unknown_authoritative_event"
