"""Comparison and Core Session planning identities."""

import random

from abar.compare.models import (
    ComparisonPlan,
    CriterionSnapshot,
    Delivery,
    PreparedPair,
    RecipeRef,
    ResolvedOperand,
    Session,
    SessionItem,
)
from abar.foundation.canonical_json import canonical_sha256
from abar.foundation.json_types import JSONValue
from abar.foundation.time_ids import new_id


def comparison_plan(
    first: ResolvedOperand,
    second: ResolvedOperand,
    prepared: PreparedPair,
    recipe: RecipeRef,
) -> ComparisonPlan:
    identity_document: dict[str, JSONValue] = {
        "p1": {"audio_id": first.audio_id, "provenance_ref": first.provenance_ref},
        "p2": {"audio_id": second.audio_id, "provenance_ref": second.provenance_ref},
        "prepared_pair_id": prepared.id,
    }
    identity = canonical_sha256(identity_document)
    return ComparisonPlan(
        id=f"cmp_{identity}",
        pair=(first, second),
        recipe=recipe,
        prepared_pair_id=prepared.id,
    )


def core_session(
    comparison_ids: tuple[str, ...],
    *,
    presentation: str,
    reveal_policy: str,
    criterion: CriterionSnapshot | None,
    session_id: str | None = None,
) -> Session:
    selected_id = session_id or new_id("ses_")
    items = tuple(
        SessionItem(
            id=f"item_{canonical_sha256(_item_identity(selected_id, index, comparison_id))}",
            comparison_id=comparison_id,
            sequence_index=index,
        )
        for index, comparison_id in enumerate(comparison_ids)
    )
    return Session(
        id=selected_id,
        items=items,
        presentation=presentation,  # type: ignore[arg-type]
        reveal_policy=reveal_policy,  # type: ignore[arg-type]
        criterion=criterion,
    )


def _item_identity(session_id: str, index: int, comparison_id: str) -> dict[str, JSONValue]:
    return {
        "session_id": session_id,
        "sequence_index": index,
        "comparison_id": comparison_id,
    }


def allocate_deliveries(
    session: Session,
    *,
    seed: int,
    assignment_overrides: dict[str, dict[str, str]] | None = None,
) -> tuple[Delivery, ...]:
    randomizer = random.Random(seed)
    assignments: list[dict[str, str]] = []
    p1_as_a = 0
    p2_as_a = 0
    for item in session.items:
        override = (assignment_overrides or {}).get(item.id)
        if override is not None:
            assignment = override
        elif p1_as_a < p2_as_a:
            assignment = {"A": "p1", "B": "p2"}
        elif p2_as_a < p1_as_a:
            assignment = {"A": "p2", "B": "p1"}
        elif randomizer.randrange(2) == 0:
            assignment = {"A": "p1", "B": "p2"}
        else:
            assignment = {"A": "p2", "B": "p1"}
        p1_as_a += assignment["A"] == "p1"
        p2_as_a += assignment["A"] == "p2"
        assignments.append(assignment)
    return tuple(
        Delivery(
            id=new_id("d_"),
            session_id=session.id,
            session_item_id=item.id,
            comparison_id=item.comparison_id,
            slot_assignment=assignment,  # type: ignore[arg-type]
            sequence_index=item.sequence_index,
        )
        for item, assignment in zip(session.items, assignments, strict=True)
    )
