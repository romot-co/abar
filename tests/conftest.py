from collections.abc import Callable, Generator
from pathlib import Path

import numpy as np
import pytest

from abar.app import commands
from abar.app.events import child_key, draft
from abar.app.repository import WorkspaceRepository
from abar.compare.audio.content import decode_wav_bytes, encode_float32_wav
from abar.compare.audio.importing import import_canonical_wav_bytes
from abar.compare.models import AudioObject
from abar.foundation.json_types import JSONValue


@pytest.fixture
def repository(tmp_path: Path) -> Generator[WorkspaceRepository]:
    value = WorkspaceRepository.open(tmp_path / "workspace")
    yield value
    value.close()


@pytest.fixture
def wav_file(tmp_path: Path) -> Callable[[str, float], Path]:
    def create(name: str, frequency: float) -> Path:
        sample_rate = 8_000
        seconds = 6
        time = np.arange(sample_rate * seconds, dtype=np.float32) / sample_rate
        envelope = np.linspace(0.2, 0.8, len(time), dtype=np.float32)
        pcm = (0.2 * envelope * np.sin(2.0 * np.pi * frequency * time)).reshape(-1, 1)
        path = tmp_path / name
        path.write_bytes(encode_float32_wav(pcm, sample_rate))
        return path

    return create


def persist_finite_variant(
    repository: WorkspaceRepository,
    *,
    label: str,
    same_as_source: bool,
) -> str:
    state = repository.state()
    project = state.project.project
    assert project is not None
    mapping: dict[str, JSONValue] = {}
    audios: list[AudioObject] = []
    for material_id in project.material_ids:
        material = state.compare.materials[material_id]
        source = state.compare.audio[material.source_audio_id]
        audio = source
        if not same_as_source:
            decoded = decode_wav_bytes(repository.objects.read(audio.object_id))
            time = np.arange(decoded.frames, dtype=np.float32) / decoded.sample_rate
            changed = decoded.pcm + 0.01 * np.sin(2.0 * np.pi * 730.0 * time).reshape(-1, 1)
            audio = import_canonical_wav_bytes(
                encode_float32_wav(changed, decoded.sample_rate),
                objects=repository.objects,
            )
        audios.append(audio)
        mapping[material_id] = {
            "audio_object_id": audio.id,
            "audio_sha": audio.pcm_sha,
            "sample_rate": audio.sample_rate,
            "channel_layout": audio.channel_layout,
            "frames": audio.frames,
        }
    key = commands.operation_key()
    with repository.events.transaction(causation_id=key) as tx:
        for index, audio in enumerate(audios):
            tx.append(
                draft(
                    "audio.imported",
                    {
                        "audio_id": audio.id,
                        "object_id": audio.object_id,
                        "pcm_sha": audio.pcm_sha,
                        "sample_rate": audio.sample_rate,
                        "channel_layout": audio.channel_layout,
                        "frames": audio.frames,
                        "provenance_kind": "test_fixture",
                    },
                    idempotency_key=child_key(key, index),
                )
            )
    archive = repository.objects.put(b"finite-map-v2")
    manifest: dict[str, JSONValue] = {
        "schema_version": 1,
        "source_archive": {
            "object_id": archive.object_id,
            "sha": f"sha256:{archive.sha256}",
        },
        "renderer": {
            "kind": "finite_map",
            "context_policy": "full_material",
            "timeline_policy": "source_aligned_exact_v1",
            "command": None,
            "finite_map": mapping,
        },
        "input_contract": {"audio": "canonical_wav", "params": "canonical_json"},
        "output_contract": {
            "container": "wav",
            "sample_rates": "source",
            "channel_layouts": ["mono"],
        },
    }
    return commands.add_variant(repository, manifest, label=label)
