"""Seeded random evidence Clip selection."""

import random
from collections.abc import Mapping
from dataclasses import dataclass

from abar.compare.models import Clip, Material


@dataclass(frozen=True, slots=True)
class EvidenceClipSelection:
    clip_ids: tuple[str, ...]
    algorithm_id: str
    algorithm_version: int
    seed: int | None


def explicit_selection(clip_ids: tuple[str, ...]) -> EvidenceClipSelection:
    return EvidenceClipSelection(clip_ids, "explicit", 1, None)


def random_selection(
    *,
    material_ids: tuple[str, ...],
    materials: Mapping[str, Material],
    clips: Mapping[str, Clip],
    count: int,
    seed: int,
) -> EvidenceClipSelection:
    """Select distinct Clips randomly while preserving the two-Material rule."""

    by_material = {
        material_id: tuple(
            sorted(clip_id for clip_id in materials[material_id].clip_ids if clip_id in clips)
        )
        for material_id in sorted(material_ids)
    }
    by_material = {key: value for key, value in by_material.items() if value}
    eligible = tuple(clip_id for values in by_material.values() for clip_id in values)
    if len(eligible) < count:
        raise ValueError("not enough eligible Clips")

    generator = random.Random(seed)
    algorithm_version = 1
    if count == 3 and len(by_material) >= 2:
        first_material, second_material = generator.sample(tuple(by_material), 2)
        selected = [
            generator.choice(by_material[first_material]),
            generator.choice(by_material[second_material]),
        ]
        remaining = tuple(clip_id for clip_id in eligible if clip_id not in selected)
        selected.append(generator.choice(remaining))
        generator.shuffle(selected)
    elif count > 3:
        algorithm_version = 2
        material_order = list(by_material)
        generator.shuffle(material_order)
        selected = [generator.choice(by_material[item]) for item in material_order[:count]]
        if len(selected) < count:
            remaining = tuple(clip_id for clip_id in eligible if clip_id not in selected)
            selected.extend(generator.sample(remaining, count - len(selected)))
        generator.shuffle(selected)
    else:
        selected = generator.sample(eligible, count)
    return EvidenceClipSelection(tuple(selected), "uniform-random", algorithm_version, seed)
