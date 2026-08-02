import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from abar.app import commands
from abar.app.events import draft
from abar.app.queries import status
from abar.app.repository import WorkspaceRepository
from abar.cli import app
from abar.server.request_models import ObservationSessionRequest
from tests.conftest import persist_finite_variant


def test_project_init_names_existing_material_option_explicitly() -> None:
    result = CliRunner().invoke(app, ["project", "init", "--help"])

    assert result.exit_code == 0
    assert "--existing-material" in result.stdout
    assert "--material-id" not in result.stdout


def test_project_init_unknown_existing_material_explains_file_import(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "--workspace",
            str(tmp_path / "workspace"),
            "--json",
            "project",
            "init",
            "--name",
            "Project",
            "--brief",
            "Improve the sound",
            "--existing-material",
            "missing",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "unknown_existing_material"
    assert "use --material to import a file" in payload["error"]["message"]


def test_material_add_accepts_multiple_files_and_returns_clip_ids(
    tmp_path: Path,
    wav_file: Callable[[str, float], Path],
) -> None:
    workspace = tmp_path / "batch-workspace"
    repository = WorkspaceRepository.open(workspace)
    try:
        commands.init_project(repository, name="Project", brief="Improve the sound")
    finally:
        repository.close()
    first = wav_file("batch-one.wav", 220.0)
    second = wav_file("batch-two.wav", 330.0)

    result = CliRunner().invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "--json",
            "--actor",
            "test-agent",
            "--idempotency-key",
            "batch-materials",
            "material",
            "add",
            str(first),
            str(second),
            "--source-group",
            "corpus",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload["result"]) == 2
    assert all(item["clip_ids"] for item in payload["result"])


def test_session_create_help_explains_variable_and_repeatable_evidence() -> None:
    result = CliRunner().invoke(app, ["project", "session", "create", "--help"])

    assert result.exit_code == 0
    assert "default 3, minimum 3" in result.stdout
    assert "Evidence Clip ID; repeat" in result.stdout
    assert "once per comparison" in result.stdout


def test_observation_request_rejects_evidence_count_that_does_not_match_size() -> None:
    with pytest.raises(ValidationError):
        ObservationSessionRequest(
            first_variant="source",
            second_variant="v_example",
            focus="Check the sound",
            size="standard",
            evidence_count=2,
        )
    with pytest.raises(ValidationError):
        ObservationSessionRequest(
            first_variant="source",
            second_variant="v_example",
            focus="Check the sound",
            size="short",
            evidence_count=3,
        )


def test_status_describes_the_event_that_degraded_a_workspace(
    repository: WorkspaceRepository,
) -> None:
    repository.events.append(
        draft(
            "legacy.unsupported",
            {},
            idempotency_key="unknown-event",
        )
    )

    view = status(repository)

    assert view.health.status == "degraded"
    assert view.health.degradation is not None
    assert view.health.degradation.event_seq == 1
    assert view.health.degradation.event_type == "legacy.unsupported"
    assert view.health.degradation.schema_version == 1
    assert "create a new Workspace" in view.health.degradation.recovery


def test_session_create_streams_json_progress_to_stderr(
    tmp_path: Path,
    wav_file: Callable[[str, float], Path],
) -> None:
    workspace = tmp_path / "progress-workspace"
    repository = WorkspaceRepository.open(workspace)
    try:
        commands.init_project(
            repository,
            name="Project",
            brief="Improve the sound",
            material_paths=(wav_file("progress.wav", 220.0),),
        )
        variant_id = persist_finite_variant(
            repository,
            label="Proposal",
            same_as_source=False,
        )
    finally:
        repository.close()

    result = CliRunner().invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "--json",
            "--actor",
            "test-agent",
            "project",
            "session",
            "create",
            "--a",
            "source",
            "--b",
            variant_id,
            "--focus",
            "Check the proposal",
            "--recipe",
            "native",
        ],
    )

    assert result.exit_code == 0, result.output
    progress = [json.loads(line) for line in result.stderr.splitlines()]
    assert [item["stage"] for item in progress] == ["started", "completed"]
    assert all(item["type"] == "session_preparation_progress" for item in progress)
