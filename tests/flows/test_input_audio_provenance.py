import io
from pathlib import Path

import numpy as np
import soundfile as sf  # pyright: ignore[reportMissingTypeStubs]

from abar.app import commands
from abar.app.repository import WorkspaceRepository
from abar.compare.models import RecipeRef


def test_import_event_records_original_format_and_decoder(
    repository: WorkspaceRepository,
) -> None:
    path = _write_input(repository, "source.mp3", "MP3", "MPEG_LAYER_III", 220.0)

    audio_id = commands.import_audio(repository, path)

    event = next(
        item
        for item in reversed(repository.events.read_all())
        if item.event_type == "audio.imported"
    )
    source = event.payload["input_source"]
    assert isinstance(source, dict)
    assert source["container"] == "MP3"
    assert source["subtype"] == "MPEG_LAYER_III"
    assert source["decoder"] == "libsndfile"
    assert str(source["original_sha"]).startswith("sha256:")
    assert repository.state().compare.audio[audio_id].object_id.startswith("obj_")


def test_quick_listen_accepts_different_external_containers(
    repository: WorkspaceRepository,
) -> None:
    first = _write_input(repository, "first.mp3", "MP3", "MPEG_LAYER_III", 220.0)
    second = _write_input(repository, "second.flac", "FLAC", "PCM_24", 330.0)

    session_id = commands.create_quick_listen(
        repository,
        str(first),
        str(second),
        recipe=RecipeRef("native"),
        presentation="open",
    )

    state = repository.state()
    assert state.compare.sessions[session_id].items
    imported = [
        event.payload["input_source"]
        for event in repository.events.read_all()
        if event.event_type == "audio.imported" and "input_source" in event.payload
    ]
    assert {str(item["container"]) for item in imported if isinstance(item, dict)} == {
        "MP3",
        "FLAC",
    }


def _write_input(
    repository: WorkspaceRepository,
    name: str,
    container: str,
    subtype: str,
    frequency: float,
) -> Path:
    time = np.arange(48_000, dtype=np.float32) / 8_000
    pcm = (0.2 * np.sin(2.0 * np.pi * frequency * time)).reshape(-1, 1)
    stream = io.BytesIO()
    sf.write(stream, pcm, 8_000, format=container, subtype=subtype)
    path = repository.root / name
    path.write_bytes(stream.getvalue())
    return path
