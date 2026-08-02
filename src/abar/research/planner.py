"""Pure Project Session ordering and fingerprint rules."""

from dataclasses import dataclass

from abar.compare.models import RecipeRef
from abar.foundation.canonical_json import canonical_sha256
from abar.foundation.json_types import JSONValue


@dataclass(frozen=True, slots=True)
class PlannedRole:
    role: str
    evidence_index: int


def item_roles(
    size: str, *, same_check: bool = False, repeat_check: bool = False
) -> tuple[PlannedRole, ...]:
    if size not in {"short", "standard"}:
        raise ValueError("Session size must be short or standard")
    roles: list[PlannedRole] = [PlannedRole("evidence", 0)]
    if same_check:
        roles.append(PlannedRole("same", 0))
    if size == "standard":
        roles.extend((PlannedRole("evidence", 1), PlannedRole("evidence", 2)))
    if repeat_check:
        roles.append(PlannedRole("repeat", 0))
    return tuple(roles)


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
