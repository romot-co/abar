"""Trusted Variant rendering with deterministic first-run observation."""

import contextlib
import hashlib
import os
import platform
import signal
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from abar.compare.audio.content import InvalidAudioObjectError, decode_wav_bytes
from abar.compare.audio.importing import import_decoded_audio
from abar.compare.manifests import VariantManifest
from abar.compare.models import AudioObject, Material, Variant
from abar.foundation.canonical_json import canonical_json_bytes, canonical_sha256
from abar.foundation.json_types import JSONValue
from abar.foundation.object_store import ObjectStore


class RenderViolation(ValueError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True, slots=True)
class RenderOutcome:
    audio: AudioObject
    material_id: str
    runtime_fingerprint: str
    raw_render_id: str
    invocation_identity: str
    nondeterministic_hashes: tuple[str, str] | None = None


def runtime_fingerprint() -> str:
    return canonical_sha256(
        {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        }
    )


def render_variant(
    variant: Variant,
    manifest: VariantManifest,
    material: Material,
    source_audio: AudioObject,
    *,
    objects: ObjectStore,
    runtime: str | None = None,
    seed: int = 0,
) -> RenderOutcome:
    selected_runtime = runtime or runtime_fingerprint()
    renderer = manifest.renderer
    if renderer.kind == "finite_map":
        assert renderer.finite_map is not None
        entry = renderer.finite_map.get(material.id)
        if entry is None:
            raise RenderViolation("finite_map_missing_material")
        raise RenderViolation(
            "finite_map_requires_projection_resolution",
            "finite_map AudioObject must be resolved by the operand service",
        )
    command = renderer.command
    assert command is not None
    archive = objects.read(manifest.source_archive.object_id)
    input_bytes = objects.read(source_audio.object_id)
    invocation_document: dict[str, JSONValue] = {
        "argv": list(command.argv),
        "env": {name: value for name, value in command.env.items()},
        "cwd": command.cwd,
        "executable_sha": command.executable_sha,
        "input_audio_id": source_audio.id,
        "resolved_params": variant.resolved_params,
    }
    invocation = canonical_sha256(invocation_document)
    outputs: list[bytes] = []
    for _ in range(2):
        outputs.append(
            _execute_command(
                archive,
                command.argv,
                cwd=command.cwd,
                env=command.env,
                executable_sha=command.executable_sha,
                timeout_seconds=command.timeout_seconds,
                input_bytes=input_bytes,
                params=canonical_json_bytes(variant.resolved_params),
                seed=seed if command.seed_mode == "required" else None,
            )
        )
    first_hash = f"sha256:{hashlib.sha256(outputs[0]).hexdigest()}"
    second_hash = f"sha256:{hashlib.sha256(outputs[1]).hexdigest()}"
    nondeterministic = None if first_hash == second_hash else (first_hash, second_hash)
    try:
        decoded = decode_wav_bytes(outputs[0])
    except InvalidAudioObjectError as error:
        raise RenderViolation("render_failed", f"renderer output is invalid: {error}") from error
    if decoded.channel_layout not in manifest.output_contract.channel_layouts:
        raise RenderViolation("unsupported_channel_layout")
    if decoded.sample_rate != source_audio.sample_rate or decoded.frames != source_audio.frames:
        raise RenderViolation(
            "render_timeline_mismatch",
            "renderer output must preserve source sample rate and frame extent",
        )
    # Store only a validated output so a rejected render leaves no orphan object.
    audio = import_decoded_audio(decoded, objects=objects)
    raw_identity: dict[str, JSONValue] = {
        "variant_id": variant.id,
        "material_id": material.id,
        "source_audio_id": source_audio.id,
        "context_policy": renderer.context_policy,
        "timeline_policy": renderer.timeline_policy,
        "invocation_identity": invocation,
        "runtime": selected_runtime,
        "seed": seed if command.seed_mode == "required" else None,
    }
    raw_id = f"render_{canonical_sha256(raw_identity)}"
    return RenderOutcome(
        audio=audio,
        material_id=material.id,
        runtime_fingerprint=selected_runtime,
        raw_render_id=raw_id,
        invocation_identity=invocation,
        nondeterministic_hashes=nondeterministic,
    )


