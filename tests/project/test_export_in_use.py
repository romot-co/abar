from collections.abc import Callable
from pathlib import Path

import pytest

from abar.app import commands
from abar.app.actors import Actor
from abar.app.repository import WorkspaceRepository
from tests.conftest import persist_finite_variant


def test_export_records_in_use_only_after_file_is_written(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    tmp_path: Path,
) -> None:
    commands.init_project(
        repository,
        name="Product",
        brief="brief",
        material_paths=(wav_file("source.wav", 220.0),),
    )
    variant = persist_finite_variant(repository, label="release", same_as_source=True)
    output = tmp_path / "release.json"
    commands.export_project(repository, variant, output=output, actor=Actor("human", "human"))
    assert output.is_file()
    assert repository.state().project.project.in_use_variant_id == variant  # type: ignore[union-attr]


def test_export_retry_rejects_a_different_request(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    tmp_path: Path,
) -> None:
    commands.init_project(
        repository,
        name="Product",
        brief="brief",
        material_paths=(wav_file("source.wav", 220.0),),
    )
    variant = persist_finite_variant(repository, label="release", same_as_source=True)
    key = "export-release"
    commands.export_project(
        repository,
        variant,
        output=tmp_path / "release.json",
        actor=Actor("human", "human"),
        idempotency_key=key,
    )
    with pytest.raises(commands.CommandError) as raised:
        commands.export_project(
            repository,
            variant,
            output=tmp_path / "other.json",
            actor=Actor("human", "human"),
            idempotency_key=key,
        )
    assert raised.value.code == "idempotency_conflict"


def test_export_with_clips_persists_audio_effects_with_the_in_use_event(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    tmp_path: Path,
) -> None:
    commands.init_project(
        repository,
        name="Product",
        brief="brief",
        material_paths=(wav_file("source.wav", 220.0),),
    )
    variant = persist_finite_variant(repository, label="release", same_as_source=False)
    result = commands.export_project(
        repository,
        variant,
        output=tmp_path / "release.json",
        actor=Actor("human", "human"),
        render_clips=tmp_path / "clips",
        idempotency_key="export-clips",
    )

    assert result.rendered_files
    operation = repository.events.read_operation("export-clips")
    assert [event.event_type for event in operation][-1] == "in_use.recorded"
    persisted = {
        str(event.payload["audio_id"])
        for event in operation
        if event.event_type in {"audio.slice.created", "render.completed"}
    }
    state = repository.state()
    assert persisted
    assert persisted <= set(state.compare.audio)
