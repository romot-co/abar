# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from abar.app import commands
from abar.app.repository import WorkspaceRepository
from abar.compare.models import RecipeRef
from abar.server import create_app


def test_interaction_capability_and_blind_sealing(
    tmp_path: Path,
    wav_file: Callable[[str, float], Path],
) -> None:
    root = tmp_path / "server-workspace"
    repository = WorkspaceRepository.open(root)
    try:
        session_id = commands.create_quick_listen(
            repository,
            str(wav_file("left.wav", 220.0)),
            str(wav_file("right.wav", 330.0)),
            recipe=RecipeRef("native"),
            presentation="blind",
        )
        state = repository.state()
        comparison_id = state.compare.sessions[session_id].items[0].comparison_id
    finally:
        repository.close()
    application = create_app(
        root,
        automation_token="automation",
        interaction_token="interaction",
        allowed_origins=frozenset({"http://testserver"}),
    )
    automation = {"Authorization": "Bearer automation", "X-ABAR-Actor": "agent-1"}
    interaction = {"Authorization": "Bearer interaction"}
    with TestClient(application) as client:
        assert client.get(f"/api/entities/{comparison_id}", headers=interaction).status_code == 403
        assert client.get(f"/api/entities/{comparison_id}", headers=automation).status_code == 200
        rejected = client.post(
            f"/api/sessions/{session_id}/start",
            headers=automation,
            json={"allocation_seed": 0},
        )
        assert rejected.status_code == 403
        assert (
            client.post(
                f"/api/sessions/{session_id}/start",
                headers=interaction,
                json={"allocation_seed": 0},
            ).status_code
            == 200
        )
        deck = client.get("/api/deck/active", headers=interaction).json()
        assert deck["identity_by_slot"] is None
        delivery_id = deck["delivery_id"]
        answer = {
            "preference": 3,
            "blockers": {
                "a": {"selected": False, "note": None},
                "b": {"selected": False, "note": None},
            },
            "comment": None,
            "telemetry": {"listen_ms": {"a": 10, "b": 10}, "switches": 1, "answer_ms": 50},
        }
        assert (
            client.post(
                f"/api/deliveries/{delivery_id}/judgments",
                headers=automation,
                json=answer,
            ).status_code
            == 403
        )
        recorded = client.post(
            f"/api/deliveries/{delivery_id}/judgments",
            headers=interaction,
            json=answer,
        )
        assert recorded.status_code == 200
        assert recorded.json()["result"] == "ended"
        completion = client.get(f"/api/sessions/{session_id}/completion", headers=interaction)
        assert completion.status_code == 200
        assert completion.json()["items"][0]["identity_by_slot"] is not None
        assert completion.json()["items"][0]["judgment"]["preference"] == 3
        assert completion.json()["items"][0]["skipped"] is False


def test_browser_cookie_grants_interaction_after_bootstrap(tmp_path: Path) -> None:
    application = create_app(
        tmp_path / "server-workspace",
        automation_token="automation",
        interaction_token="interaction",
        allowed_origins=frozenset({"http://testserver"}),
    )
    with TestClient(application) as client:
        assert client.get("/api/status").status_code == 403
        connected = client.post(
            "/api/browser-sessions", headers={"Authorization": "Bearer interaction"}
        )
        assert connected.status_code == 200
        assert "abar_interaction" in connected.cookies
        # 以後はCookieだけでinteractionとして開ける
        assert client.get("/api/status").status_code == 200
        # Cookieがあってもautomation bearerはinteraction専用endpointに昇格しない
        rejected = client.post(
            "/api/browser-sessions",
            headers={"Authorization": "Bearer automation", "X-ABAR-Actor": "agent-1"},
        )
        assert rejected.status_code == 403


def test_interaction_can_switch_workspace_without_moving_automation(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, name in ((first, "First"), (second, "Second")):
        repository = WorkspaceRepository.open(root)
        try:
            commands.init_project(repository, name=name, brief=f"{name} brief")
        finally:
            repository.close()
    application = create_app(
        first,
        workspace_roots=(first, second),
        automation_token="automation",
        interaction_token="interaction",
        allowed_origins=frozenset({"http://testserver"}),
    )
    interaction = {"Authorization": "Bearer interaction"}
    automation = {"Authorization": "Bearer automation", "X-ABAR-Actor": "agent-1"}
    with TestClient(application) as client:
        catalog = client.get("/api/workspaces", headers=interaction).json()
        assert [item["name"] for item in catalog["workspaces"]] == ["First", "Second"]
        second_id = catalog["workspaces"][1]["id"]
        selected = client.post(f"/api/workspaces/{second_id}/select", headers=interaction)
        assert selected.status_code == 200
        assert client.get("/api/project", headers=interaction).json()["name"] == "Second"
        assert client.get("/api/project", headers=automation).status_code == 403
        assert client.get("/api/project/snapshot", headers=automation).json()["name"] == "First"