def _execute_command(
    archive: bytes,
    argv_template: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    executable_sha: str,
    timeout_seconds: int,
    input_bytes: bytes,
    params: bytes,
    seed: int | None,
) -> bytes:
    with tempfile.TemporaryDirectory(prefix="abar-render-") as temporary:
        root = Path(temporary)
        bundle = root / "bundle"
        bundle.mkdir()
        _extract_archive(archive, bundle)
        input_path = root / "input.wav"
        params_path = root / "params.json"
        output_path = root / "output.wav"
        input_path.write_bytes(input_bytes)
        params_path.write_bytes(params)
        executable = (bundle / argv_template[0]).resolve()
        if not executable.is_relative_to(bundle.resolve()) or not executable.is_file():
            raise RenderViolation("render_failed", "renderer executable is missing")
        digest = f"sha256:{hashlib.sha256(executable.read_bytes()).hexdigest()}"
        if digest != executable_sha:
            raise RenderViolation("render_failed", "renderer executable hash mismatch")
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        replacements = {
            "{input_wav}": str(input_path),
            "{params_json}": str(params_path),
            "{output_wav}": str(output_path),
            "{seed}": "0" if seed is None else str(seed),
        }
        argv: list[str] = []
        for value in argv_template:
            for placeholder, replacement in replacements.items():
                value = value.replace(placeholder, replacement)
            argv.append(str(executable) if not argv else value)
        process_env = {
            "HOME": str(root / "home"),
            "TMPDIR": str(root / "tmp"),
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            **env,
        }
        Path(process_env["HOME"]).mkdir()
        Path(process_env["TMPDIR"]).mkdir()
        workdir = (bundle / cwd).resolve()
        if not workdir.is_relative_to(bundle.resolve()) or not workdir.is_dir():
            raise RenderViolation("render_failed", "renderer cwd is invalid")
        _run_renderer(argv, cwd=workdir, env=process_env, timeout_seconds=timeout_seconds)
        if not output_path.is_file():
            raise RenderViolation("render_failed", "renderer produced no output")
        return output_path.read_bytes()


def _run_renderer(argv: list[str], *, cwd: Path, env: dict[str, str], timeout_seconds: int) -> None:
    """Run the renderer in its own session and never leave its process group behind.

    ``subprocess.run(timeout=...)`` kills only the direct child, so helpers the
    renderer spawned would keep running (and holding the output pipes) forever.
    """

    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RenderViolation("render_failed", str(error)) from error
    try:
        _stdout, stderr = process.communicate(timeout=timeout_seconds)
    except BaseException as error:
        # Signal the group only while its leader is unreaped, so the group ID
        # cannot have been recycled, then reap the leader.
        if process.returncode is None:
            _kill_process_group(process.pid)
            process.communicate()
        if isinstance(error, subprocess.TimeoutExpired):
            raise RenderViolation(
                "render_failed", f"renderer timed out after {timeout_seconds} s"
            ) from error
        raise
    if process.returncode != 0:
        detail = (stderr or b"")[-4096:].decode("utf-8", errors="replace")
        raise RenderViolation("render_failed", f"renderer exited {process.returncode}: {detail}")


def _kill_process_group(process_group_id: int) -> None:
    # Already gone raises ESRCH; macOS reports EPERM for a group of only zombies.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process_group_id, signal.SIGKILL)


def _extract_archive(data: bytes, destination: Path) -> None:
    archive_path = destination.parent / "bundle.zip"
    archive_path.write_bytes(data)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            if len(infos) > 10_000 or sum(item.file_size for item in infos) > 256 * 1024 * 1024:
                raise RenderViolation("render_failed", "renderer archive is too large")
            for info in infos:
                path = PurePosixPath(info.filename)
                mode = info.external_attr >> 16
                if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(mode):
                    raise RenderViolation("render_failed", "unsafe renderer archive member")
                target = destination.joinpath(*path.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(info))
                    target.chmod(0o755 if mode & 0o111 else 0o644)
    except zipfile.BadZipFile as error:
        raise RenderViolation("render_failed", "source archive must be ZIP") from error
