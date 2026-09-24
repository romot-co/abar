from collections.abc import Callable
from pathlib import Path

import pytest

from abar.app import commands, queries
from abar.app.repository import WorkspaceRepository
from abar.app.views import ActiveDeckView
from abar.compare.models import RecipeRef


def test_quick_listen_uses_core_session_and_reveals_after_answer(
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
    state = repository.state()
    delivery_id = state.compare.session_runtime[session_id].deliveries[0]
    commands.record_judgment(repository, delivery_id, preference=3)
    state = repository.state()
    assert state.compare.session_runtime[session_id].status == "ended"
    assert state.compare.session_runtime[session_id].revealed
    assert not state.research.project_sessions

    with pytest.raises(commands.CommandError, match="immutable once recorded"):
        commands.record_judgment(repository, delivery_id, preference=1)


def test_only_one_core_session_can_be_active(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    first = commands.create_quick_listen(
        repository,
        str(wav_file("first-a.wav", 220.0)),
        str(wav_file("first-b.wav", 330.0)),
        recipe=RecipeRef("native"),
    )
    second = commands.create_quick_listen(
        repository,
        str(wav_file("second-a.wav", 440.0)),
        str(wav_file("second-b.wav", 550.0)),
        recipe=RecipeRef("native"),
    )

    commands.start_session(repository, first, allocation_seed=1)
    with pytest.raises(commands.CommandError) as raised:
        commands.start_session(repository, second, allocation_seed=2)

    assert raised.value.code == "session_already_active"
    state = repository.state()
    assert state.compare.session_runtime[first].status == "active"
    assert state.compare.session_runtime[second].status == "ready"


@pytest.mark.parametrize("ending", ["skip", "abandon"])
def test_blind_quick_listen_reveals_however_it_ends(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    ending: str,
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
    if ending == "skip":
        commands.skip_delivery(repository, delivery_id)
    else:
        commands.abandon_session(repository, session_id)

    runtime = repository.state().compare.session_runtime[session_id]
    assert runtime.status == "ended"
    assert runtime.revealed


def test_blind_quick_listen_offers_reveal_only_until_revealed(
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

    def deck() -> ActiveDeckView:
        return queries.active_deck(repository, audio_url=lambda d, s, _a: f"/{d}/{s}")

    assert deck().can_reveal
    commands.reveal_session(repository, session_id)
    assert not deck().can_reveal
    assert deck().identity_by_slot is not None
