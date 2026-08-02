"""Single-writer append-only SQLite event store."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Self, cast

from pydantic import TypeAdapter

from abar.foundation.canonical_json import canonical_json_bytes, canonical_sha256
from abar.foundation.events import EventDraft, EventEnvelope
from abar.foundation.json_types import JSONValue

_PAYLOAD = TypeAdapter(dict[str, JSONValue])


class IdempotencyConflictError(ValueError):
    pass


class EventIntegrityError(RuntimeError):
    pass


class EventTransaction:
    def __init__(self, store: "EventStore", causation_id: str | None) -> None:
        self._store = store
        self._causation_id = causation_id

    def append(self, draft: EventDraft) -> EventEnvelope:
        if self._causation_id is not None and draft.causation_id not in (None, self._causation_id):
            raise ValueError("draft causation ID conflicts with transaction")
        if self._causation_id is not None and draft.causation_id is None:
            draft = draft.model_copy(update={"causation_id": self._causation_id})
        return self._store.append_in_transaction(draft)


class EventStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # FastAPI may enter, use, and exit one request-scoped sync dependency on
        # different worker threads. The connection is never shared across requests.
        self._connection = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA foreign_keys = ON")
        current_mode = cast(
            str,
            self._connection.execute("PRAGMA journal_mode").fetchone()[0],
        )
        if current_mode.lower() != "wal":
            self._connection.execute("PRAGMA journal_mode = WAL")
        schema_exists = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'events'"
        ).fetchone()
        if schema_exists is None:
            self._create_schema()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
                ts TEXT NOT NULL,
                causation_id TEXT,
                idempotency_key TEXT NOT NULL UNIQUE,
                payload_hash TEXT NOT NULL CHECK (payload_hash GLOB 'sha256:*'),
                payload TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS events_reject_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS events_reject_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
            """
        )

    def append(self, draft: EventDraft) -> EventEnvelope:
        with self.transaction(causation_id=draft.causation_id) as tx:
            return tx.append(draft)

    def append_many(self, drafts: tuple[EventDraft, ...]) -> tuple[EventEnvelope, ...]:
        if not drafts:
            return ()
        with self.transaction(causation_id=drafts[0].causation_id) as tx:
            return tuple(tx.append(draft) for draft in drafts)

    @contextmanager
    def transaction(self, *, causation_id: str | None = None) -> Generator[EventTransaction]:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            yield EventTransaction(self, causation_id)
        except BaseException:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def append_in_transaction(self, draft: EventDraft) -> EventEnvelope:
        payload_text = canonical_json_bytes(draft.payload).decode("utf-8")
        existing = self._connection.execute(
            "SELECT * FROM events WHERE idempotency_key = ?", (draft.idempotency_key,)
        ).fetchone()
        if existing is not None:
            envelope = self._row_to_envelope(existing)
            if not self._matches_retry(envelope, draft):
                raise IdempotencyConflictError(
                    f"idempotency key {draft.idempotency_key!r} was reused"
                )
            return envelope
        cursor = self._connection.execute(
            """INSERT INTO events
               (event_id,event_type,schema_version,ts,causation_id,idempotency_key,payload_hash,payload)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                draft.event_id,
                draft.event_type,
                draft.schema_version,
                draft.ts.isoformat(),
                draft.causation_id,
                draft.idempotency_key,
                draft.payload_hash,
                payload_text,
            ),
        )
        row = self._connection.execute(
            "SELECT * FROM events WHERE event_seq = ?", (cursor.lastrowid,)
        ).fetchone()
        if row is None:
            raise RuntimeError("appended event could not be read back")
        return self._row_to_envelope(row)

    def read_all(self, *, since: int = 0, limit: int | None = None) -> tuple[EventEnvelope, ...]:
        sql = "SELECT * FROM events WHERE event_seq > ? ORDER BY event_seq"
        params: tuple[object, ...] = (since,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (since, limit)
        rows = self._connection.execute(sql, params).fetchall()
        return tuple(self._row_to_envelope(row) for row in rows)

    def read_operation(self, idempotency_key: str) -> tuple[EventEnvelope, ...]:
        rows = self._connection.execute(
            """SELECT * FROM events
               WHERE idempotency_key = ? OR causation_id = ?
               ORDER BY event_seq""",
            (idempotency_key, idempotency_key),
        ).fetchall()
        return tuple(self._row_to_envelope(row) for row in rows)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @staticmethod
    def _matches_retry(envelope: EventEnvelope, draft: EventDraft) -> bool:
        return (
            envelope.event_type == draft.event_type
            and envelope.schema_version == draft.schema_version
            and envelope.causation_id == draft.causation_id
            and envelope.payload_hash == draft.payload_hash
        )

    @staticmethod
    def _row_to_envelope(row: sqlite3.Row) -> EventEnvelope:
        payload_text = cast(str, row["payload"])
        payload = _PAYLOAD.validate_json(payload_text)
        payload_hash = cast(str, row["payload_hash"])
        expected = f"sha256:{canonical_sha256(payload)}"
        if canonical_json_bytes(payload).decode("utf-8") != payload_text:
            raise EventIntegrityError("stored event payload is not canonical JSON")
        if payload_hash != expected:
            raise EventIntegrityError("stored event payload hash does not match payload")
        return EventEnvelope(
            event_seq=cast(int, row["event_seq"]),
            event_id=cast(str, row["event_id"]),
            event_type=cast(str, row["event_type"]),
            schema_version=cast(int, row["schema_version"]),
            ts=datetime.fromisoformat(cast(str, row["ts"])),
            causation_id=cast(str | None, row["causation_id"]),
            idempotency_key=cast(str, row["idempotency_key"]),
            payload_hash=payload_hash,
            payload=payload,
        )
