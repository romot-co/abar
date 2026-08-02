from abar.compare.models import Clip, Material
from abar.research.clip_selection import random_selection


def test_random_clip_selection_is_seeded_and_spans_materials() -> None:
    clips = {
        "c1": Clip("c1", "m1", 0, 100),
        "c2": Clip("c2", "m1", 100, 100),
        "c3": Clip("c3", "m2", 0, 100),
        "c4": Clip("c4", "m2", 100, 100),
    }
    materials = {
        "m1": Material("m1", "one", "a1", clip_ids=("c1", "c2")),
        "m2": Material("m2", "two", "a2", clip_ids=("c3", "c4")),
    }

    first = random_selection(
        material_ids=("m1", "m2"),
        materials=materials,
        clips=clips,
        count=3,
        seed=72,
    )
    repeated = random_selection(
        material_ids=("m1", "m2"),
        materials=materials,
        clips=clips,
        count=3,
        seed=72,
    )

    assert first == repeated
    assert len(set(first.clip_ids)) == 3
    assert {clips[clip_id].material_id for clip_id in first.clip_ids} == {"m1", "m2"}
    assert first.algorithm_id == "uniform-random"
    assert first.algorithm_version == 1
    assert first.seed == 72


def test_ten_item_selection_prefers_one_clip_per_material() -> None:
    clips = {f"c{index}": Clip(f"c{index}", f"m{index}", 0, 100) for index in range(12)}
    materials = {
        f"m{index}": Material(
            f"m{index}",
            f"material-{index}",
            f"a{index}",
            clip_ids=(f"c{index}",),
        )
        for index in range(12)
    }

    first = random_selection(
        material_ids=tuple(materials),
        materials=materials,
        clips=clips,
        count=10,
        seed=73,
    )
    repeated = random_selection(
        material_ids=tuple(materials),
        materials=materials,
        clips=clips,
        count=10,
        seed=73,
    )

    assert first == repeated
    assert len(first.clip_ids) == 10
    assert len({clips[clip_id].material_id for clip_id in first.clip_ids}) == 10
    assert first.algorithm_id == "uniform-random"
    assert first.algorithm_version == 2
