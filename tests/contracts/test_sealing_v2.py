from abar.compare.models import (
    ComparisonPlan,
    Delivery,
    RecipeRef,
    ResolvedOperand,
    Session,
    SessionItem,
)
from abar.compare.sealing import public_delivery


def test_blind_delivery_hides_identity_until_reveal() -> None:
    comparison = ComparisonPlan(
        "cmp",
        (
            ResolvedOperand("p1", "audio_1", {"variant_ref": "v_1"}),
            ResolvedOperand("p2", "audio_2", {"variant_ref": "v_2"}),
        ),
        RecipeRef(),
        "pp",
    )
    session = Session("ses", (SessionItem("item", "cmp", 0),), "blind", "on_end", None)
    delivery = Delivery("d", "ses", "item", "cmp", {"A": "p2", "B": "p1"}, "blind", 0)
    sealed = public_delivery(
        session, delivery, comparison, session_revealed=False, delivery_answered=True
    )
    revealed = public_delivery(
        session, delivery, comparison, session_revealed=True, delivery_answered=True
    )
    assert sealed.identity_by_slot is None
    assert revealed.identity_by_slot is not None
