"""Commands validated against a stale projection must never commit.

Each test lets a second writer commit between a command's validation and its write
transaction, which is what two browser tabs, a double submit, or the UI racing an
agent CLI produce. The Workspace must stay replayable and every rule must hold.
"""

from collections.abc import Callable, Generator, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path

import pytest

from abar.app import commands
from abar.app.repository import WorkspaceRepository
from abar.infrastructure.sqlite_event_store import (
    ConcurrentWriteError,
    EventStore,
    EventTransaction,
)
from tests.conftest import persist_finite_variant

type Interleave = Callable[[Callable[[], None]], None]


@pytest.fixture
def interleave(monkeypatch: pytest.MonkeyPatch) -> Iterator[Interleave]:
    """Run a competing write right before the next write transaction begins."""

    pending: list[Callable[[], None]] = []
    original = EventStore.transaction

    def gated(
        self: EventStore, *, causation_id: str | None = None
    ) -> AbstractContextManager[EventTransaction]:
        if pending:
            pending.pop()()
        return original(self, causation_id=causation_id)

    monkeypatch.setattr(EventStore, "transaction", gated)
    yield pending.append


@contextmanager
def other_writer(repository: WorkspaceRepository) -> Generator[WorkspaceRepository]:
    other = WorkspaceRepository.open(repository.root)
    try:
        yield other
    finally:
        other.close()


def _observation_delivery(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]
) -> tuple[str, str]:
    commands.init_project(
        repository, name="P", brief="b", material_paths=(wav_file("s.wav", 220.0),)
    )
    proposed = persist_finite_variant(repository, label="Proposal", same_as_source=False)
    project_session_id = commands.create_observation_session(
        repository,
        first_variant="source",
        second_variant=proposed,
        focus="f",
        actor_id="agent-1",
    )
    core = repository.state().research.project_sessions[project_session_id].core_session_id
    commands.start_session(repository, core, allocation_seed=1)
    delivery = next(
        item for item in repository.state().compare.deliveries.values() if item.session_id == core
    )
    return core, delivery.id


def test_transaction_refuses_to_commit_on_a_stale_projection(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]
) -> None:
    commands.init_project(
        repository, name="P", brief="b", material_paths=(wav_file("s.wav", 220.0),)
    )
    repository.state()
    with other_writer(repository) as other:
        commands.write_note(other, "written elsewhere", actor_id="agent-1")

    with pytest.raises(ConcurrentWriteError), repository.events.transaction():
        pass
    repository.state()
    with repository.events.transaction():
        pass


def test_double_submitted_answer_is_recorded_once(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    interleave: Interleave,
) -> None:
    session_id, delivery_id = _observation_delivery(repository, wav_file)

    with other_writer(repository) as other:
        interleave(lambda: _answer(other, delivery_id))
        with pytest.raises(commands.CommandError) as rejected:
            commands.record_judgment(repository, delivery_id, preference=5)

    assert rejected.value.code == "judgment_already_recorded"
    state = repository.state()
    assert state.compare.session_runtime[session_id].status == "ended"
    types = [event.event_type for event in repository.events.read_all()]
    assert types.count("judgment.recorded") == 1
    assert types.count("session.ended") == 1
    assert types.count("session.revealed") == 1


def test_concurrent_retry_with_the_same_key_returns_the_first_result(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    interleave: Interleave,
) -> None:
    _session_id, delivery_id = _observation_delivery(repository, wav_file)
    recorded: list[str] = []

    with other_writer(repository) as other:
        interleave(
            lambda: recorded.append(
                commands.record_judgment(other, delivery_id, preference=5, idempotency_key="k")
            )
        )
        retried = commands.record_judgment(
            repository, delivery_id, preference=5, idempotency_key="k"
        )

    assert retried == recorded[0]
    repository.state()


def test_answer_and_skip_of_the_same_delivery_cannot_both_commit(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    interleave: Interleave,
) -> None:
    session_id, delivery_id = _observation_delivery(repository, wav_file)

    with other_writer(repository) as other:
        interleave(lambda: _answer(other, delivery_id))
        with pytest.raises(commands.CommandError) as rejected:
            commands.skip_delivery(repository, delivery_id, confirmed=True)

    assert rejected.value.code in {"delivery_already_answered", "session_not_active"}
    state = repository.state()
    assert not state.compare.session_runtime[session_id].skipped_item_ids


def test_brief_change_racing_the_final_answer_blocks_promotion(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    interleave: Interleave,
) -> None:
    commands.init_project(
        repository,
        name="Xifa",
        brief="denser without losing attack",
        material_paths=(wav_file("vocal.wav", 220.0), wav_file("drums.wav", 330.0)),
    )
    project = repository.state().project.project
    assert project is not None
    commands.add_clip(repository, project.material_ids[0], start_seconds=1.0, duration_seconds=2.0)
    proposed = persist_finite_variant(repository, label="proposal", same_as_source=False)
    project_session_id = commands.create_best_update_session(
        repository, proposed_variant=proposed, actor_id="agent-1"
    )
    project_session = repository.state().research.project_sessions[project_session_id]
    commands.start_session(repository, project_session.core_session_id, allocation_seed=4)

    with other_writer(repository) as other:
        for index, item_id in enumerate(project_session.evidence_item_ids):
            state = repository.state()
            delivery = next(
                item
                for item in state.compare.deliveries.values()
                if item.session_item_id == item_id
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
            if index == 2:
                interleave(lambda: _change_brief(other))
            commands.record_judgment(
                repository, delivery.id, preference=1 if proposed_slot == "A" else 5
            )

    state = repository.state()
    assert state.project.project is not None
    assert state.project.project.brief_revision == 2
    assert state.project.project.current_best_variant_id == "source"
    assert state.compare.session_runtime[project_session.core_session_id].status == "ended"


def _answer(repository: WorkspaceRepository, delivery_id: str) -> None:
    commands.record_judgment(repository, delivery_id, preference=1)


def _change_brief(repository: WorkspaceRepository) -> None:
    commands.change_brief(
        repository, text="a new purpose", human_quote="new purpose", actor_id="human"
    )
