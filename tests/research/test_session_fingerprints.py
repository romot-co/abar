from abar.compare.models import RecipeRef
from abar.research.planner import (
    best_update_session_fingerprint,
    observation_session_fingerprint,
)


def test_observation_fingerprint_includes_focus_and_checks() -> None:
    pair = ("source", "variant")
    clips = ("clip_1",)
    recipe = RecipeRef("aligned")
    base = observation_session_fingerprint(
        pair=pair,
        focus="attack",
        evidence_clip_ids=clips,
        recipe=recipe,
        same_check=False,
        repeat_check=False,
    )
    assert (
        observation_session_fingerprint(
            pair=pair,
            focus="air",
            evidence_clip_ids=clips,
            recipe=recipe,
            same_check=False,
            repeat_check=False,
        )
        != base
    )
    assert (
        observation_session_fingerprint(
            pair=pair,
            focus="attack",
            evidence_clip_ids=clips,
            recipe=recipe,
            same_check=True,
            repeat_check=False,
        )
        != base
    )
    assert (
        observation_session_fingerprint(
            pair=pair,
            focus="attack",
            evidence_clip_ids=clips,
            recipe=recipe,
            same_check=False,
            repeat_check=True,
        )
        != base
    )


def test_best_update_fingerprint_uses_authority_snapshot_not_topic_metadata() -> None:
    # topic_key is intentionally absent from this authority identity.
    base = best_update_session_fingerprint(
        brief_revision=1,
        incumbent_variant_id="source",
        proposed_variant_id="variant",
        evidence_clip_ids=("clip_1", "clip_2", "clip_3"),
        recipe=RecipeRef("matched"),
    )
    changed = best_update_session_fingerprint(
        brief_revision=2,
        incumbent_variant_id="source",
        proposed_variant_id="variant",
        evidence_clip_ids=("clip_1", "clip_2", "clip_3"),
        recipe=RecipeRef("matched"),
    )
    assert changed != base
