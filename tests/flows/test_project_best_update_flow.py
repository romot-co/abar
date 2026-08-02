from collections.abc import Callable
from pathlib import Path

import pytest

from abar.app import commands, queries
from abar.app.repository import WorkspaceRepository
from tests.conftest import persist_finite_variant


def test_standard_plan_updates_current_best_only_after_three_evidence_answers(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    first = wav_file("vocal.wav", 220.0)
    second = wav_file("drums.wav", 330.0)
    commands.init_project(
        repository,
        name="Xifa",
        brief="denser without losing attack",
        material_paths=(first, second),
    )
    state = repository.state()
    materials = tuple(state.project.project.material_ids)  # type: ignore[union-attr]
    commands.add_clip(
        repository, materials[0], start_seconds=1.0, duration_seconds=2.0, role="transient"
    )
    proposed = persist_finite_variant(repository, label="proposal", same_as_source=False)
    project_session_id = commands.create_best_update_session(
        repository,
        proposed_variant=proposed,
        actor_id="agent-1",
    )
    state = repository.state()
    project_session = state.research.project_sessions[project_session_id]
    commands.start_session(repository, project_session.core_session_id, allocation_seed=4)
    for item_id in project_session.evidence_item_ids:
        state = repository.state()
        delivery = next(
            item for item in state.compare.deliveries.values() if item.session_item_id == item_id
        )
        comparison = state.compare.comparisons[delivery.comparison_id]
        proposed_key = next(
            operand.input_key
            for operand in comparison.pair
            if operand.provenance_ref.get("variant_ref") == proposed
        )
        proposed_slot = next(
            slot for slot, key in delivery.slot_assignment.items() if key == proposed_key
        )
        commands.record_judgment(
            repository, delivery.id, preference=1 if proposed_slot == "A" else 5
        )
    assert repository.state().project.project.current_best_variant_id == proposed  # type: ignore[union-attr]
    result = queries.session_result(repository, project_session_id)
    assert result.best_update_evidence is not None
    assert result.best_update_evidence.favorable_count == 3
    assert result.best_update_evidence.answered_count == 3
    assert result.best_update_evidence.score_sum == 6
    assert result.best_update_evidence.blocker_count == 0
    assert len(result.evidence) == 3
    assert {item.material_name for item in result.evidence} == {"vocal.wav", "drums.wav"}
    assert all(item.favored_variant_id == proposed for item in result.evidence)
    project_view = queries.project_view(repository)
    assert project_view.current_best_evidence == result.best_update_evidence


def test_answering_a_skipped_item_before_session_end_clears_incomplete_state(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(
        repository,
        name="Xifa",
        brief="denser without losing attack",
        material_paths=(wav_file("voice.wav", 220.0), wav_file("beat.wav", 330.0)),
    )
    project = repository.state().project.project
    assert project is not None
    commands.add_clip(
        repository,
        project.material_ids[0],
        start_seconds=1.0,
        duration_seconds=2.0,
        role="transient",
    )
    proposed = persist_finite_variant(repository, label="proposal", same_as_source=False)
    project_session_id = commands.create_best_update_session(
        repository,
        proposed_variant=proposed,
        actor_id="agent-1",
    )
    project_session = repository.state().research.project_sessions[project_session_id]
    session_id = project_session.core_session_id
    commands.start_session(repository, session_id, allocation_seed=4)
    deliveries = tuple(
        item
        for item in repository.state().compare.deliveries.values()
        if item.session_id == session_id
    )

    commands.skip_delivery(repository, deliveries[0].id, confirmed=True)
    commands.record_judgment(repository, deliveries[0].id, preference=3)
    state = repository.state()
    assert (
        deliveries[0].session_item_id
        not in state.compare.session_runtime[session_id].skipped_item_ids
    )

    with pytest.raises(commands.CommandError, match="answered Delivery cannot be skipped"):
        commands.skip_delivery(repository, deliveries[0].id, confirmed=True)

    for delivery in deliveries[1:]:
        commands.record_judgment(repository, delivery.id, preference=3)
    runtime = repository.state().compare.session_runtime[session_id]
    assert runtime.status == "ended"
    assert runtime.outcome == "completed"
