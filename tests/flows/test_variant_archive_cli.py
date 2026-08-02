import hashlib
import json
from pathlib import Path

from typer.testing import CliRunner

from abar.app.repository import WorkspaceRepository
from abar.cli import app


def test_variant_add_imports_command_renderer_archive(tmp_path: Path) -> None:
    archive = tmp_path / "renderer.zip"
    archive.write_bytes(b"immutable renderer bundle")
    executable = b"renderer executable"
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
