"""Bounded, server-owned projections of append-only workspace histories."""

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from abar.app.state import EVENT_SCHEMAS, ABARState, reduce_state
from abar.foundation.replay import ReplayResult, incremental_replay
from abar.infrastructure.sqlite_event_store import EventStore


@dataclass(slots=True)
class ReplayCache:
    capacity: int = 8
    _entries: OrderedDict[tuple[Path, tuple[int, int]], ReplayResult[ABARState]] = field(
        default_factory=OrderedDict[tuple[Path, tuple[int, int]], ReplayResult[ABARState]]
    )
    _lock: Lock = field(default_factory=Lock)

    def replay(
        self,
        root: Path,
        identity: tuple[int, int],
        events: EventStore,
        *,
        force: bool = False,
    ) -> ReplayResult[ABARState]:
        # Serialize projection updates so concurrent requests cannot publish an
        # older snapshot over a newer one. SQLite connections remain request-local.
        key = (root, identity)
        with self._lock:
            previous = self._entries.get(key)
            if (
                force
                or previous is None
                or events.latest_sequence() < previous.processed_through_event_seq
            ):
                previous = ReplayResult(state=ABARState())
            result = incremental_replay(
                previous,
                events.read_all(since=previous.processed_through_event_seq),
                schemas=EVENT_SCHEMAS,
                reducer=reduce_state,
            )
            self._entries[key] = result
            self._entries.move_to_end(key)
            while len(self._entries) > self.capacity:
                self._entries.popitem(last=False)
            return result
