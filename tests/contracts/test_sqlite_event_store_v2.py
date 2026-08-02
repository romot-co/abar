from datetime import UTC, datetime
from pathlib import Path

import pytest

from abar.foundation.events import EventDraft
from abar.infrastructure.sqlite_event_store import EventStore, IdempotencyConflictError


def _draft(key: str, value: int) -> EventDraft:
    return EventDraft(
        event_id=f"ev_{key}_{value}",
        event_type="test.event",
        schema_version=1,
        ts=datetime.now(UTC),
        causation_id="cause",
        idempotency_key=key,
        payload={"value": value},
    )


def test_same_idempotency_key_same_payload_returns_original(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.sqlite3") as store:
        first = store.append(_draft("key", 1))
        retry = store.append(_draft("key", 1))
        assert retry.event_seq == first.event_seq
        assert len(store.read_all()) == 1


def test_same_idempotency_key_different_payload_is_rejected(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.sqlite3") as store:
        store.append(_draft("key", 1))
        with pytest.raises(IdempotencyConflictError):
            store.append(_draft("key", 2))


def test_transaction_rolls_back_all_events(tmp_path: Path) -> None:
    with EventStore(tmp_path / "events.sqlite3") as store:
        with pytest.raises(RuntimeError), store.transaction(causation_id="cause") as tx:
            tx.append(_draft("one", 1))
            raise RuntimeError("stop")
        assert store.read_all() == ()


def test_existing_wal_store_can_open_while_another_connection_is_writing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.sqlite3"
    with EventStore(path) as writer:
        with writer.transaction(causation_id="cause") as tx:
            tx.append(_draft("one", 1))
            with EventStore(path) as reader:
                assert reader.read_all() == ()
        with EventStore(path) as reader:
            assert len(reader.read_all()) == 1
