"""Exchange-equivariant native, aligned, and loudness-matched Recipes."""

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import cast

import numpy as np
from scipy import signal  # pyright: ignore[reportMissingTypeStubs]

from abar.compare.audio.content import (
    DecodedAudio,
    decode_wav_bytes,
    encode_float32_wav,
    inspect_wav_bytes,
)
from abar.compare.models import AudioObject, PreparedPair, RecipeRef
from abar.foundation.canonical_json import canonical_sha256
from abar.foundation.json_types import JSONValue
from abar.foundation.object_store import ObjectStore


class RecipeViolation(ValueError):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PreparedResult:
    pair: PreparedPair
    output_audio: tuple[AudioObject, AudioObject]


def prepare(
    p1: AudioObject,
    p2: AudioObject,
    recipe: RecipeRef,
    *,
    objects: ObjectStore,
) -> PreparedResult:
    first = decode_wav_bytes(objects.read(p1.object_id))
    second = decode_wav_bytes(objects.read(p2.object_id))
    warnings = _input_warnings(first, second)
    native_first, native_second, rate, native_features = _native(first, second)
    features: dict[str, JSONValue] = dict(native_features)
    if recipe.id == "native":
        output_first, output_second = native_first, native_second
    else:
        output_first, output_second, aligned_features, aligned_warnings = _aligned(
            native_first, native_second, rate
        )
        features.update(aligned_features)
        warnings.extend(aligned_warnings)
        if recipe.id == "matched":
            output_first, output_second, matched_features = _matched(
                output_first, output_second, rate
            )
            features.update(matched_features)
    original_peak = max(float(np.max(np.abs(first.pcm))), float(np.max(np.abs(second.pcm))))
    output_peak = max(float(np.max(np.abs(output_first))), float(np.max(np.abs(output_second))))
    if output_peak > 1.0 and original_peak <= 1.0:
        raise RecipeViolation("post_recipe_clip")
    audio_first = _store_audio(output_first, rate, objects)
    audio_second = _store_audio(output_second, rate, objects)
    recipe_doc: dict[str, JSONValue] = {
        "id": recipe.id,
        "version": recipe.version,
        "config": recipe.config,
    }
    pair_identity: dict[str, JSONValue] = {
        "p1": {"input_audio_id": p1.id, "output_audio_id": audio_first.id},
        "p2": {"input_audio_id": p2.id, "output_audio_id": audio_second.id},
        "recipe": recipe_doc,
    }
    pair_id = f"pp_{canonical_sha256(pair_identity)}"
    pair = PreparedPair(
        id=pair_id,
        input_audio_ids=(p1.id, p2.id),
        recipe=recipe,
        output_audio_by_input_key={"p1": audio_first.id, "p2": audio_second.id},
        features=features,
        warnings=tuple(sorted(set(warnings))),
        no_effect=audio_first.id == audio_second.id,
    )
    return PreparedResult(pair=pair, output_audio=(audio_first, audio_second))


def _native(
    first: DecodedAudio, second: DecodedAudio
) -> tuple[np.ndarray, np.ndarray, int, dict[str, JSONValue]]:
    target_rate = max(first.sample_rate, second.sample_rate)
    target_channels = (
        2 if first.channel_layout == "stereo" or second.channel_layout == "stereo" else 1
    )
    a = _convert_layout(_resample(first.pcm, first.sample_rate, target_rate), target_channels)
    b = _convert_layout(_resample(second.pcm, second.sample_rate, target_rate), target_channels)
    length = min(len(a), len(b))
    if length < 1:
        raise RecipeViolation("empty_overlap")
    return (
        np.asarray(a[:length], dtype=np.float32),
        np.asarray(b[:length], dtype=np.float32),
        target_rate,
        {"target_sample_rate": target_rate, "target_channels": target_channels},
    )


