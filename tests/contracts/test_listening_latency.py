from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from abar.app import commands
from abar.app.events import draft
from abar.app.replay_cache import ReplayCache
from abar.app.repository import WorkspaceDegraded, WorkspaceRepository
from abar.compare.models import RecipeRef
from abar.server import create_app
from abar.server.audio_tokens import AudioTokenStore


def test_cached_projection_tracks_external_writes_and_preserves_old_snapshot(
    tmp_path: Path,
) -> None:
    cache = ReplayCache()
    reader = WorkspaceRepository.open(tmp_path, cache=cache)
    writer = WorkspaceRepository.open(tmp_path)
    try:
        initial = reader.state()
        commands.init_project(writer, name="External", brief="Listen")
        updated = reader.state()
        assert initial.project.project is None
        assert updated == writer.state()
        assert reader.state() is updated
        writer.events.append(draft("note.updated", {}, idempotency_key="invalid-observation"))
        assert reader.replay() == writer.replay()
        assert reader.replay().isolated_event_seqs
        writer.events.append(draft("legacy.unsupported", {}, idempotency_key="unsupported"))
        with pytest.raises(WorkspaceDegraded):
            reader.state()
        assert reader.replay() == writer.replay()
        assert reader.replay(force=True) == writer.replay()
    finally:
        reader.close()
        writer.close()


def test_cache_reads_only_appended_events_and_rebuild_reads_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from abar.infrastructure.sqlite_event_store import EventStore

    cache = ReplayCache()
    repo = WorkspaceRepository.open(tmp_path, cache=cache)
    calls: list[int] = []
    read_all = EventStore.read_all

    def tracked(self: EventStore, *, since: int = 0, limit: int | None = None):
        calls.append(since)
        return read_all(self, since=since, limit=limit)

    try:
        commands.init_project(repo, name="Cached", brief="Listen")
        last = repo.replay().processed_through_event_seq
        monkeypatch.setattr(EventStore, "read_all", tracked)
        repo.state()
        repo.state()
        repo.replay(force=True)
        assert calls == [last, last, 0]
    finally:
        repo.close()


def test_cache_isolates_workspaces_and_handles_database_replacement(tmp_path: Path) -> None:
    cache = ReplayCache(capacity=2)

    def read(root: Path) -> str:
        repo = WorkspaceRepository.open(root, cache=cache)
        try:
            project = repo.state().project.project
            assert project is not None
            return project.name
        finally:
            repo.close()

    for name in ("one", "two", "three"):
        repo = WorkspaceRepository.open(tmp_path / name)
        commands.init_project(repo, name=name, brief="Listen")
        repo.close()
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(read, [tmp_path / "one", tmp_path / "two", tmp_path / "one"])) == [
            "one",
            "two",
            "one",
        ]
    # A restored workspace can have the same event count but different contents.
    (tmp_path / "three" / "events.sqlite3").replace(tmp_path / "one" / "events.sqlite3")
    assert read(tmp_path / "one") == "three"


def test_sealed_audio_delivery_needs_no_history_read(
    tmp_path: Path,
    wav_file: Callable[[str, float], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = WorkspaceRepository.open(tmp_path)
    try:
        session_id = commands.create_quick_listen(
            repo,
            str(wav_file("a.wav", 220)),
            str(wav_file("b.wav", 330)),
            recipe=RecipeRef("native"),
            presentation="blind",
        )
        commands.start_session(repo, session_id, allocation_seed=0)
    finally:
        repo.close()
    app = create_app(
        tmp_path,
        automation_token="agent",
        interaction_token="human",
        allowed_origins=frozenset({"http://testserver"}),
    )
    with TestClient(app) as client:
        response = client.get("/api/deck/active", headers={"Authorization": "Bearer human"})
        assert response.status_code == 200
        deck = response.json()
        assert deck["identity_by_slot"] is None
        urls = [audio["url"] for audio in deck["audio"]]
        expected = [client.get(url).content for url in urls]
        assert all(data.startswith(b"RIFF") for data in expected)

        def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("audio delivery must not open the event repository")

        monkeypatch.setattr(WorkspaceRepository, "open", forbidden)
        for url, data in zip(urls, expected, strict=True):
            audio = client.get(url)
            assert audio.status_code == 200
            assert audio.content == data
            assert audio.headers["cache-control"] == "no-store"
        assert client.get("/api/audio/invalid").status_code == 404


def test_audio_tokens_remain_expiring_and_workspace_bound(tmp_path: Path) -> None:
    tokens = AudioTokenStore()
    url = tokens.issue(tmp_path, "obj_test")
    assert "obj_test" not in url
    assert tokens.consume(url.rsplit("/", 1)[1]) == (tmp_path, "obj_test")
    expired = AudioTokenStore(lifetime_seconds=-1)
    url = expired.issue(tmp_path, "obj_test")
    assert expired.consume(url.rsplit("/", 1)[1]) is None
