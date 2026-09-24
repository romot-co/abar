# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
"""HTTP boundary behaviour for retries, filesystem failures, and browser cookies."""

import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from abar.app import commands
from abar.app.repository import WorkspaceRepository
from abar.compare.models import RecipeRef
from abar.server import create_app
from abar.server.audio_tokens import AudioTokenStore

_AUTOMATION = {"Authorization": "Bearer automation", "X-ABAR-Actor": "agent-1"}
_INTERACTION = {"Authorization": "Bearer interaction"}


def _app(root: Path, origin: str = "http://testserver") -> FastAPI:
    return create_app(
        root,
        automation_token="automation",
        interaction_token="interaction",
        allowed_origins=frozenset({origin}),
    )


def _project(root: Path, wav_file: Callable[[str, float], Path]) -> None:
    repository = WorkspaceRepository.open(root)
    try:
        commands.init_project(
            repository, name="Project", brief="b", material_paths=(wav_file("s.wav", 220.0),)
        )
    finally:
        repository.close()


@pytest.mark.parametrize(
    ("path", "result"), [("/api/materials", "registered"), ("/api/audio/import", "imported")]
)
def test_upload_retry_with_the_same_key_returns_the_first_result(
    tmp_path: Path, wav_file: Callable[[str, float], Path], path: str, result: str
) -> None:
    root = tmp_path / "workspace"
    _project(root, wav_file)
    data = wav_file("upload.wav", 330.0).read_bytes()
    headers = {**_AUTOMATION, "Idempotency-Key": "upload-1"}
    with TestClient(_app(root)) as client:
        first = client.post(path, headers=headers, files={"file": ("upload.wav", data)})
        retried = client.post(path, headers=headers, files={"file": ("upload.wav", data)})
        changed = client.post(
            path, headers=headers, files={"file": ("upload.wav", data[:-8] + bytes(8))}
        )

    assert first.status_code == 200, first.json()
    assert first.json()["result"] == result
    assert retried.status_code == 200, retried.json()
    assert retried.json()["id"] == first.json()["id"]
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "idempotency_conflict"


def test_missing_audio_object_is_a_structured_error(
    tmp_path: Path, wav_file: Callable[[str, float], Path]
) -> None:
    root = tmp_path / "workspace"
    repository = WorkspaceRepository.open(root)
    try:
        session_id = commands.create_quick_listen(
            repository,
            str(wav_file("left.wav", 220.0)),
            str(wav_file("right.wav", 330.0)),
            recipe=RecipeRef("native"),
        )
        commands.start_session(repository, session_id)
    finally:
        repository.close()
    with TestClient(_app(root)) as client:
        deck = client.get("/api/deck/active", headers=_INTERACTION).json()
        for stored in (root / "objects").rglob("*"):
            if stored.is_file():
                stored.unlink()
        response = client.get(deck["audio"][0]["url"], headers=_INTERACTION)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "object_missing"


def test_filesystem_errors_become_structured_errors(tmp_path: Path) -> None:
    application = _app(tmp_path / "workspace")

    def missing() -> None:
        raise FileNotFoundError(2, "No such file or directory", "/nowhere/archive.zip")

    def denied() -> None:
        raise PermissionError(13, "Permission denied", "/locked")

    application.add_api_route("/test/missing", missing)
    application.add_api_route("/test/denied", denied)
    with TestClient(application, raise_server_exceptions=False) as client:
        not_found = client.get("/test/missing")
        failed = client.get("/test/denied")

    assert not_found.status_code == 409
    assert not_found.json()["error"] == {
        "code": "file_not_found",
        "message": "No such file or directory: /nowhere/archive.zip",
    }
    assert failed.status_code == 500
    assert failed.json()["error"]["code"] == "filesystem_error"


def test_missing_indicator_definition_file_is_a_command_error(
    tmp_path: Path, wav_file: Callable[[str, float], Path]
) -> None:
    root = tmp_path / "workspace"
    _project(root, wav_file)
    with TestClient(_app(root)) as client:
        response = client.post(
            "/api/indicators",
            headers=_AUTOMATION,
            json={
                "indicator_id": "ind_loudness_v1",
                "label": "Loudness",
                "description": "Integrated loudness",
                "definition_path": str(tmp_path / "missing.md"),
                "subject_kind": "audio",
                "unit": "LUFS",
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "indicator_definition_unreadable"


def test_unknown_workspace_cookie_falls_back_to_the_primary_workspace(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path / "workspace")) as client:
        client.post("/api/browser-sessions", headers=_INTERACTION)
        client.cookies.set("abar_workspace", "workspace_gone")
        catalog = client.get("/api/workspaces")
        status = client.get("/api/status")

    assert catalog.status_code == 200
    assert status.status_code == 200
    primary = catalog.json()["selected_id"]
    assert primary.startswith("workspace_") and primary != "workspace_gone"
    assert f"abar_workspace={primary}" in catalog.headers["set-cookie"]


def test_wrong_tokens_are_rejected(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path / "workspace")) as client:
        wrong_bearer = client.get("/api/status", headers={"Authorization": "Bearer interactio"})
        # A non-ASCII token must be rejected, not crash str-based compare_digest.
        non_ascii = client.get(
            "/api/status",
            headers=[(b"Authorization", "Bearer \xefnteraction".encode("latin-1"))],
        )
        client.cookies.set("abar_interaction", "interactionX")
        wrong_cookie = client.get("/api/status")

    assert wrong_bearer.status_code == 403
    assert non_ascii.status_code == 403
    assert wrong_cookie.status_code == 403


def test_browser_cookies_are_scoped_to_the_server_port(tmp_path: Path) -> None:
    first = _app(tmp_path / "first", "http://127.0.0.1:8765")
    with TestClient(first, base_url="http://127.0.0.1:8765") as client:
        connected = client.post("/api/browser-sessions", headers=_INTERACTION)
        set_cookies = connected.headers.get_list("set-cookie")
        assert any(item.startswith("abar_interaction_8765=interaction;") for item in set_cookies)
        assert any(item.startswith("abar_workspace_8765=") for item in set_cookies)
        assert not any(
            item.startswith(("abar_interaction=", "abar_workspace=")) for item in set_cookies
        )
        # The browser sends every port's cookies to 127.0.0.1; only ours counts.
        client.cookies.clear()
        shared = "abar_interaction_8766=other; abar_interaction_8765=interaction"
        assert client.get("/api/status", headers={"Cookie": shared}).status_code == 200
        foreign = "abar_interaction_8766=interaction"
        assert client.get("/api/status", headers={"Cookie": foreign}).status_code == 403
        # A cookie from a server predating port scoping still works until replaced.
        assert (
            client.get(
                "/api/status", headers={"Cookie": "abar_interaction=interaction"}
            ).status_code
            == 200
        )


def test_expired_audio_grants_are_purged() -> None:
    store = AudioTokenStore(lifetime_seconds=0.05)
    first = store.issue(Path("/workspace"), "obj_a").removeprefix("/api/audio/")
    assert store.consume(first) == (Path("/workspace"), "obj_a")
    # Still valid within its lifetime: the player may request the same URL again.
    assert store.consume(first) == (Path("/workspace"), "obj_a")
    time.sleep(0.1)
    second = store.issue(Path("/workspace"), "obj_b").removeprefix("/api/audio/")
    assert len(store) == 1
    assert store.consume(first) is None
    time.sleep(0.1)
    assert store.consume(second) is None
    assert len(store) == 0
