"""Workspace persistence boundary used by all application use cases."""

from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_path

from abar.app.replay_cache import ReplayCache
from abar.app.state import EVENT_SCHEMAS, ABARState, reduce_state
from abar.compare.rendering import RenderOutcome
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
    cache: ReplayCache | None = None
    database_identity: tuple[int, int] = (0, 0)
    # Renders are expensive and deterministic per Variant, Material and runtime.
    # Keeping them for the repository's lifetime lets a command that lost a write
    # race re-validate against fresh state without invoking the renderer again.
    render_memo: dict[str, RenderOutcome] = field(default_factory=dict[str, RenderOutcome])

    @classmethod
    def open(
        cls, root: Path | None = None, *, cache: ReplayCache | None = None
    ) -> "WorkspaceRepository":
        selected = (root or default_workspace_path()).expanduser().resolve()
        selected.mkdir(parents=True, exist_ok=True)
        events = EventStore(selected / "events.sqlite3")
        info = (selected / "events.sqlite3").stat()
        return cls(
            selected,
            events,
            ImmutableObjectStore(selected / "objects"),
            cache,
            (info.st_dev, info.st_ino),
        )

    def close(self) -> None:
        self.events.close()

    def replay(self, *, force: bool = False) -> ReplayResult[ABARState]:
        if self.cache is not None:
            return self.cache.replay(self.root, self.database_identity, self.events, force=force)
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
            degraded = result.degraded
            raise WorkspaceDegraded(
                f"event {degraded.event_seq} ({degraded.event_type}, schema "
                f"{degraded.schema_version}) degraded replay: {degraded.reason}. "
                "Preserve this Workspace and create a new one; pre-release events are not migrated."
            )
        self.events.observe(result.processed_through_event_seq)
        return result.state
