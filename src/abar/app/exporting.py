"""Filesystem export use case composed at the application boundary."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from abar.compare.models import AudioObject
from abar.compare.operands import resolve_operand
from abar.compare.projection import CompareState
from abar.foundation.canonical_json import canonical_json_bytes
from abar.foundation.json_types import JSONValue
from abar.foundation.object_store import ObjectStore
from abar.project.projection import ProjectState


@dataclass(frozen=True, slots=True)
class ExportResult:
    variant_id: str
    output: Path
    rendered_files: tuple[Path, ...]


def write_project_export(
    compare: CompareState,
    authority: ProjectState,
    variant_id: str,
    output: Path,
    *,
    objects: ObjectStore,
    render_clips: Path | None = None,
) -> ExportResult:
    project = authority.project
    if project is None:
        raise ValueError("Project does not exist")
    if variant_id == "source":
        variant_document: dict[str, JSONValue] = {
            "variant_ref": "source",
            "manifest": {"kind": "source"},
            "resolved_params": {},
            "label": "source",
            "provenance": [],
        }
    else:
        variant = compare.variants.get(variant_id)
        if variant is None:
            raise ValueError("unknown Variant")
        variant_document = {
            "variant_ref": variant.id,
            "manifest": compare.manifests[variant.manifest_id],
            "resolved_params": variant.resolved_params,
            "label": variant.label,
            "provenance": list(compare.provenance.get(variant.id, ())),
        }
    document: dict[str, JSONValue] = {
        "schema_version": 2,
        "project_id": project.id,
        "brief_revision": project.brief_revision,
        "exported_at": datetime.now(UTC).isoformat(),
        **variant_document,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(document) + b"\n")
    temporary.replace(output)

    rendered: list[Path] = []
    if render_clips is not None:
        render_clips.mkdir(parents=True, exist_ok=True)
        render_cache: dict[str, AudioObject] = {}
        for material_id in project.material_ids:
            material = compare.materials[material_id]
            for clip_id in material.clip_ids:
                operand = (
                    f"source:{material_id}#{clip_id}"
                    if variant_id == "source"
                    else f"variant:{variant_id}#{clip_id}"
                )
                resolved = resolve_operand(
                    operand,
                    input_key="p1",
                    state=compare,
                    objects=objects,
                    render_cache=render_cache,
                )
                destination = render_clips / f"{clip_id}-{variant_id}.wav"
                pending = destination.with_name(f".{destination.name}.tmp")
                pending.write_bytes(objects.read(resolved.audio.object_id))
                pending.replace(destination)
                rendered.append(destination)
    return ExportResult(variant_id=variant_id, output=output, rendered_files=tuple(rendered))
