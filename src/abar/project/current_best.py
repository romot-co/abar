"""The only automatic rule that may advance Project current best."""

from abar.project.models import (
    BestEvidence,
    BestUpdateDecision,
    BestUpdatePlan,
    CurrentAuthoritySnapshot,
)


def evaluate_best_update(
    authority: CurrentAuthoritySnapshot,
    plan: BestUpdatePlan,
    evidence: tuple[BestEvidence, BestEvidence, BestEvidence],
) -> BestUpdateDecision:
    expected = set(plan.evidence_item_ids)
    actual = [item.item_id for item in evidence]
    scores = [item.score_for_proposed for item in evidence]
    numeric = [score for score in scores if score is not None]
    score_sum = sum(numeric)
    positive_count = sum(score > 0 for score in numeric)
    if len(set(actual)) != 3 or set(actual) != expected:
        return BestUpdateDecision(False, "evidence_mismatch", score_sum, positive_count)
    if len(numeric) != 3:
        return BestUpdateDecision(False, "evidence_incomplete", score_sum, positive_count)
    if any(item.proposed_blocked for item in evidence):
        return BestUpdateDecision(False, "proposed_blocked", score_sum, positive_count)
    if any(item.identity_visible_at_answer is not False for item in evidence):
        return BestUpdateDecision(False, "identity_was_visible", score_sum, positive_count)
    if authority.current_best != plan.incumbent_variant_id:
        return BestUpdateDecision(False, "current_best_changed", score_sum, positive_count)
    if authority.brief_revision != plan.brief_revision:
        return BestUpdateDecision(False, "brief_changed", score_sum, positive_count)
    if authority.primary_recipe != plan.recipe_snapshot:
        return BestUpdateDecision(False, "recipe_changed", score_sum, positive_count)
    if (
        max(
            authority.last_current_best_change_seq,
            authority.last_brief_change_seq,
            authority.last_primary_recipe_change_seq,
        )
        > plan.created_event_seq
    ):
        return BestUpdateDecision(False, "plan_stale", score_sum, positive_count)
    if positive_count < 2 or score_sum <= 0:
        return BestUpdateDecision(False, "preference_threshold_not_met", score_sum, positive_count)
    return BestUpdateDecision(True, "conditions_met", score_sum, positive_count)
