"""Deterministic packaging and static validation for command renderer bundles."""

import hashlib
import io
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from abar.compare.manifests import CommandRenderer
from abar.foundation.json_types import JSONValue

_MAX_FILES = 10_000
_MAX_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BuiltCommandBundle:
    archive: bytes
    manifest: dict[str, JSONValue]


def build_command_bundle(
    root: Path,
    entry: str,
    *,
    timeout_seconds: int = 120,
    seed_mode: str = "none",
) -> BuiltCommandBundle:
    selected_root = root.expanduser().resolve()
    if not selected_root.is_dir():
        raise ValueError("renderer bundle must be a directory")
    entry_path = PurePosixPath(entry)
    if entry_path.is_absolute() or ".." in entry_path.parts or entry in {"", "."}:
        raise ValueError("renderer entry must be a bundle-relative file")

    files = sorted((item for item in selected_root.rglob("*") if item.is_file()), key=str)
    if any(item.is_symlink() for item in selected_root.rglob("*")):
        raise ValueError("renderer bundle may not contain symbolic links")
    if not files or len(files) > _MAX_FILES:
        raise ValueError("renderer bundle has an invalid file count")
    total_bytes = sum(item.stat().st_size for item in files)
    if total_bytes > _MAX_BYTES:
        raise ValueError("renderer bundle is too large")

    relative_files = {item.relative_to(selected_root).as_posix(): item for item in files}
    executable = relative_files.get(entry_path.as_posix())
    if executable is None:
        raise ValueError("renderer entry does not exist in the bundle")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, path in relative_files.items():
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if relative == entry_path.as_posix() else 0o644) << 16
            archive.writestr(info, path.read_bytes())

    argv = [entry_path.as_posix(), "{input_wav}", "{params_json}", "{output_wav}"]
    if seed_mode == "required":
        argv.append("{seed}")
    executable_sha = f"sha256:{hashlib.sha256(executable.read_bytes()).hexdigest()}"
    manifest = cast(
        dict[str, JSONValue],
        {
            "schema_version": 1,
            "renderer": {
                "kind": "command",
                "context_policy": "full_material",
                "timeline_policy": "source_aligned_exact_v1",
                "command": {
                    "argv": argv,
                    "timeout_seconds": timeout_seconds,
                    "seed_mode": seed_mode,
                    "executable_sha": executable_sha,
                },
            },
            "input_contract": {"audio": "canonical_wav", "params": "canonical_json"},
            "output_contract": {
                "container": "wav",
                "sample_rates": "source",
                "channel_layouts": ["mono", "stereo"],
            },
        },
    )
    return BuiltCommandBundle(buffer.getvalue(), manifest)


def validate_command_archive(data: bytes, command: CommandRenderer) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > _MAX_FILES or sum(item.file_size for item in infos) > _MAX_BYTES:
                raise ValueError("renderer archive is too large")
            members: dict[str, zipfile.ZipInfo] = {}
            for info in infos:
                path = PurePosixPath(info.filename)
                mode = info.external_attr >> 16
                if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(mode):
                    raise ValueError("renderer archive contains an unsafe member")
                name = path.as_posix()
                if name in members:
                    raise ValueError("renderer archive contains duplicate members")
                members[name] = info
            executable = PurePosixPath(command.argv[0]).as_posix()
            info = members.get(executable)
            if info is None or info.is_dir():
                raise ValueError("renderer executable is missing from the archive")
            cwd = PurePosixPath(command.cwd).as_posix().rstrip("/")
            if cwd not in {"", "."} and not any(
                name == cwd or name.startswith(f"{cwd}/") for name in members
            ):
                raise ValueError("renderer cwd is missing from the archive")
            digest = f"sha256:{hashlib.sha256(archive.read(info)).hexdigest()}"
            if digest != command.executable_sha:
                raise ValueError("renderer executable hash mismatch")
    except zipfile.BadZipFile as error:
        raise ValueError("renderer archive must be ZIP") from error
