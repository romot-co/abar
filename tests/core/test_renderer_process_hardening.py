import hashlib
import io
import os
import subprocess
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf  # pyright: ignore[reportMissingTypeStubs]

from abar.compare import rendering
from abar.compare.audio.content import decode_wav_bytes, encode_float32_wav
from abar.compare.audio.importing import import_input_audio_file
from abar.compare.manifests import VariantManifest
from abar.compare.models import AudioObject, Material, Variant
from abar.infrastructure.object_store import ImmutableObjectStore


def _archive(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return stream.getvalue()


def _sha(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _wavex(pcm: np.ndarray, sample_rate: int) -> bytes:
    stream = io.BytesIO()
    sf.write(stream, pcm, sample_rate, format="WAVEX", subtype="FLOAT")
    return stream.getvalue()


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _command_render(
    objects: ImmutableObjectStore,
    source: AudioObject,
    files: dict[str, bytes],
    *,
    channel_layouts: list[str],
) -> rendering.RenderOutcome:
    executable = files["render.sh"]
    archive = objects.put(_archive(files))
    manifest = VariantManifest.model_validate(
        {
            "schema_version": 1,
            "source_archive": {"object_id": archive.object_id, "sha": f"sha256:{archive.sha256}"},
            "renderer": {
                "kind": "command",
                "context_policy": "full_material",
                "timeline_policy": "source_aligned_exact_v1",
                "command": {
                    "argv": ["render.sh", "{input_wav}", "{params_json}", "{output_wav}"],
                    "executable_sha": _sha(executable),
                },
            },
            "input_contract": {"audio": "canonical_wav", "params": "canonical_json"},
            "output_contract": {
                "container": "wav",
                "sample_rates": "source",
                "channel_layouts": channel_layouts,
            },
        }
    )
    material = Material("material_1", "material.wav", source.id)
    variant = Variant("variant_1", "test", manifest.id, {}, "renderable")
    return rendering.render_variant(
        variant, manifest, material, source, objects=objects, runtime="test-runtime"
    )


def _stored_objects(objects_root: Path) -> set[Path]:
    return {path for path in objects_root.rglob("*") if path.is_file()}


def test_renderer_timeout_kills_helpers_it_spawned(tmp_path: Path) -> None:
    pid_file = tmp_path / "helper.pid"
    executable = b'#!/bin/sh\nsleep 30 &\necho $! > "$PID_FILE"\nsleep 30\n'

    started = time.monotonic()
    with pytest.raises(rendering.RenderViolation, match="timed out"):
        rendering._execute_command(  # pyright: ignore[reportPrivateUsage]
            _archive({"render.sh": executable}),
            ["render.sh", "{input_wav}", "{params_json}", "{output_wav}"],
            cwd=".",
            env={"PID_FILE": str(pid_file)},
            executable_sha=_sha(executable),
            timeout_seconds=1,
            input_bytes=b"input",
            params=b"{}",
            seed=None,
        )

    # The helper held the output pipes; without killing the group this blocks ~30 s.
    assert time.monotonic() - started < 10
    helper = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while _process_exists(helper) and time.monotonic() < deadline:
        time.sleep(0.05)  # an orphaned zombie is reaped by init shortly after SIGKILL
    assert not _process_exists(helper)


def test_renderer_failure_runs_once_and_reports_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    executable = b"#!/bin/sh\necho broken >&2\nexit 7\n"
    launches = 0
    original = subprocess.Popen

    def counted(*args: object, **kwargs: object) -> object:
        nonlocal launches
        launches += 1
        assert kwargs.get("start_new_session") is True
        return original(*args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(rendering.subprocess, "Popen", counted)
    with pytest.raises(rendering.RenderViolation, match="exited 7: broken"):
        rendering._execute_command(  # pyright: ignore[reportPrivateUsage]
            _archive({"render.sh": executable}),
            ["render.sh", "{input_wav}", "{params_json}", "{output_wav}"],
            cwd=".",
            env={},
            executable_sha=_sha(executable),
            timeout_seconds=5,
            input_bytes=b"input",
            params=b"{}",
            seed=None,
        )
    assert launches == 1


def test_wavex_container_is_accepted_as_core_wav() -> None:
    pcm = (0.1 * np.sin(np.arange(800, dtype=np.float32) / 7.0)).reshape(-1, 1)

    decoded = decode_wav_bytes(_wavex(pcm, 8_000))

    assert decoded.sample_rate == 8_000
    assert decoded.channel_layout == "mono"
    assert np.array_equal(decoded.pcm, decode_wav_bytes(encode_float32_wav(pcm, 8_000)).pcm)


def test_command_renderer_may_emit_wavex(
    tmp_path: Path, wav_file: Callable[[str, float], Path]
) -> None:
    objects = ImmutableObjectStore(tmp_path / "objects")
    source = import_input_audio_file(wav_file("material.wav", 220.0), objects=objects).audio
    decoded = decode_wav_bytes(objects.read(source.object_id))
    executable = b'#!/bin/sh\ncp out.wav "$3"\n'

    outcome = _command_render(
        objects,
        source,
        {"render.sh": executable, "out.wav": _wavex(decoded.pcm, decoded.sample_rate)},
        channel_layouts=["mono"],
    )

    # Stored in the canonical WAV form: same content identity as the source PCM.
    assert outcome.audio.id == source.id
    assert decode_wav_bytes(objects.read(outcome.audio.object_id)).frames == source.frames


@pytest.mark.parametrize("violation", ["unsupported_channel_layout", "render_timeline_mismatch"])
def test_rejected_render_output_is_not_stored(
    tmp_path: Path, wav_file: Callable[[str, float], Path], violation: str
) -> None:
    objects = ImmutableObjectStore(tmp_path / "objects")
    source = import_input_audio_file(wav_file("material.wav", 220.0), objects=objects).audio
    decoded = decode_wav_bytes(objects.read(source.object_id))
    if violation == "unsupported_channel_layout":
        output = encode_float32_wav(np.repeat(decoded.pcm, 2, axis=1) * 0.5, decoded.sample_rate)
    else:
        output = encode_float32_wav(decoded.pcm[:-10] * 0.5, decoded.sample_rate)
    executable = b'#!/bin/sh\ncp out.wav "$3"\n'
    files = {"render.sh": executable, "out.wav": output}
    objects.put(_archive(files))
    before = _stored_objects(tmp_path / "objects")

    with pytest.raises(rendering.RenderViolation) as raised:
        _command_render(objects, source, files, channel_layouts=["mono"])

    assert raised.value.code == violation
    assert _stored_objects(tmp_path / "objects") == before
