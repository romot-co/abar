from collections.abc import Callable
from pathlib import Path

import pytest

from abar.app import commands
from abar.app.repository import WorkspaceRepository
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
