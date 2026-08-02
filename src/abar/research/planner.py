"""Pure Project Session ordering and fingerprint rules."""

import random
from dataclasses import dataclass

from abar.compare.models import RecipeRef
from abar.foundation.canonical_json import canonical_sha256
from abar.foundation.json_types import JSONValue
from abar.research.models import ProjectSession
from abar.research.session_sizes import resolve_evidence_count


@dataclass(frozen=True, slots=True)
class PlannedRole:
    role: str
    evidence_index: int


def item_roles(
    size: str,
    *,
    evidence_count: int | None = None,
    same_check: bool = False,
    repeat_check: bool = False,
) -> tuple[PlannedRole, ...]:
    count = resolve_evidence_count(size, evidence_count)
    roles: list[PlannedRole] = [PlannedRole("evidence", 0)]
    if same_check:
        roles.append(PlannedRole("same", 0))
    roles.extend(PlannedRole("evidence", index) for index in range(1, count))
    if repeat_check:
        roles.append(PlannedRole("repeat", 0))
    return tuple(roles)


def presentation_order(project_session: ProjectSession, *, seed: int) -> tuple[str, ...]:
    """Return a deterministic blind presentation order with separated checks."""

    randomizer = random.Random(seed ^ 0x50524553454E54)
    evidence = list(project_session.evidence_item_ids)
    repeated = project_session.repeat_of_item_id
    if project_session.repeat_check_item_id is not None and repeated in evidence:
        evidence.remove(repeated)
        randomizer.shuffle(evidence)
        if project_session.size == "standard":
            original_index = randomizer.randrange(max(1, len(evidence) - 1))
        else:
            original_index = 0
        evidence.insert(original_index, repeated)
    else:
        randomizer.shuffle(evidence)

    ordered = evidence
    repeat = project_session.repeat_check_item_id
    if repeat is not None and repeated is not None:
        original_index = ordered.index(repeated)
        minimum_gap = 2 if project_session.size == "standard" else 0
        earliest = min(len(ordered), original_index + minimum_gap + 1)
        repeat_index = randomizer.randrange(earliest, len(ordered) + 1)
        ordered.insert(repeat_index, repeat)

    same = project_session.same_check_item_id
    if same is not None:
        ordered.insert(randomizer.randrange(1, len(ordered) + 1), same)
    return tuple(ordered)


def observation_session_fingerprint(
    *,
    pair: tuple[str, str],
    focus: str,
    evidence_clip_ids: tuple[str, ...],
    recipe: RecipeRef,
    same_check: bool,
    repeat_check: bool,
) -> str:
    document: dict[str, JSONValue] = {
        "kind": "observation",
        "pair": list(pair),
        "focus": " ".join(focus.split()),
        "evidence_clip_ids": list(sorted(evidence_clip_ids)),
        "recipe": {"id": recipe.id, "version": recipe.version, "config": recipe.config},
        "same_check": same_check,
        "repeat_check": repeat_check,
    }
    return canonical_sha256(document)


def best_update_session_fingerprint(
    *,
    brief_revision: int,
    incumbent_variant_id: str,
    proposed_variant_id: str,
    evidence_clip_ids: tuple[str, ...],
    recipe: RecipeRef,
) -> str:
    document: dict[str, JSONValue] = {
        "kind": "best_update",
        "brief_revision": brief_revision,
        "incumbent_variant_id": incumbent_variant_id,
        "proposed_variant_id": proposed_variant_id,
        "evidence_clip_ids": list(sorted(evidence_clip_ids)),
        "recipe": {"id": recipe.id, "version": recipe.version, "config": recipe.config},
    }
    return canonical_sha256(document)
