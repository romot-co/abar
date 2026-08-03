"""Project catalog use cases: Project, Material, Clip, Audio, and Variant registration."""

import hashlib
from pathlib import Path
from typing import cast

from abar.app.command_support import CommandError, existing_operation, operation_key, request_hash
from abar.app.event_payloads import audio_payload, material_payload, recipe_payload
from abar.app.events import child_key, draft
from abar.app.repository import WorkspaceRepository
from abar.compare.audio.clip_selection import manual_clip_id
from abar.compare.audio.importing import import_input_audio_file, import_material_file, slice_audio
from abar.compare.bundles import validate_command_archive
from abar.compare.manifests import VariantManifest
from abar.compare.models import RecipeRef
from abar.compare.variants import register_variant
from abar.foundation.json_types import JSONValue
from abar.foundation.time_ids import new_id
from abar.project.models import Project


def init_project(
    repository: WorkspaceRepository,
    *,
    name: str,
    brief: str,
    material_paths: tuple[Path, ...] = (),
    material_ids: tuple[str, ...] = (),
    current_best: str = "source",
    idempotency_key: str | None = None,
) -> str:
    try:
        Project(
            id="validation",
            name=name,
            brief_text=brief,
            brief_revision=1,
            material_ids=(),
            primary_recipe=RecipeRef("matched"),
            current_best_variant_id=current_best,
            in_use_variant_id=None,
        )
    except ValueError as error:
        raise CommandError("invalid_project", str(error)) from error
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "project.init",
        {
            "name": name,
            "brief": brief,
            "material_paths": [str(item.expanduser().resolve()) for item in material_paths],
            "material_ids": list(material_ids),
            "current_best": current_best,
        },
    )
    existing = existing_operation(repository, key, "project.created", request_hash=fingerprint)
    if existing is not None:
        return cast(str, existing.payload["project_id"])
    state = repository.state()
    if state.project.project is not None:
        raise CommandError("a Workspace may contain only one Project")
    if current_best != "source" and current_best not in state.compare.variants:
        raise CommandError("initial current best must be source or a known Variant")
    imports = [import_material_file(path, objects=repository.objects) for path in material_paths]
    for material_id in material_ids:
        if material_id not in state.compare.materials:
            raise CommandError(
                "unknown_existing_material",
                f"unknown existing Material: {material_id}; use --material to import a file",
            )
    project_id = new_id("prj_")
    with repository.events.transaction(causation_id=key) as tx:
        index = 0
        imported_ids: list[str] = []
        for imported in imports:
            tx.append(
                draft(
                    "audio.imported",
                    audio_payload(
                        imported.audio,
                        provenance="imported_file",
                        input_source=imported.source,
                    ),
                    idempotency_key=child_key(key, index),
                )
            )
            index += 1
            tx.append(
                draft(
                    "material.added",
                    material_payload(imported.material, imported.clips),
                    idempotency_key=child_key(key, index),
                )
            )
            index += 1
            imported_ids.append(imported.material.id)
        tx.append(
            draft(
                "project.created",
                {
                    "project_id": project_id,
                    "name": name,
                    "brief": brief,
                    "primary_recipe": recipe_payload(RecipeRef("matched")),
                    "initial_current_best": current_best,
                    "ready_session_limit": 12,
                    "request_hash": fingerprint,
                },
                idempotency_key=child_key(key, index),
            )
        )
        index += 1
        for material_id in (*material_ids, *imported_ids):
            tx.append(
                draft(
                    "project.material.attached",
                    {"project_id": project_id, "material_id": material_id},
                    idempotency_key=child_key(key, index),
                )
            )
            index += 1
    return project_id


def add_material(
    repository: WorkspaceRepository,
    path: Path,
    *,
    source_group: str | None = None,
    name: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "material.add",
        {
            "path": str(path.expanduser().resolve()),
            "source_group": source_group,
            "name": name,
        },
    )
    existing = existing_operation(repository, key, "material.added", request_hash=fingerprint)
    if existing is not None:
        return cast(str, existing.payload["material_id"])
    state = repository.state()
    imported = import_material_file(
        path,
        objects=repository.objects,
        source_group=source_group,
        name=name,
    )
    with repository.events.transaction(causation_id=key) as tx:
        tx.append(
            draft(
                "audio.imported",
                audio_payload(
                    imported.audio,
                    provenance="imported_file",
                    input_source=imported.source,
                ),
                idempotency_key=child_key(key, 0),
            )
        )
        tx.append(
            draft(
                "material.added",
                {
                    **material_payload(imported.material, imported.clips),
                    "request_hash": fingerprint,
                },
                idempotency_key=child_key(key, 1),
            )
        )
        if state.project.project is not None:
            tx.append(
                draft(
                    "project.material.attached",
                    {
                        "project_id": state.project.project.id,
                        "material_id": imported.material.id,
                    },
                    idempotency_key=child_key(key, 2),
                )
            )
    return imported.material.id


