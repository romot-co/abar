"""Workspace persistence boundary used by all application use cases."""

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

from abar.app.state import EVENT_SCHEMAS, ABARState, reduce_state
from abar.foundation.replay import ReplayResult, full_replay
from abar.infrastructure.object_store import ImmutableObjectStore
from abar.infrastructure.sqlite_event_store import EventStore


class WorkspaceError(RuntimeError):
    code = "workspace_error"


class WorkspaceDegraded(WorkspaceError):
    code = "workspace_degraded"


def default_workspace_path() -> Path:
    return Path(user_data_path("abar", appauthor=False)) / "default"


@dataclass(slots=True)
class WorkspaceRepository:
    root: Path
    events: EventStore
    objects: ImmutableObjectStore

    @classmethod
    def open(cls, root: Path | None = None) -> "WorkspaceRepository":
        selected = (root or default_workspace_path()).expanduser().resolve()
        selected.mkdir(parents=True, exist_ok=True)
        events = EventStore(selected / "events.sqlite3")
        return cls(selected, events, ImmutableObjectStore(selected / "objects"))

    def close(self) -> None:
        self.events.close()

    def replay(self) -> ReplayResult[ABARState]:
        result = full_replay(
            ABARState(),
            self.events.read_all(),
            schemas=EVENT_SCHEMAS,
            reducer=reduce_state,
        )
        return result

    def state(self) -> ABARState:
        result = self.replay()
        if result.degraded is not None:
            raise WorkspaceDegraded(
                f"event {result.degraded.event_seq} degraded replay: {result.degraded.reason}"
            )
        return result.state
