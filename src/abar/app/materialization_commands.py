"""Non-authoritative Variant audio materialization use case."""

from pathlib import Path
from typing import cast

from abar.app.command_support import CommandError, existing_operation, operation_key, request_hash
from abar.app.comparison_events import append_resolution_effects
from abar.app.events import child_key, draft
from abar.app.repository import WorkspaceRepository
from abar.app.views import MaterializedAudioView, VariantMaterializationView
from abar.compare.models import AudioObject
from abar.compare.operands import OperandResolution, resolve_operand
from abar.foundation.json_types import JSONValue


def materialize_variant(
    repository: WorkspaceRepository,
    variant_id: str,
    *,
    clip_ids: tuple[str, ...],
    output: Path,
    idempotency_key: str | None = None,
) -> VariantMaterializationView:
    """Render exact Clip audio for external measurement without changing Project authority."""
    key = operation_key(idempotency_key)
    output_directory = output.expanduser().resolve()
    fingerprint = request_hash(
        "variant.materialize",
        {
            "variant_id": variant_id,
            "clip_ids": list(clip_ids),
            "output": str(output_directory),
        },
    )
    existing = existing_operation(
        repository,
        key,
        "variant.materialized",
        request_hash=fingerprint,
    )
    if existing is not None:
        view = _view_from_payload(existing.payload)
        _write_materialized_files(repository, view)
        return view

    state = repository.state()
    project = state.project.project
    if project is None:
        raise CommandError("Project does not exist")
    if variant_id != "source" and variant_id not in state.compare.variants:
        raise CommandError("unknown Variant")
    if not clip_ids or len(set(clip_ids)) != len(clip_ids):
        raise CommandError("distinct Clip IDs are required")
    project_clips = {
        clip_id
        for material_id in project.material_ids
        for clip_id in state.compare.materials[material_id].clip_ids
    }
    if any(clip_id not in project_clips for clip_id in clip_ids):
        raise CommandError("materialization requires attached Project Clips")
    if output_directory.exists() and not output_directory.is_dir():
        raise CommandError("materialization output must be a directory")

    render_cache: dict[str, AudioObject] = {}
    resolutions: list[OperandResolution] = []
    items: list[MaterializedAudioView] = []
    try:
        for clip_id in clip_ids:
            clip = state.compare.clips[clip_id]
            operand = (
                f"source:{clip.material_id}#{clip_id}"
                if variant_id == "source"
                else f"variant:{variant_id}#{clip_id}"
            )
            resolved = resolve_operand(
                operand,
                input_key="p1",
                state=state.compare,
                objects=repository.objects,
                render_cache=render_cache,
            )
            resolutions.append(resolved)
            items.append(
                MaterializedAudioView(
                    clip_id=clip_id,
                    material_id=clip.material_id,
                    audio_id=resolved.audio.id,
                    pcm_sha=resolved.audio.pcm_sha,
                    sample_rate=resolved.audio.sample_rate,
                    channel_layout=resolved.audio.channel_layout,
                    frames=resolved.audio.frames,
                    output=str(output_directory / f"{clip_id}-{variant_id}.wav"),
                )
            )
    except (OSError, ValueError) as error:
        raise CommandError(str(error)) from error

    view = VariantMaterializationView(
        variant_id=variant_id,
        output_directory=str(output_directory),
        items=tuple(items),
    )
    _write_materialized_files(repository, view, resolutions=resolutions)
    with repository.events.transaction(causation_id=key) as tx:
        index = append_resolution_effects(tx, key, resolutions)
        tx.append(
            draft(
                "variant.materialized",
                {
                    "variant_id": view.variant_id,
                    "output_directory": view.output_directory,
                    "items": cast(
                        list[JSONValue],
                        [item.model_dump(mode="json") for item in view.items],
                    ),
                    "request_hash": fingerprint,
                },
                idempotency_key=child_key(key, index),
            )
        )
    return view


def _view_from_payload(payload: dict[str, JSONValue]) -> VariantMaterializationView:
    raw_items = cast(list[dict[str, JSONValue]], payload["items"])
    return VariantMaterializationView.model_validate(
        {
            "schema_version": 2,
            "variant_id": payload["variant_id"],
            "output_directory": payload["output_directory"],
            "items": tuple(MaterializedAudioView.model_validate(item) for item in raw_items),
        }
    )


def _write_materialized_files(
    repository: WorkspaceRepository,
    view: VariantMaterializationView,
    *,
    resolutions: list[OperandResolution] | None = None,
) -> None:
    audio_by_id = (
        {resolution.audio.id: resolution.audio for resolution in resolutions}
        if resolutions is not None
        else repository.state().compare.audio
    )
    Path(view.output_directory).mkdir(parents=True, exist_ok=True)
    for item in view.items:
        try:
            audio = audio_by_id[item.audio_id]
        except KeyError:
            raise CommandError(f"materialized AudioObject is missing: {item.audio_id}") from None
        destination = Path(item.output)
        pending = destination.with_name(f".{destination.name}.tmp")
        try:
            pending.write_bytes(repository.objects.read(audio.object_id))
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)
