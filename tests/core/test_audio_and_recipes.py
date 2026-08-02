from collections.abc import Callable
from pathlib import Path

from abar.compare.audio.importing import import_input_audio_file
from abar.compare.models import RecipeRef
from abar.compare.recipes import prepare
from abar.infrastructure.object_store import ImmutableObjectStore


def test_audio_identity_is_content_based(
    tmp_path: Path,
    wav_file: Callable[[str, float], Path],
) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    path = wav_file("tone.wav", 220.0)
    first = import_input_audio_file(path, objects=store).audio
    second = import_input_audio_file(path, objects=store).audio
    assert first.id == second.id


def test_prepared_pair_identity_preserves_operand_order(
    tmp_path: Path,
    wav_file: Callable[[str, float], Path],
) -> None:
    store = ImmutableObjectStore(tmp_path / "objects")
    first = import_input_audio_file(wav_file("a.wav", 220.0), objects=store).audio
    second = import_input_audio_file(wav_file("b.wav", 330.0), objects=store).audio
    forward = prepare(first, second, RecipeRef("native"), objects=store)
    reverse = prepare(second, first, RecipeRef("native"), objects=store)
    assert forward.pair.id != reverse.pair.id
    assert (
        forward.pair.output_audio_by_input_key["p1"] == reverse.pair.output_audio_by_input_key["p2"]
    )
    assert (
        forward.pair.output_audio_by_input_key["p2"] == reverse.pair.output_audio_by_input_key["p1"]
    )
