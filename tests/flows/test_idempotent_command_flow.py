from collections.abc import Callable
from pathlib import Path

import pytest

from abar.app import commands
from abar.app.repository import WorkspaceRepository


def test_brief_retry_is_idempotent_and_conflicting_request_is_rejected(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(
        repository,
        name="Product",
        brief="initial",
        material_paths=(wav_file("source.wav", 220.0),),
    )
    commands.change_brief(
        repository,
        text="new brief",
        human_quote="new brief",
        actor_id="human",
        idempotency_key="brief-change",
    )
    count = len(repository.events.read_all())
    commands.change_brief(
        repository,
        text="new brief",
        human_quote="new brief",
        actor_id="human",
        idempotency_key="brief-change",
    )
    assert len(repository.events.read_all()) == count
    with pytest.raises(commands.CommandError):
        commands.change_brief(
            repository,
            text="different",
            human_quote="different",
            actor_id="human",
            idempotency_key="brief-change",
        )
