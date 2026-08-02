from abar.compare.models import RecipeRef
from abar.project.current_best import evaluate_best_update
from abar.project.models import BestEvidence, BestUpdatePlan, CurrentAuthoritySnapshot


def _plan() -> BestUpdatePlan:
    return BestUpdatePlan(
        "best_1",
        "prj_1",
        "ses_1",
        "v_old",
        "v_new",
        ("i1", "i2", "i3"),
        2,
        "brief",
        RecipeRef("matched"),
        20,
    )


def test_only_sealed_complete_positive_evidence_updates() -> None:
    plan = _plan()
    authority = CurrentAuthoritySnapshot("v_old", 10, 2, 10, RecipeRef("matched"), 10)
    evidence = (
        BestEvidence("i1", 2, False, False),
        BestEvidence("i2", 1, False, False),
        BestEvidence("i3", -1, False, False),
    )
    assert evaluate_best_update(authority, plan, evidence).update


def test_blocker_or_stale_authority_prevents_update() -> None:
    plan = _plan()
    stale = CurrentAuthoritySnapshot("v_old", 21, 2, 10, RecipeRef("matched"), 10)
    evidence = (
        BestEvidence("i1", 2, False, False),
        BestEvidence("i2", 1, True, False),
        BestEvidence("i3", 1, False, False),
    )
    assert not evaluate_best_update(stale, plan, evidence).update
