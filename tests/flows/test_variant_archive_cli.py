import hashlib
import json
import zipfile
from pathlib import Path

from typer.testing import CliRunner

from abar.app.repository import WorkspaceRepository
from abar.cli import app
from abar.compare.bundles import build_command_bundle
from abar.compare.manifests import VariantManifest


def test_variant_add_imports_command_renderer_archive(tmp_path: Path) -> None:
    archive = tmp_path / "renderer.zip"
    executable = b"renderer executable"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("renderer", executable)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "renderer": {
                    "kind": "command",
                    "context_policy": "full_material",
                    "timeline_policy": "source_aligned_exact_v1",
                    "command": {
                        "argv": [
                            "renderer",
                            "{input_wav}",
                            "{params_json}",
                            "{output_wav}",
                        ],
                        "executable_sha": ("sha256:" + hashlib.sha256(executable).hexdigest()),
                    },
                },
                "input_contract": {
                    "audio": "canonical_wav",
                    "params": "canonical_json",
                },
                "output_contract": {
                    "container": "wav",
                    "sample_rates": "source",
                    "channel_layouts": ["mono", "stereo"],
                },
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "--workspace",
            str(tmp_path / "workspace"),
            "--json",
            "--actor",
            "test-agent",
            "variant",
            "add",
            "--manifest",
            str(manifest),
            "--archive",
            str(archive),
        ],
    )

    assert result.exit_code == 0, result.output
    repository = WorkspaceRepository.open(tmp_path / "workspace")
    try:
        state = repository.state()
        stored_manifest = next(iter(state.compare.manifests.values()))
    finally:
        repository.close()
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert stored_manifest["source_archive"] == {
        "object_id": f"obj_{digest}",
        "sha": f"sha256:{digest}",
    }


def test_variant_add_builds_standard_command_bundle_without_a_manifest(tmp_path: Path) -> None:
    bundle = tmp_path / "renderer"
    bundle.mkdir()
    executable = bundle / "render.py"
    executable.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    first_build = build_command_bundle(bundle, "render.py")
    assert build_command_bundle(bundle, "render.py") == first_build

    result = CliRunner().invoke(
        app,
        [
            "--workspace",
            str(tmp_path / "workspace"),
            "--json",
            "--actor",
            "test-agent",
            "variant",
            "add",
            "--bundle",
            str(bundle),
            "--entry",
            "render.py",
            "--label",
            "simple renderer",
        ],
    )

    assert result.exit_code == 0, result.output
    repository = WorkspaceRepository.open(tmp_path / "workspace")
    try:
        state = repository.state()
        manifest = VariantManifest.model_validate(next(iter(state.compare.manifests.values())))
    finally:
        repository.close()
    command = manifest.renderer.command
    assert command is not None
    assert command.argv == [
        "render.py",
        "{input_wav}",
        "{params_json}",
        "{output_wav}",
    ]
    assert manifest.renderer.context_policy == "full_material"