def add_materials(
    repository: WorkspaceRepository,
    paths: tuple[Path, ...],
    *,
    source_group: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[str, ...]:
    """Import a set with stable per-file idempotency and partial-resume semantics."""

    if not paths:
        raise CommandError("material set must contain at least one file")
    key = operation_key(idempotency_key)
    return tuple(
        add_material(
            repository,
            path,
            source_group=source_group,
            idempotency_key=child_key(key, index),
        )
        for index, path in enumerate(paths)
    )


def import_audio(
    repository: WorkspaceRepository,
    path: Path,
    *,
    idempotency_key: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    fingerprint = request_hash("audio.import", {"path": str(path.expanduser().resolve())})
    existing = existing_operation(repository, key, "audio.imported", request_hash=fingerprint)
    if existing is not None:
        return cast(str, existing.payload["audio_id"])
    repository.state()
    imported = import_input_audio_file(path, objects=repository.objects)
    repository.events.append(
        draft(
            "audio.imported",
            {
                **audio_payload(
                    imported.audio,
                    provenance="imported_file",
                    input_source=imported.source,
                ),
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )
    return imported.audio.id


def add_clip(
    repository: WorkspaceRepository,
    material_id: str,
    *,
    start_seconds: float,
    duration_seconds: float,
    role: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "clip.add",
        {
            "material_id": material_id,
            "start_seconds": start_seconds,
            "duration_seconds": duration_seconds,
            "role": role,
        },
    )
    existing = existing_operation(repository, key, "audio.slice.created", request_hash=fingerprint)
    if existing is not None:
        return cast(str, cast(dict[str, JSONValue], existing.payload["clip"])["id"])
    state = repository.state()
    material = state.compare.materials.get(material_id)
    if material is None:
        raise CommandError("unknown Material")
    source = state.compare.audio[material.source_audio_id]
    start_frame = round(start_seconds * source.sample_rate)
    frames = round(duration_seconds * source.sample_rate)
    clip = manual_clip_id(material_id, start_frame, frames, role)
    sliced = slice_audio(source, start_frame=start_frame, frames=frames, objects=repository.objects)
    repository.events.append(
        draft(
            "audio.slice.created",
            {
                **audio_payload(sliced, provenance="source_slice"),
                "source_audio_id": source.id,
                "clip": {
                    "id": clip,
                    "material_id": material_id,
                    "start_frame": start_frame,
                    "frames": frames,
                    "role": role,
                    "selector_id": None,
                    "selector_version": None,
                    "seed": None,
                },
                "request_hash": fingerprint,
            },
            idempotency_key=key,
        )
    )
    return clip


def add_variant(
    repository: WorkspaceRepository,
    manifest_document: dict[str, JSONValue],
    *,
    params: dict[str, JSONValue] | None = None,
    label: str | None = None,
    provenance: dict[str, JSONValue] | None = None,
    idempotency_key: str | None = None,
) -> str:
    key = operation_key(idempotency_key)
    fingerprint = request_hash(
        "variant.add",
        {
            "manifest": manifest_document,
            "params": params,
            "label": label,
            "provenance": provenance,
        },
    )
    existing = existing_operation(repository, key, "variant.created", request_hash=fingerprint)
    if existing is not None:
        return cast(str, existing.payload["variant_id"])
    registration = register_variant(
        manifest_document,
        resolved_params=params,
        label=label,
        provenance=provenance,
    )
    manifest = registration.manifest
    archive_bytes = repository.objects.read(manifest.source_archive.object_id)
    _validate_variant_archive(manifest, archive_bytes)
    state = repository.state()
    existing_variant = state.compare.variants.get(registration.variant.id)
    if existing_variant is not None and existing_variant != registration.variant:
        raise CommandError(
            "variant_definition_conflict",
            "Variant definition and label are immutable for a content identity",
        )
    existing_manifest = state.compare.manifests.get(manifest.id)
    if existing_manifest is not None and existing_manifest != manifest.document():
        raise CommandError(
            "variant_manifest_conflict",
            "Variant manifest ID is already registered with different content",
        )
    if manifest.renderer.kind == "finite_map":
        assert manifest.renderer.finite_map is not None
        for material_id, entry in manifest.renderer.finite_map.items():
            material = state.compare.materials.get(material_id)
            if material is None:
                raise CommandError(f"finite_map references unknown Material: {material_id}")
            rendered = state.compare.audio.get(entry.audio_object_id)
            if rendered is None:
                raise CommandError(
                    f"finite_map references unknown AudioObject: {entry.audio_object_id}"
                )
            source = state.compare.audio[material.source_audio_id]
            if (
                rendered.pcm_sha != entry.audio_sha
                or rendered.sample_rate != entry.sample_rate
                or rendered.channel_layout != entry.channel_layout
                or rendered.frames != entry.frames
            ):
                raise CommandError("finite_map AudioObject metadata mismatch")
            if rendered.sample_rate != source.sample_rate or rendered.frames != source.frames:
                raise CommandError("finite_map must preserve the Material timeline")
            if rendered.channel_layout not in manifest.output_contract.channel_layouts:
                raise CommandError("finite_map uses an unsupported channel layout")
    with repository.events.transaction(causation_id=key) as tx:
        tx.append(
            draft(
                "variant.created",
                {
                    "variant_id": registration.variant.id,
                    "label": registration.variant.label,
                    "manifest_id": registration.variant.manifest_id,
                    "resolved_params": registration.variant.resolved_params,
                    "render_contract": registration.variant.render_contract,
                    "manifest": manifest.document(),
                    "request_hash": fingerprint,
                },
                idempotency_key=child_key(key, 0),
            )
        )
        if provenance is not None:
            tx.append(
                draft(
                    "variant.provenance.observed",
                    {"variant_id": registration.variant.id, "provenance": provenance},
                    idempotency_key=child_key(key, 1),
                )
            )
    return registration.variant.id


def add_variant_archive(
    repository: WorkspaceRepository,
    manifest_document: dict[str, JSONValue],
    archive_bytes: bytes,
    *,
    params: dict[str, JSONValue] | None = None,
    label: str | None = None,
    provenance: dict[str, JSONValue] | None = None,
    idempotency_key: str | None = None,
) -> str:
    """Validate and import a Variant archive through one application boundary."""

    repository.state()
    digest = hashlib.sha256(archive_bytes).hexdigest()
    archive_ref: dict[str, JSONValue] = {
        "object_id": f"obj_{digest}",
        "sha": f"sha256:{digest}",
    }
    resolved_manifest = dict(manifest_document)
    declared = resolved_manifest.get("source_archive")
    if declared is not None and declared != archive_ref:
        raise CommandError(
            "source_archive_mismatch",
            "archive content does not match manifest source_archive",
        )
    resolved_manifest["source_archive"] = archive_ref
    registration = register_variant(
        resolved_manifest,
        resolved_params=params,
        label=label,
        provenance=provenance,
    )
    _validate_variant_archive(registration.manifest, archive_bytes)
    stored = repository.objects.put(archive_bytes)
    if (
        stored.object_id != archive_ref["object_id"]
        or f"sha256:{stored.sha256}" != archive_ref["sha"]
    ):
        raise CommandError("source archive object identity mismatch")
    return add_variant(
        repository,
        resolved_manifest,
        params=params,
        label=label,
        provenance=provenance,
        idempotency_key=idempotency_key,
    )


def _validate_variant_archive(manifest: VariantManifest, archive_bytes: bytes) -> None:
    validated = manifest
    archive_sha = f"sha256:{hashlib.sha256(archive_bytes).hexdigest()}"
    if archive_sha != validated.source_archive.sha:
        raise CommandError("Variant source archive hash mismatch")
    if validated.renderer.kind == "command":
        assert validated.renderer.command is not None
        try:
            validate_command_archive(archive_bytes, validated.renderer.command)
        except ValueError as error:
            raise CommandError("invalid_renderer_bundle", str(error)) from error
