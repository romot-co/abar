"""Shared presentation helpers for bounded read models."""

from typing import Literal, cast

from abar.app.state import ABARState
from abar.app.views import RevealedIdentityView, TimelineEntryView
from abar.compare.models import RecipeRef
from abar.foundation.json_types import JSONValue

type Slot = Literal["A", "B"]


def variant_label(state: ABARState, variant_id: str) -> str:
    if variant_id == "source":
        return "原音"
    variant = state.compare.variants.get(variant_id)
    if variant is None:
        return "不明な版"
    if variant.label:
        return variant.label
    provenance = state.compare.provenance.get(variant_id, ())
    if provenance:
        latest = provenance[-1]
        return str(latest.get("summary") or latest.get("reason") or "登録済みの版")
    return "登録済みの版"


def recipe_label(recipe: RecipeRef) -> str:
    return f"{recipe.id}-v{recipe.version}"


def labeled_identity(
    state: ABARState,
    identity: dict[str, dict[str, object]] | None,
) -> dict[Slot, RevealedIdentityView] | None:
    """Add labels only after the sealing boundary has allowed identity reveal."""
    if identity is None:
        return None
    output: dict[Slot, RevealedIdentityView] = {}
    for slot, value in identity.items():
        provenance = cast(dict[str, JSONValue], value["provenance"])
        kind = provenance.get("kind")
        variant_ref = provenance.get("variant_ref")
        name = provenance.get("name")
        label: str | None = None
        if kind in {"source", "variant"} and isinstance(variant_ref, str):
            label = variant_label(state, variant_ref)
        elif kind == "file" and isinstance(name, str):
            label = name
        output[cast(Slot, slot)] = RevealedIdentityView(
            audio_id=cast(str, value["audio_id"]),
            provenance=provenance,
            label=label,
        )
    return output


def timeline_entry(event_seq: int, event_type: str) -> TimelineEntryView:
    labels = {
        "project.brief.changed": "目的を更新",
        "current_best.changed": "現在最良を更新",
        "session.ended": "Sessionを完了",
        "session.memo.recorded": "Sessionメモを記録",
        "indicator.value.recorded": "指標値を記録",
    }
    return TimelineEntryView(
        event_seq=event_seq,
        event_type=event_type,
        summary=labels.get(event_type, event_type),
    )
