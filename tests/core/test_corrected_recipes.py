# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportPrivateUsage=false
import hashlib
from pathlib import Path

import numpy as np
import pytest

from abar.compare.audio.content import decode_wav_bytes, encode_float32_wav
from abar.compare.audio.importing import import_input_audio_file
from abar.compare.models import RecipeRef
from abar.compare.recipes import _integrated_loudness, _matched, prepare
from abar.infrastructure.object_store import ImmutableObjectStore


@pytest.mark.parametrize(
    "rate,frequency,reference",
    [
        (16000, 80, -25.351),
        (16000, 1000, -22.970),
        (16000, 6000, -19.580),
        (44100, 80, -25.431),
        (44100, 1000, -23.010),
        (44100, 6000, -19.670),
        (48000, 80, -25.441),
        (48000, 1000, -23.010),
        (48000, 6000, -19.680),
        (96000, 80, -25.461),
        (96000, 1000, -23.030),
        (96000, 6000, -19.700),
    ],
)
def test_corrected_loudness_against_independent_ffmpeg_reference(
    rate: int, frequency: int, reference: float
) -> None:
    # FFmpeg ebur128=metadata=1, final lavfi.r128.I for a 3-second float32 sine.
    pcm = (0.1 * np.sin(2 * np.pi * frequency * np.arange(rate * 3) / rate)).astype(np.float32)[
        :, None
    ]
    assert abs(_integrated_loudness(pcm, rate, corrected=True) - reference) < 0.011


def test_legacy_matching_remains_byte_identical() -> None:
    t = np.arange(96000) / 48000
    a = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)[:, None]
    b = (0.05 * np.sin(2 * np.pi * 330 * t)).astype(np.float32)[:, None]
    x, y, _ = _matched(a, b, 48000)
    # Captured from main 18a9136 before changing Recipes.
    assert (
        hashlib.sha256(x.tobytes() + y.tobytes()).hexdigest()
        == "e5b4b6f44f82ff3ee7cc0b6e37fc9eb75e5466f9809b7d14c9e7ca970641252f"
    )


def test_level_matching_preserves_time_origin_and_exchange_symmetry(tmp_path: Path) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    rng = np.random.default_rng(42)
    a = (0.03 * rng.normal(size=(48000, 1))).astype(np.float32)
    b = np.roll(a * 0.5, 100, axis=0)
    paths = [tmp_path / "a.wav", tmp_path / "b.wav"]
    for path, pcm in zip(paths, (a, b), strict=True):
        path.write_bytes(encode_float32_wav(pcm, 48000))
    inputs = [import_input_audio_file(path, objects=store).audio for path in paths]
    forward = prepare(inputs[0], inputs[1], RecipeRef("level-matched"), objects=store)
    reverse = prepare(inputs[1], inputs[0], RecipeRef("level-matched"), objects=store)
    assert forward.output_audio == tuple(reversed(reverse.output_audio))
    assert "alignment_lag_frames" not in forward.pair.features
    assert abs(float(str(forward.pair.features["post_match_loudness_delta_lu"]))) < 0.001
    for original, audio in zip((a, b), forward.output_audio, strict=True):
        output = decode_wav_bytes(store.read(audio.object_id)).pcm
        assert np.argmax(np.abs(output)) == np.argmax(np.abs(original))
        gain = float(output[0, 0] / original[0, 0])
        assert np.max(np.abs(output - original * gain)) < 1e-6
    assert RecipeRef.from_name("matched-v2") == RecipeRef("matched", version=2)
