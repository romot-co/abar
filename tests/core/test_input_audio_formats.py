import hashlib
import io
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf  # pyright: ignore[reportMissingTypeStubs]

from abar.compare.audio.content import InvalidAudioObjectError, decode_wav_bytes
from abar.compare.audio.importing import (
    import_canonical_wav_bytes,
    import_input_audio_bytes,
)
from abar.infrastructure.object_store import ImmutableObjectStore


@pytest.mark.parametrize(
    ("container", "subtype"),
    (
        ("WAV", "PCM_24"),
        ("MP3", "MPEG_LAYER_III"),
        ("FLAC", "PCM_24"),
        ("AIFF", "PCM_24"),
        ("OGG", "VORBIS"),
        ("OGG", "OPUS"),
        ("CAF", "ALAC_24"),
    ),
)
def test_supported_input_is_canonicalized_to_internal_wav(
    tmp_path: Path,
    container: str,
    subtype: str,
) -> None:
    objects = ImmutableObjectStore(tmp_path / "objects")
    encoded = _encoded_audio(container, subtype)

    imported = import_input_audio_bytes(encoded, objects=objects)
    canonical = objects.read(imported.audio.object_id)
    decoded = decode_wav_bytes(canonical)

    assert imported.source.container == container
    assert imported.source.subtype == subtype
    assert imported.source.original_sha == f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    assert imported.source.decoder == "libsndfile"
    assert imported.source.decoder_version
    assert decoded.sample_rate == 16_000
    assert decoded.channel_layout == "mono"
    assert decoded.frames == 32_000
    with sf.SoundFile(io.BytesIO(canonical)) as audio_file:
        assert audio_file.format == "WAV"
        assert audio_file.subtype == "FLOAT"


def test_internal_audio_import_remains_wav_only(tmp_path: Path) -> None:
    objects = ImmutableObjectStore(tmp_path / "objects")
    with pytest.raises(InvalidAudioObjectError, match="WAV container"):
        import_canonical_wav_bytes(
            _encoded_audio("MP3", "MPEG_LAYER_III"),
            objects=objects,
        )


def test_unlisted_container_is_rejected(tmp_path: Path) -> None:
    objects = ImmutableObjectStore(tmp_path / "objects")
    with pytest.raises(InvalidAudioObjectError, match="unsupported input audio format: AU"):
        import_input_audio_bytes(_encoded_audio("AU", "PCM_16"), objects=objects)


def _encoded_audio(container: str, subtype: str) -> bytes:
    time = np.arange(32_000, dtype=np.float32) / 16_000
    pcm = (0.2 * np.sin(2.0 * np.pi * 220.0 * time)).reshape(-1, 1)
    stream = io.BytesIO()
    sf.write(stream, pcm, 16_000, format=container, subtype=subtype)
    return stream.getvalue()
