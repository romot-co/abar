"""Canonical audio import and slicing."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf  # pyright: ignore[reportMissingTypeStubs]

from abar.compare.audio.clip_selection import clip_id, select_default_clips
from abar.compare.audio.content import (
    audio_content_id,
    decode_input_audio_bytes,
    decode_wav_bytes,
    encode_float32_wav,
    inspect_wav_bytes,
)
from abar.compare.models import AudioObject, Clip, Material
from abar.foundation.object_store import ObjectStore
from abar.foundation.time_ids import new_id


@dataclass(frozen=True, slots=True)
class InputAudioMetadata:
    container: str
    subtype: str
    original_sha: str
    decoder: str
    decoder_version: str


@dataclass(frozen=True, slots=True)
class ImportedMaterial:
    audio: AudioObject
    material: Material
    clips: tuple[Clip, ...]
    source: InputAudioMetadata


@dataclass(frozen=True, slots=True)
class ImportedInputAudio:
    audio: AudioObject
    source: InputAudioMetadata


def import_canonical_wav_bytes(data: bytes, *, objects: ObjectStore) -> AudioObject:
    """Store bytes produced inside ABAR after enforcing the Core WAV contract."""

    decoded = decode_wav_bytes(data)
    return _store_decoded_audio(decoded.pcm, decoded.sample_rate, objects=objects)


def import_input_audio_bytes(data: bytes, *, objects: ObjectStore) -> ImportedInputAudio:
    """Decode an external supported format and store only its canonical WAV form."""

    decoded = decode_input_audio_bytes(data)
    audio = _store_decoded_audio(
        decoded.audio.pcm,
        decoded.audio.sample_rate,
        objects=objects,
    )
    return ImportedInputAudio(
        audio,
        InputAudioMetadata(
            container=decoded.container,
            subtype=decoded.subtype,
            original_sha=f"sha256:{hashlib.sha256(data).hexdigest()}",
            decoder="libsndfile",
            decoder_version=str(sf.__libsndfile_version__),
        ),
    )


def _store_decoded_audio(
    pcm: np.ndarray,
    sample_rate: int,
    *,
    objects: ObjectStore,
) -> AudioObject:
    canonical = encode_float32_wav(pcm, sample_rate)
    stored = objects.put(canonical)
    inspected = inspect_wav_bytes(canonical)
    return AudioObject(
        id=audio_content_id(inspected),
        object_id=stored.object_id,
        pcm_sha=f"sha256:{inspected.sha256}",
        sample_rate=inspected.sample_rate,
        channel_layout=inspected.channel_layout,
        frames=inspected.frames,
    )


def import_input_audio_file(path: Path, *, objects: ObjectStore) -> ImportedInputAudio:
    return import_input_audio_bytes(path.read_bytes(), objects=objects)


def import_material_file(
    path: Path,
    *,
    objects: ObjectStore,
    source_group: str | None = None,
    name: str | None = None,
    seed: int = 0,
) -> ImportedMaterial:
    imported = import_input_audio_file(path, objects=objects)
    audio = imported.audio
    decoded = decode_wav_bytes(objects.read(audio.object_id))
    # Material is a research entity, not an audio-content identity. The same PCM
    # may intentionally be registered more than once with different context.
    material = new_id("m_")
    windows = select_default_clips(decoded, seed=seed)
    clips = tuple(
        Clip(
            id=clip_id(material, window),
            material_id=material,
            start_frame=window.start_frame,
            frames=window.frames,
            role=window.role,
            selector_id=window.selector_id,
            selector_version=window.selector_version,
            seed=window.seed,
        )
        for window in windows
    )
    return ImportedMaterial(
        audio=audio,
        material=Material(
            id=material,
            name=name or path.name,
            source_audio_id=audio.id,
            source_group=source_group,
            clip_ids=tuple(item.id for item in clips),
        ),
        clips=clips,
        source=imported.source,
    )


def slice_audio(
    source: AudioObject,
    *,
    start_frame: int,
    frames: int,
    objects: ObjectStore,
) -> AudioObject:
    if start_frame < 0 or frames <= 0 or start_frame + frames > source.frames:
        raise ValueError("slice range is outside the source audio")
    decoded = decode_wav_bytes(objects.read(source.object_id))
    data = encode_float32_wav(decoded.pcm[start_frame : start_frame + frames], decoded.sample_rate)
    return import_canonical_wav_bytes(data, objects=objects)
