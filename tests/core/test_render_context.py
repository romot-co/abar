import hashlib
import io
import subprocess
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from abar.compare import rendering
from abar.compare.audio.importing import import_input_audio_file
from abar.compare.manifests import VariantManifest
from abar.compare.models import AudioObject, Clip, Material, Variant
from abar.compare.operands import resolve_operand
from abar.compare.projection import CompareState
from abar.infrastructure.object_store import ImmutableObjectStore


def test_command_variant_renders_full_material_once_before_slicing_clips(
    tmp_path: Path,
    wav_file: Callable[[str, float], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    objects = ImmutableObjectStore(tmp_path / "objects")
    source = import_input_audio_file(wav_file("material.wav", 220.0), objects=objects).audio
    first_clip = Clip("clip_first", "material_1", 8_000, 8_000)
    second_clip = Clip("clip_second", "material_1", 24_000, 8_000)
    material = Material(
        "material_1",
        "material.wav",
        source.id,
        clip_ids=(first_clip.id, second_clip.id),
    )
    executable = b'#!/bin/sh\ncp "$1" "$3"\n'
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("render.sh", executable)
    archive_ref = objects.put(archive_bytes.getvalue())
    manifest = VariantManifest.model_validate(
        {
            "schema_version": 1,
            "source_archive": {
                "object_id": archive_ref.object_id,
                "sha": f"sha256:{archive_ref.sha256}",
            },
            "renderer": {
                "kind": "command",
                "context_policy": "full_material",
                "timeline_policy": "source_aligned_exact_v1",
                "command": {
                    "argv": [
                        "render.sh",
                        "{input_wav}",
                        "{params_json}",
                        "{output_wav}",
                    ],
                    "executable_sha": f"sha256:{hashlib.sha256(executable).hexdigest()}",
                },
            },
            "input_contract": {"audio": "canonical_wav", "params": "canonical_json"},
            "output_contract": {
                "container": "wav",
                "sample_rates": "source",
                "channel_layouts": ["mono"],
            },
        }
    )
    variant = Variant("variant_1", "test", manifest.id, {}, "renderable")
    state = CompareState(
        audio={source.id: source},
        materials={material.id: material},
        clips={first_clip.id: first_clip, second_clip.id: second_clip},
        variants={variant.id: variant},
        manifests={manifest.id: manifest.document()},
    )
    render_cache: dict[str, AudioObject] = {}
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

    first = resolve_operand(
        f"variant:{variant.id}#{first_clip.id}",
        input_key="p1",
        state=state,
        objects=objects,
        runtime="test-runtime",
        render_cache=render_cache,
    )
    second = resolve_operand(
        f"variant:{variant.id}#{second_clip.id}",
        input_key="p2",
        state=state,
        objects=objects,
        runtime="test-runtime",
        render_cache=render_cache,
    )

    assert [effect.kind for effect in first.effects] == ["render", "slice"]
    assert first.effects[0].audio.frames == source.frames
    assert first.effects[0].render is not None
    assert first.effects[0].render.material_id == material.id
    assert first.audio.frames == first_clip.frames
    assert [effect.kind for effect in second.effects] == ["slice"]
    assert second.audio.frames == second_clip.frames
    assert len(render_cache) == 1
    assert executions == 2


def test_renderer_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    executable = b"#!/bin/sh\nexit 1\n"
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("render.sh", executable)
    calls = 0

    def fail(*_args: object, **_kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise subprocess.CalledProcessError(1, ["render.sh"])

    monkeypatch.setattr(rendering.subprocess, "run", fail)
    with pytest.raises(rendering.RenderViolation):
        rendering._execute_command(  # pyright: ignore[reportPrivateUsage]
            archive_bytes.getvalue(),
            ["render.sh", "{input_wav}", "{params_json}", "{output_wav}"],
            cwd=".",
            env={},
            executable_sha=f"sha256:{hashlib.sha256(executable).hexdigest()}",
            timeout_seconds=1,
            input_bytes=b"input",
            params=b"{}",
            seed=None,
        )
    assert calls == 1
