"""Canonical audio content primitives owned by Compare Core."""

import hashlib
import io
from dataclasses import dataclass
from typing import Literal

import numpy as np
import soundfile as sf  # pyright: ignore[reportMissingTypeStubs]


class InvalidAudioObjectError(ValueError):
    """Raised when an imported audio object violates the Core audio contract."""


@dataclass(frozen=True, slots=True)
class CanonicalAudio:
    sha256: str
    sample_rate: int
    channel_layout: Literal["mono", "stereo"]
    frames: int


@dataclass(frozen=True, slots=True)
class DecodedAudio:
    pcm: np.ndarray
    sample_rate: int
    channel_layout: Literal["mono", "stereo"]

    @property
    def frames(self) -> int:
        return int(self.pcm.shape[0])


@dataclass(frozen=True, slots=True)
class DecodedInputAudio:
    audio: DecodedAudio
    container: str
    subtype: str


SUPPORTED_INPUT_FORMATS = frozenset(
    {"WAV", "WAVEX", "RF64", "W64", "AIFF", "FLAC", "OGG", "CAF", "MP3"}
)


def decode_input_audio_bytes(data: bytes) -> DecodedInputAudio:
    """Decode a supported external audio container into float32 frame-major PCM."""

    try:
        with sf.SoundFile(io.BytesIO(data)) as audio_file:
            container = str(audio_file.format)
            subtype = str(audio_file.subtype)
            if container not in SUPPORTED_INPUT_FORMATS:
                raise InvalidAudioObjectError(f"unsupported input audio format: {container}")
            decoded = _decoded_audio(
                audio_file.read(dtype="float32", always_2d=True),
                int(audio_file.samplerate),
                int(audio_file.channels),
            )
    except (sf.LibsndfileError, RuntimeError) as error:
        raise InvalidAudioObjectError("input is not a readable supported audio file") from error
    return DecodedInputAudio(decoded, container, subtype)


def decode_wav_bytes(data: bytes) -> DecodedAudio:
    """Decode an internal Core WAV into float32 frame-major PCM."""

    try:
        with sf.SoundFile(io.BytesIO(data)) as audio_file:
            if audio_file.format != "WAV":
                raise InvalidAudioObjectError("audio object must use the WAV container")
            return _decoded_audio(
                audio_file.read(dtype="float32", always_2d=True),
                int(audio_file.samplerate),
                int(audio_file.channels),
            )
    except (sf.LibsndfileError, RuntimeError) as error:
        raise InvalidAudioObjectError("audio object is not a readable WAV file") from error


def _decoded_audio(pcm: np.ndarray, sample_rate: int, channels: int) -> DecodedAudio:
    if channels == 1:
        channel_layout: Literal["mono", "stereo"] = "mono"
    elif channels == 2:
        channel_layout = "stereo"
    else:
        raise InvalidAudioObjectError("Core audio objects must be mono or stereo")

    canonical_pcm = np.asarray(pcm, dtype=np.dtype("<f4"), order="C")
    if not np.isfinite(canonical_pcm).all():
        raise InvalidAudioObjectError("PCM must contain only finite samples")
    return DecodedAudio(
        pcm=canonical_pcm,
        sample_rate=sample_rate,
        channel_layout=channel_layout,
    )


def inspect_wav_bytes(data: bytes) -> CanonicalAudio:
    """Identify WAV contents by canonical interleaved little-endian float32 PCM."""

    decoded = decode_wav_bytes(data)
    canonical_pcm = decoded.pcm
    digest = hashlib.sha256(canonical_pcm.tobytes(order="C")).hexdigest()
    return CanonicalAudio(
        sha256=digest,
        sample_rate=decoded.sample_rate,
        channel_layout=decoded.channel_layout,
        frames=decoded.frames,
    )


def audio_content_id(audio: CanonicalAudio) -> str:
    from abar.foundation.canonical_json import canonical_sha256
    from abar.foundation.json_types import JSONValue

    identity: dict[str, JSONValue] = {
        "pcm_sha": f"sha256:{audio.sha256}",
        "sample_rate": audio.sample_rate,
        "channel_layout": audio.channel_layout,
        "frames": audio.frames,
    }
    return f"audio_{canonical_sha256(identity)}"


def encode_float32_wav(pcm: np.ndarray, sample_rate: int) -> bytes:
    """Encode frame-major PCM into the canonical Core WAV representation."""

    normalized = np.asarray(pcm, dtype=np.dtype("<f4"), order="C")
    if normalized.ndim != 2 or normalized.shape[1] not in (1, 2):
        raise InvalidAudioObjectError("PCM must have shape (frames, mono|stereo channels)")
    if normalized.shape[0] < 1:
        raise InvalidAudioObjectError("PCM must contain at least one frame")
    if not np.isfinite(normalized).all():
        raise InvalidAudioObjectError("PCM must contain only finite samples")
    stream = io.BytesIO()
    sf.write(stream, normalized, sample_rate, format="WAV", subtype="FLOAT")
    return stream.getvalue()
