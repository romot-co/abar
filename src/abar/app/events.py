"""Application helpers for deterministic event drafts."""

from datetime import UTC, datetime

from abar.foundation.events import EventDraft
from abar.foundation.json_types import JSONValue
from abar.foundation.time_ids import new_id


def draft(
    event_type: str,
    payload: dict[str, JSONValue],
    *,
    idempotency_key: str,
    causation_id: str | None = None,
) -> EventDraft:
    return EventDraft(
        event_id=new_id("ev_"),
        event_type=event_type,
        schema_version=1,
        ts=datetime.now(UTC),
        causation_id=causation_id,
        idempotency_key=idempotency_key,
        payload=payload,
    )


def child_key(operation_key: str, index: int) -> str:
    return f"{operation_key}:{index}"
