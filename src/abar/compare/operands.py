"""Resolution of public AudioOperand strings into concrete audio."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from abar.compare.audio.importing import InputAudioMetadata, import_input_audio_file, slice_audio
from abar.compare.manifests import VariantManifest
from abar.compare.models import AudioObject, ResolvedOperand
from abar.compare.projection import CompareState
from abar.compare.rendering import RenderOutcome, render_variant, runtime_fingerprint
from abar.foundation.object_store import ObjectStore


class OperandResolutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolutionEffect:
    kind: Literal["import", "slice", "render"]
    audio: AudioObject
    source_audio_id: str | None = None
    start_frame: int | None = None
    render: RenderOutcome | None = None
    input_source: InputAudioMetadata | None = None


@dataclass(frozen=True, slots=True)
class OperandResolution:
    operand: ResolvedOperand
    audio: AudioObject
    effects: tuple[ResolutionEffect, ...] = ()


def resolve_operand(
    text: str,
    *,
    input_key: Literal["p1", "p2"],
    state: CompareState,
    objects: ObjectStore,
    runtime: str | None = None,
    render_cache: dict[str, AudioObject] | None = None,
) -> OperandResolution:
    if text.startswith("audio:"):
        audio_id = text.removeprefix("audio:")
        try:
            audio = state.audio[audio_id]
        except KeyError:
            raise OperandResolutionError(f"unknown AudioObject: {audio_id}") from None
        return _resolved(input_key, audio, {"kind": "audio", "audio_id": audio.id})
    if text.startswith("source:"):
        material_id, clip_id = _parse_material_clip(text.removeprefix("source:"))
        clip = state.clips.get(clip_id)
        if clip is None or clip.material_id != material_id:
            raise OperandResolutionError("source operand references an unknown Material/Clip")
        material = state.materials[material_id]
        source = state.audio[material.source_audio_id]
        audio = slice_audio(
            source,
            start_frame=clip.start_frame,
            frames=clip.frames,
            objects=objects,
        )
        return _resolved(
            input_key,
            audio,
            {
                "kind": "source",
                "variant_ref": "source",
                "material_id": material_id,
                "clip_id": clip_id,
            },
            (ResolutionEffect("slice", audio, source.id, clip.start_frame),),
        )
    if text.startswith("variant:"):
        variant_id, clip_id = _parse_variant_clip(text.removeprefix("variant:"))
        variant = state.variants.get(variant_id)
        clip = state.clips.get(clip_id)
        if variant is None or clip is None:
            raise OperandResolutionError("variant operand references an unknown Variant/Clip")
        manifest = VariantManifest.model_validate(state.manifests[variant.manifest_id])
        material = state.materials[clip.material_id]
        source = state.audio[material.source_audio_id]
        if manifest.renderer.kind == "finite_map":
            assert manifest.renderer.finite_map is not None
            entry = manifest.renderer.finite_map.get(material.id)
            if entry is None:
                raise OperandResolutionError("finite_map_missing_material")
            rendered_material = state.audio.get(entry.audio_object_id)
            if rendered_material is None:
                raise OperandResolutionError("finite_map references an unknown AudioObject")
            if (
                rendered_material.pcm_sha != entry.audio_sha
                or rendered_material.sample_rate != entry.sample_rate
                or rendered_material.channel_layout != entry.channel_layout
                or rendered_material.frames != entry.frames
            ):
                raise OperandResolutionError("finite_map AudioObject metadata mismatch")
            _validate_rendered_material(rendered_material, source, manifest)
            audio = slice_audio(
                rendered_material,
                start_frame=clip.start_frame,
                frames=clip.frames,
                objects=objects,
            )
            return _resolved(
                input_key,
                audio,
                {
                    "kind": "variant",
                    "variant_ref": variant_id,
                    "material_id": material.id,
                    "clip_id": clip_id,
                },
                (
                    ResolutionEffect(
                        "slice",
                        audio,
                        rendered_material.id,
                        clip.start_frame,
                    ),
                ),
            )
        selected_runtime = runtime or runtime_fingerprint()
        cache_key = f"{variant_id}:{material.id}:{selected_runtime}"
        cached_audio_id = state.render_audio.get(cache_key)
        locally_cached = None if render_cache is None else render_cache.get(cache_key)
        outcome: RenderOutcome | None = None
        if cached_audio_id is not None:
            rendered_material = state.audio[cached_audio_id]
        elif locally_cached is not None:
            rendered_material = locally_cached
        else:
            outcome = render_variant(
                variant,
                manifest,
                material,
                source,
                objects=objects,
                runtime=selected_runtime,
            )
            rendered_material = outcome.audio
            if render_cache is not None:
                render_cache[cache_key] = rendered_material
        audio = slice_audio(
            rendered_material,
            start_frame=clip.start_frame,
            frames=clip.frames,
            objects=objects,
        )
        effects: list[ResolutionEffect] = []
        if outcome is not None:
            effects.append(ResolutionEffect("render", rendered_material, render=outcome))
        effects.append(ResolutionEffect("slice", audio, rendered_material.id, clip.start_frame))
        return _resolved(
            input_key,
            audio,
            {
                "kind": "variant",
                "variant_ref": variant_id,
                "material_id": material.id,
                "clip_id": clip_id,
            },
            tuple(effects),
        )
    path, range_seconds = parse_file_operand(text)
    imported = import_input_audio_file(path, objects=objects)
    audio = imported.audio
    effects: list[ResolutionEffect] = [
        ResolutionEffect("import", audio, input_source=imported.source)
    ]
    provenance: dict[str, object] = {
        "kind": "file",
        "name": path.name,
        "input_source": {
            "container": imported.source.container,
            "subtype": imported.source.subtype,
            "original_sha": imported.source.original_sha,
            "decoder": imported.source.decoder,
            "decoder_version": imported.source.decoder_version,
        },
    }
    if range_seconds is not None:
        start, duration = range_seconds
        start_frame = round(start * audio.sample_rate)
        frames = round(duration * audio.sample_rate)
        sliced = slice_audio(audio, start_frame=start_frame, frames=frames, objects=objects)
        effects.append(ResolutionEffect("slice", sliced, audio.id, start_frame))
        audio = sliced
        provenance["range"] = {"start_seconds": start, "duration_seconds": duration}
    return _resolved(input_key, audio, provenance, tuple(effects))


def parse_file_operand(text: str) -> tuple[Path, tuple[float, float] | None]:
    value = text.removeprefix("file:") if text.startswith("file:") else text
    if "#" not in value:
        path = Path(value).expanduser()
        range_seconds = None
    else:
        raw_path, raw_range = value.rsplit("#", 1)
        path = Path(raw_path).expanduser()
        try:
            start_text, duration_text = raw_range.split("+", 1)
            range_seconds = (float(start_text), float(duration_text))
        except (ValueError, TypeError):
            raise OperandResolutionError("file range must be START+DURATION") from None
        if range_seconds[0] < 0 or range_seconds[1] <= 0:
            raise OperandResolutionError("file range is invalid")
    if not path.is_file():
        raise OperandResolutionError(f"audio file does not exist: {path}")
    return path, range_seconds


def _parse_material_clip(value: str) -> tuple[str, str]:
    if "#" not in value:
        raise OperandResolutionError("source operand requires a global Clip ID")
    return tuple(value.split("#", 1))  # type: ignore[return-value]


def _parse_variant_clip(value: str) -> tuple[str, str]:
    if "#" not in value:
        raise OperandResolutionError("variant operand requires a global Clip ID")
    return tuple(value.split("#", 1))  # type: ignore[return-value]


def _validate_rendered_material(
    rendered: AudioObject,
    source: AudioObject,
    manifest: VariantManifest,
) -> None:
    if rendered.sample_rate != source.sample_rate or rendered.frames != source.frames:
        raise OperandResolutionError("render_timeline_mismatch")
    if rendered.channel_layout not in manifest.output_contract.channel_layouts:
        raise OperandResolutionError("unsupported_channel_layout")


def _resolved(
    input_key: Literal["p1", "p2"],
    audio: AudioObject,
    provenance: dict[str, object],
    effects: tuple[ResolutionEffect, ...] = (),
) -> OperandResolution:
    return OperandResolution(
        operand=ResolvedOperand(
            input_key=input_key,
            audio_id=audio.id,
            provenance_ref=provenance,  # type: ignore[arg-type]
        ),
        audio=audio,
        effects=effects,
    )
