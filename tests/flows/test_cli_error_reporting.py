"""CLI failures are reported as JSON/human errors and never leave empty Workspaces."""

import json
from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from abar.app import commands
from abar.app.repository import WorkspaceRepository
from abar.cli import app
from tests.conftest import persist_finite_variant


def _invoke(*arguments: str) -> tuple[int, dict[str, object]]:
    result = CliRunner().invoke(app, list(arguments))
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    return result.exit_code, json.loads(result.stdout)


def _error(payload: dict[str, object]) -> dict[str, object]:
    assert payload["schema_version"] == 2
    return payload["error"]  # type: ignore[return-value]


def test_listen_reports_operand_errors_without_a_traceback(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    code, payload = _invoke(
        "--workspace", str(root), "--json", "listen", "missing-a.wav", "missing-b.wav"
    )
    assert code == 3
    assert "audio file does not exist" in str(_error(payload)["message"])
    assert not root.exists()


def test_rebuild_does_not_create_a_workspace(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    code, payload = _invoke("--workspace", str(root), "--json", "rebuild")
    assert code == 3
    assert "Workspace does not exist" in str(_error(payload)["message"])
    assert not root.exists()


def test_rebuild_json_carries_the_schema_version(repository: WorkspaceRepository) -> None:
    commands.init_project(repository, name="P", brief="b")
    code, payload = _invoke("--workspace", str(repository.root), "--json", "rebuild")
    assert code == 0
    assert payload["schema_version"] == 2
    assert payload["result"] == "ok"


def test_failed_write_does_not_leave_an_empty_workspace(tmp_path: Path) -> None:
    root = tmp_path / "parent" / "workspace"
    note = tmp_path / "note.md"
    note.write_text("hello", encoding="utf-8")
    code, payload = _invoke(
        "--workspace",
        str(root),
        "--json",
        "--actor",
        "agent-1",
        "note",
        "write",
        "--file",
        str(note),
    )
    assert code == 3
    assert _error(payload)["message"] == "Project does not exist"
    assert not (tmp_path / "parent").exists()


def test_unknown_session_close_is_an_entity_error(repository: WorkspaceRepository) -> None:
    commands.init_project(repository, name="P", brief="b")
    code, payload = _invoke(
        "--workspace",
        str(repository.root),
        "--json",
        "--actor",
        "agent-1",
        "project",
        "session",
        "close",
        "ps_missing",
    )
    assert code == 3
    assert _error(payload)["code"] == "entity_not_found"


def test_human_can_close_the_session_they_created_from_the_cli(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]
) -> None:
    commands.init_project(
        repository, name="P", brief="b", material_paths=(wav_file("s.wav", 220.0),)
    )
    proposed = persist_finite_variant(repository, label="Proposal", same_as_source=False)
    workspace = ["--workspace", str(repository.root)]
    runner = CliRunner()
    created = runner.invoke(
        app,
        [
            *workspace,
            "project",
            "session",
            "create",
            "--a",
            "source",
            "--b",
            proposed,
            "--focus",
            "f",
        ],
    )
    assert created.exit_code == 0, created.output
    project_session = next(iter(repository.state().research.project_sessions.values()))
    assert project_session.created_by_id == "human"

    closed = runner.invoke(app, [*workspace, "project", "session", "close", project_session.id])

    assert closed.exit_code == 0, closed.output
    runtime = repository.state().compare.session_runtime[project_session.core_session_id]
    assert runtime.status == "closed"


def test_invalid_input_files_are_reported_without_a_traceback(
    repository: WorkspaceRepository, tmp_path: Path
) -> None:
    commands.init_project(repository, name="P", brief="b")
    agent = ["--workspace", str(repository.root), "--json", "--actor", "agent-1"]
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps([{"indicator_id": "x"}]), encoding="utf-8")
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    for arguments in (
        ["variant", "add", "--manifest", str(broken)],
        ["variant", "add", "--bundle", str(bundle), "--entry", "missing.sh"],
        ["indicator", "value", "record", "--batch", str(batch)],
    ):
        code, payload = _invoke(*agent, *arguments)
        assert code == 3, arguments
        assert _error(payload)["message"], arguments