def _resample(pcm: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return np.asarray(pcm, dtype=np.float32)
    ratio = Fraction(target_rate, source_rate)
    return cast(
        np.ndarray,
        signal.resample_poly(pcm, ratio.numerator, ratio.denominator, axis=0),  # pyright: ignore[reportUnknownMemberType]
    ).astype(np.float32)


def _convert_layout(pcm: np.ndarray, channels: int) -> np.ndarray:
    if pcm.shape[1] == channels:
        return pcm
    if pcm.shape[1] == 1 and channels == 2:
        return np.repeat(pcm, 2, axis=1)
    if pcm.shape[1] == 2 and channels == 1:
        return np.mean(pcm, axis=1, keepdims=True)
    raise RecipeViolation("unsupported_channel_layout")


def _aligned(
    first: np.ndarray, second: np.ndarray, sample_rate: int
) -> tuple[np.ndarray, np.ndarray, dict[str, JSONValue], list[str]]:
    first_mono = np.mean(first.astype(np.float64), axis=1)
    second_mono = np.mean(second.astype(np.float64), axis=1)
    first_mono -= np.mean(first_mono)
    second_mono -= np.mean(second_mono)
    denominator = float(np.linalg.norm(first_mono) * np.linalg.norm(second_mono))
    if denominator <= 0.0:
        raise RecipeViolation("alignment_unresolved")
    max_lag = min(round(0.25 * sample_rate), len(first_mono) - 1, len(second_mono) - 1)
    correlations = cast(
        np.ndarray,
        signal.correlate(first_mono, second_mono, mode="full", method="fft"),  # pyright: ignore[reportUnknownMemberType]
    )
    lags = cast(
        np.ndarray,
        signal.correlation_lags(len(first_mono), len(second_mono), mode="full"),  # pyright: ignore[reportUnknownMemberType]
    )
    allowed = np.abs(lags) <= max_lag
    values = correlations[allowed]
    allowed_lags = lags[allowed]
    index = int(np.argmax(np.abs(values)))
    lag = int(allowed_lags[index])
    correlation = float(values[index] / denominator)
    if abs(correlation) < 0.10:
        raise RecipeViolation("alignment_unresolved")
    if lag > 0:
        a, b = first[lag:], second[: len(first) - lag]
    elif lag < 0:
        a, b = first[: len(second) + lag], second[-lag:]
    else:
        a, b = first, second
    length = min(len(a), len(b))
    overlap_ratio = length / max(len(first), len(second))
    if length < round(0.5 * sample_rate) or overlap_ratio < 0.80:
        raise RecipeViolation("empty_overlap")
    a = np.asarray(a[:length], dtype=np.float32)
    b = np.asarray(b[:length], dtype=np.float32)
    a_mono = np.mean(a.astype(np.float64), axis=1)
    b_mono = np.mean(b.astype(np.float64), axis=1)
    a_mono -= np.mean(a_mono)
    b_mono -= np.mean(b_mono)
    b_energy = float(np.dot(b_mono, b_mono))
    a_norm = float(np.linalg.norm(a_mono))
    if b_energy <= 0.0 or a_norm <= 0.0:
        raise RecipeViolation("alignment_unresolved")
    scale = float(np.dot(a_mono, b_mono) / b_energy)
    residual = float(np.linalg.norm(a_mono - scale * b_mono) / a_norm)
    if residual > 0.99:
        raise RecipeViolation("alignment_unresolved")
    warnings: list[str] = []
    if correlation < 0.0:
        warnings.append("polarity_inverted")
    if abs(lag) > round(0.05 * sample_rate):
        warnings.append("large_alignment_shift")
    return (
        a,
        b,
        {
            "alignment_lag_frames": lag,
            "alignment_correlation": correlation,
            "alignment_normalized_residual": residual,
            "overlap_ratio": overlap_ratio,
        },
        warnings,
    )


def _matched(
    first: np.ndarray, second: np.ndarray, sample_rate: int
) -> tuple[np.ndarray, np.ndarray, dict[str, JSONValue]]:
    first_loudness = _integrated_loudness(first, sample_rate)
    second_loudness = _integrated_loudness(second, sample_rate)
    if not math.isfinite(first_loudness) or not math.isfinite(second_loudness):
        raise RecipeViolation("invalid_audio", "matched Recipe cannot prepare silent audio")
    target = (first_loudness + second_loudness) / 2.0
    first_gain = target - first_loudness
    second_gain = target - second_loudness
    a = first * np.float32(10.0 ** (first_gain / 20.0))
    b = second * np.float32(10.0 ** (second_gain / 20.0))
    peak = max(float(np.max(np.abs(a))), float(np.max(np.abs(b))))
    attenuation = 0.0
    if peak > 0.99:
        gain = 0.99 / peak
        a *= np.float32(gain)
        b *= np.float32(gain)
        attenuation = 20.0 * math.log10(gain)
    return (
        a,
        b,
        {
            "loudness_p1": first_loudness,
            "loudness_p2": second_loudness,
            "match_gain_db_p1": first_gain,
            "match_gain_db_p2": second_gain,
            "common_attenuation_db": attenuation,
        },
    )


def _input_warnings(first: DecodedAudio, second: DecodedAudio) -> list[str]:
    warnings: list[str] = []
    peaks = (float(np.max(np.abs(first.pcm))), float(np.max(np.abs(second.pcm))))
    if max(peaks) > 1.0:
        warnings.append("input_peak_over_full_scale")
    duration_a = first.frames / first.sample_rate
    duration_b = second.frames / second.sample_rate
    difference = abs(duration_a - duration_b)
    if difference > 1.0 and difference / max(duration_a, duration_b) > 0.10:
        warnings.append("large_duration_difference")
    loudness_a = _integrated_loudness(first.pcm, first.sample_rate)
    loudness_b = _integrated_loudness(second.pcm, second.sample_rate)
    if (
        math.isfinite(loudness_a)
        and math.isfinite(loudness_b)
        and abs(loudness_a - loudness_b) > 6.0
    ):
        warnings.append("large_native_level_difference")
    return warnings


def _store_audio(pcm: np.ndarray, sample_rate: int, objects: ObjectStore) -> AudioObject:
    wav = encode_float32_wav(pcm, sample_rate)
    stored = objects.put(wav)
    inspected = inspect_wav_bytes(wav)
    identity: dict[str, JSONValue] = {
        "pcm_sha": f"sha256:{inspected.sha256}",
        "sample_rate": inspected.sample_rate,
        "channel_layout": inspected.channel_layout,
        "frames": inspected.frames,
    }
    audio_id = f"audio_{canonical_sha256(identity)}"
    return AudioObject(
        id=audio_id,
        object_id=stored.object_id,
        pcm_sha=f"sha256:{inspected.sha256}",
        sample_rate=inspected.sample_rate,
        channel_layout=inspected.channel_layout,
        frames=inspected.frames,
    )


def _integrated_loudness(pcm: np.ndarray, sample_rate: int) -> float:
    weighted = _k_weight(pcm.astype(np.float64), sample_rate)
    block = max(1, round(0.4 * sample_rate))
    hop = max(1, round(0.1 * sample_rate))
    if len(weighted) < block:
        weighted = np.pad(weighted, ((0, block - len(weighted)), (0, 0)))
    powers = np.array(
        [
            float(np.sum(np.mean(np.square(weighted[start : start + block]), axis=0)))
            for start in range(0, len(weighted) - block + 1, hop)
        ]
    )
    loudness = np.full_like(powers, -math.inf)
    positive = powers > 0.0
    loudness[positive] = -0.691 + 10.0 * np.log10(powers[positive])
    absolute = loudness > -70.0
    if not np.any(absolute):
        return -math.inf
    threshold = -0.691 + 10.0 * math.log10(float(np.mean(powers[absolute]))) - 10.0
    gated = absolute & (loudness > threshold)
    if not np.any(gated):
        return -math.inf
    return -0.691 + 10.0 * math.log10(float(np.mean(powers[gated])))


def _k_weight(pcm: np.ndarray, sample_rate: int) -> np.ndarray:
    shelf_b, shelf_a = _high_shelf(sample_rate)
    high_b, high_a = _high_pass(sample_rate)
    weighted = cast(np.ndarray, signal.lfilter(shelf_b, shelf_a, pcm, axis=0))  # pyright: ignore[reportUnknownMemberType]
    return cast(np.ndarray, signal.lfilter(high_b, high_a, weighted, axis=0))  # pyright: ignore[reportUnknownMemberType]


def _high_shelf(sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    frequency, gain_db, quality = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * frequency / sample_rate)
    vh, vb = 10.0 ** (gain_db / 20.0), 10.0 ** (gain_db / 20.0) ** 0.4996667741545416
    denominator = 1.0 + k / quality + k * k
    return (
        np.array(
            [
                (vh + vb * k / quality + k * k) / denominator,
                2.0 * (k * k - vh) / denominator,
                (vh - vb * k / quality + k * k) / denominator,
            ]
        ),
        np.array(
            [1.0, 2.0 * (k * k - 1.0) / denominator, (1.0 - k / quality + k * k) / denominator]
        ),
    )


def _high_pass(sample_rate: int) -> tuple[np.ndarray, np.ndarray]:
    frequency, quality = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * frequency / sample_rate)
    denominator = 1.0 + k / quality + k * k
    return (
        np.array([1.0 / denominator, -2.0 / denominator, 1.0 / denominator]),
        np.array(
            [1.0, 2.0 * (k * k - 1.0) / denominator, (1.0 - k / quality + k * k) / denominator]
        ),
    )
