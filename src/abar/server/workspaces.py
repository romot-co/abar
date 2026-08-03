"""Project workspace catalog for the local interaction UI."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from abar.app.repository import WorkspaceRepository


@dataclass(frozen=True, slots=True)
class WorkspaceEntry:
    id: str
    root: Path
    name: str


@dataclass(frozen=True, slots=True)
class WorkspaceCatalog:
    primary_id: str
    entries: tuple[WorkspaceEntry, ...]

    @classmethod
    def build(
        cls,
        primary_root: Path,
        roots: tuple[Path, ...] | None = None,
    ) -> "WorkspaceCatalog":
        primary = primary_root.expanduser().resolve()
        selected_roots = roots or (primary,)
        normalized = tuple(dict.fromkeys(item.expanduser().resolve() for item in selected_roots))
        if primary not in normalized:
            normalized = (primary, *normalized)
        entries = tuple(_entry(root) for root in normalized)
        return cls(primary_id=_workspace_id(primary), entries=entries)

    def resolve(self, workspace_id: str | None) -> Path:
        selected_id = self.primary_id if workspace_id is None else workspace_id
        for entry in self.entries:
            if entry.id == selected_id:
                return entry.root
        raise ValueError("unknown Project workspace")


def discover_project_workspaces(primary_root: Path) -> tuple[Path, ...]:
    """Find sibling ABAR workspaces without merging their event stores."""
    primary = primary_root.expanduser().resolve()
    siblings: list[Path] = []
    for child in sorted(primary.parent.iterdir()):
        if child == primary or not child.is_dir() or not (child / "events.sqlite3").is_file():
            continue
        repository = WorkspaceRepository.open(child)
        try:
            replay = repository.replay()
            if replay.degraded is not None or replay.state.project.project is not None:
                siblings.append(child.resolve())
        finally:
            repository.close()
    return (primary, *siblings)


def _entry(root: Path) -> WorkspaceEntry:
    repository = WorkspaceRepository.open(root)
    try:
        project = repository.replay().state.project.project
        name = root.name if project is None else project.name
    finally:
        repository.close()
    return WorkspaceEntry(id=_workspace_id(root), root=root, name=name)


def _workspace_id(root: Path) -> str:
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    return f"workspace_{digest}"
