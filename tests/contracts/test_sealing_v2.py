from collections.abc import Callable
from pathlib import Path
from typing import cast

from abar.app import commands
from abar.app.agent_queries import entity
from abar.app.repository import WorkspaceRepository
from abar.compare.models import (
    ComparisonPlan,
    Delivery,
    RecipeRef,
    ResolvedOperand,
    Session,
    SessionItem,
)
from abar.compare.sealing import public_delivery
from tests.conftest import persist_finite_variant


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
    delivery = Delivery("d", "ses", "item", "cmp", {"A": "p2", "B": "p1"}, 0)
    sealed = public_delivery(
        session, delivery, comparison, session_revealed=False, delivery_answered=True
    )
    revealed = public_delivery(
        session, delivery, comparison, session_revealed=True, delivery_answered=True
    )
    assert sealed.identity_by_slot is None
    assert revealed.identity_by_slot is not None


def test_raw_entities_do_not_reveal_assignment_or_roles_before_session_end(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(
        repository,
        name="Xifa",
        brief="denser",
        material_paths=(wav_file("vocal.wav", 220.0), wav_file("drums.wav", 330.0)),
    )
    proposed = persist_finite_variant(repository, label="proposal", same_as_source=False)
    project_session_id = commands.create_observation_session(
        repository,
        first_variant="source",
        second_variant=proposed,
        focus="attack",
        same_check=True,
        repeat_check=True,
        actor_id="agent-1",
    )
    project_session = repository.state().research.project_sessions[project_session_id]
    session_id = project_session.core_session_id
    commands.start_session(repository, session_id, allocation_seed=3)
    deliveries = [
        item
        for item in repository.state().compare.deliveries.values()
        if item.session_id == session_id
    ]
    commands.record_judgment(repository, deliveries[0].id, preference=2)

    for delivery in deliveries:
        document = entity(repository, delivery.id).document
        assert document["slot_assignment"] is None
        assert document["comparison_id"] is None
        assert document["session_item_id"] is None
    session_document = entity(repository, session_id).document
    items = cast(list[dict[str, object]], session_document["items"])
    assert all(item["comparison_id"] is None for item in items)
    ps_document = entity(repository, project_session_id).document
    assert ps_document["evidence_item_ids"] is None
    assert ps_document["same_check_item_id"] is None
    assert ps_document["repeat_check_item_id"] is None

    for delivery in deliveries[1:]:
        commands.skip_delivery(repository, delivery.id)
    assert repository.state().compare.session_runtime[session_id].revealed
    revealed = entity(repository, deliveries[0].id).document
    assert revealed["slot_assignment"] == deliveries[0].slot_assignment
    assert "sealed_fields" not in revealed
    assert entity(repository, project_session_id).document["same_check_item_id"] is not None


def test_blind_quick_listen_delivery_reveals_assignment_after_its_answer(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    session_id = commands.create_quick_listen(
        repository,
        str(wav_file("a.wav", 220.0)),
        str(wav_file("b.wav", 330.0)),
        recipe=RecipeRef("native"),
        presentation="blind",
    )
    commands.start_session(repository, session_id, allocation_seed=1)
    delivery_id = repository.state().compare.session_runtime[session_id].deliveries[0]
    assert entity(repository, delivery_id).document["slot_assignment"] is None
    commands.record_judgment(repository, delivery_id, preference=3)
    assert entity(repository, delivery_id).document["slot_assignment"] is not None
