from datetime import UTC, datetime

import pytest

from abar.compare.models import BlockerInput, Judgment, Telemetry
from abar.compare.planning import allocate_deliveries, core_session
from abar.compare.projection import CompareState, reduce_compare
from abar.foundation.events import EventEnvelope


def test_session_item_count_and_balanced_delivery_allocation() -> None:
    session = core_session(
        ("cmp_1", "cmp_2", "cmp_3", "cmp_4", "cmp_5"),
        presentation="blind",
        reveal_policy="on_end",
        criterion=None,
    )
    deliveries = allocate_deliveries(session, seed=7)
    p1_as_a = sum(item.slot_assignment["A"] == "p1" for item in deliveries)
    assert len(deliveries) == 5
    assert abs(p1_as_a - (len(deliveries) - p1_as_a)) <= 1


def test_judgment_allows_blocker_independent_of_preference() -> None:
    judgment = Judgment(
        "j_1",
        "d_1",
        1,
        {"a": BlockerInput(), "b": BlockerInput(True, "attack collapsed")},
        "A is preferred but B has a blocker",
        False,
        Telemetry({"a": 100, "b": 200}, 2, 500),
    )
    assert judgment.preference == 1
    assert judgment.blockers["b"].selected


def test_replay_rejects_a_second_judgment_for_the_same_delivery() -> None:
    existing = Judgment(
        "j_1",
        "d_1",
        3,
        {"a": BlockerInput(), "b": BlockerInput()},
        None,
        False,
        Telemetry({"a": 0, "b": 0}, 0, 0),
    )
    duplicate = EventEnvelope(
        event_seq=2,
        event_id="ev_2",
        event_type="judgment.recorded",
        schema_version=1,
        ts=datetime.now(UTC),
        causation_id=None,
        idempotency_key="key_2",
        payload_hash="sha256:" + "0" * 64,
        payload={
            "judgment_id": "j_2",
            "delivery_id": "d_1",
            "preference": 1,
            "blockers": {
                "a": {"selected": False, "note": None},
                "b": {"selected": False, "note": None},
            },
            "comment": None,
            "identity_visible_at_answer": False,
            "telemetry": {"listen_ms": {"a": 0, "b": 0}, "switches": 0, "answer_ms": 0},
        },
    )

    with pytest.raises(ValueError, match="immutable once recorded"):
        reduce_compare(CompareState(judgments={"d_1": existing}), duplicate)
