import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from typer.testing import CliRunner

from abar.app import commands
from abar.app.actors import Actor
from abar.app.repository import WorkspaceRepository
from abar.cli import app
from abar.compare import rendering
from abar.compare.bundles import build_command_bundle
from tests.conftest import persist_finite_variant


def test_materialization_persists_exact_audio_without_changing_project_authority(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    tmp_path: Path,
) -> None:
    commands.init_project(
        repository,
        name="Product",
        brief="Improve the sound",
        material_paths=(wav_file("source.wav", 220.0),),
    )
    variant_id = persist_finite_variant(repository, label="proposal", same_as_source=False)
    project_before = repository.state().project.project
    assert project_before is not None
    clip_id = repository.state().compare.materials[project_before.material_ids[0]].clip_ids[0]

    result = commands.materialize_variant(
        repository,
        variant_id,
        clip_ids=(clip_id,),
        output=tmp_path / "measurements",
        idempotency_key="materialize-proposal",
    )

    assert result.variant_id == variant_id
    assert len(result.items) == 1
    item = result.items[0]
    state = repository.state()
    audio = state.compare.audio[item.audio_id]
    assert Path(item.output).read_bytes() == repository.objects.read(audio.object_id)
    assert item.pcm_sha == audio.pcm_sha
    assert state.project.project == project_before
    assert not any(event.event_type == "in_use.recorded" for event in repository.events.read_all())
    assert any(event.event_type == "variant.materialized" for event in repository.events.read_all())

    definition = tmp_path / "indicator.md"
    definition.write_text("mean absolute amplitude", encoding="utf-8")
    commands.register_indicator(
        repository,
        indicator_id="ind_amplitude_v1",
        label="Amplitude",
        description="External amplitude observation",
        definition_path=definition,
        subject_kind="audio",
        unit="ratio",
        actor_id="test-agent",
    )
    commands.record_indicator_value(
        repository,
        indicator_id="ind_amplitude_v1",
        subject_id=item.audio_id,
        variant_id=variant_id,
        value=0.25,
        actor=Actor("test-agent", "agent"),
    )


def test_materialization_retry_restores_output_and_rejects_a_different_request(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    tmp_path: Path,
) -> None:
    commands.init_project(
        repository,
        name="Product",
        brief="Improve the sound",
        material_paths=(wav_file("source.wav", 220.0),),
    )
    variant_id = persist_finite_variant(repository, label="proposal", same_as_source=True)
    project = repository.state().project.project
    assert project is not None
    clip_id = repository.state().compare.materials[project.material_ids[0]].clip_ids[0]
    output = tmp_path / "measurements"
    key = "materialize-proposal"
    first = commands.materialize_variant(
        repository,
        variant_id,
        clip_ids=(clip_id,),
        output=output,
        idempotency_key=key,
    )
    event_count = len(tuple(repository.events.read_all()))
    Path(first.items[0].output).unlink()

    retried = commands.materialize_variant(
        repository,
        variant_id,
        clip_ids=(clip_id,),
        output=output,
        idempotency_key=key,
    )

    assert retried == first
    assert Path(retried.items[0].output).is_file()
    assert len(tuple(repository.events.read_all())) == event_count
    with pytest.raises(commands.CommandError) as raised:
        commands.materialize_variant(
            repository,
            "source",
            clip_ids=(clip_id,),
            output=output,
            idempotency_key=key,
        )
    assert raised.value.code == "idempotency_conflict"


def test_agent_cli_materializes_multiple_clips_but_cannot_project_export(
    tmp_path: Path,
    wav_file: Callable[[str, float], Path],
) -> None:
    workspace = tmp_path / "workspace"
    repository = WorkspaceRepository.open(workspace)
    try:
        commands.init_project(
            repository,
            name="Product",
            brief="Improve the sound",
            material_paths=(wav_file("source.wav", 220.0),),
        )
        project = repository.state().project.project
        assert project is not None
        material_id = project.material_ids[0]
        first_clip = repository.state().compare.materials[material_id].clip_ids[0]
        second_clip = commands.add_clip(
            repository,
            material_id,
            start_seconds=1.0,
            duration_seconds=1.0,
        )
        variant_id = persist_finite_variant(repository, label="proposal", same_as_source=False)
    finally:
        repository.close()

    materialized = CliRunner().invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "--json",
            "--actor",
            "test-agent",
            "--idempotency-key",
            "materialize-two-clips",
            "variant",
            "materialize",
            variant_id,
            "--clip",
            first_clip,
            "--clip",
            second_clip,
            "--output",
            str(tmp_path / "measurements"),
        ],
    )

    assert materialized.exit_code == 0, materialized.output
    payload = json.loads(materialized.stdout)
    assert payload["variant_id"] == variant_id
    assert [item["clip_id"] for item in payload["items"]] == [first_clip, second_clip]
    assert all(Path(item["output"]).is_file() for item in payload["items"])

    rejected = CliRunner().invoke(
        app,
        [
            "--workspace",
            str(workspace),
            "--json",
            "--actor",
            "test-agent",
            "project",
            "export",
            variant_id,
            "--output",
            str(tmp_path / "release.json"),
        ],
    )
    assert rejected.exit_code != 0
    assert "human interaction path" in rejected.stderr


def test_materialization_renders_one_full_material_for_multiple_clips(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands.init_project(
        repository,
        name="Product",
        brief="Improve the sound",
        material_paths=(wav_file("source.wav", 220.0),),
    )
    project = repository.state().project.project
    assert project is not None
    material_id = project.material_ids[0]
    first_clip = repository.state().compare.materials[material_id].clip_ids[0]
    second_clip = commands.add_clip(
        repository,
        material_id,
        start_seconds=1.0,
        duration_seconds=1.0,
    )
    bundle_root = tmp_path / "renderer"
    bundle_root.mkdir()
    entry = bundle_root / "render.sh"
    entry.write_text('#!/bin/sh\ncp "$1" "$3"\n', encoding="utf-8")
    built = build_command_bundle(bundle_root, entry.name)
    variant_id = commands.add_variant_archive(
        repository,
        built.manifest,
        built.archive,
        label="copy renderer",
    )
    executions = 0
    execute = cast(
        Callable[..., bytes],
        rendering._execute_command,  # pyright: ignore[reportPrivateUsage]
    )

    def counted_execute(*args: object, **kwargs: object) -> bytes:
        nonlocal executions
        executions += 1
        return execute(*args, **kwargs)

    monkeypatch.setattr(rendering, "_execute_command", counted_execute)

    result = commands.materialize_variant(
        repository,
        variant_id,
        clip_ids=(first_clip, second_clip),
        output=tmp_path / "measurements",
    )

    assert len(result.items) == 2
    assert executions == 2
    assert (
        sum(event.event_type == "render.completed" for event in repository.events.read_all()) == 1
    )
