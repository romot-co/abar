from collections.abc import Callable
from pathlib import Path

from abar.app import commands
from abar.app.actors import Actor
from abar.app.repository import WorkspaceRepository
from tests.conftest import persist_finite_variant


def test_byte_identical_simplification_requires_human_acceptance(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(
        repository,
        name="Product",
        brief="keep the sound",
        material_paths=(wav_file("source.wav", 220.0),),
    )
    simple = persist_finite_variant(repository, label="simple", same_as_source=True)
    state = repository.state()
    clip_id = next(iter(state.compare.clips))
    plan_id = commands.create_simplification(
        repository,
        simple_variant_id=simple,
        reason="fewer processing stages",
        scope_clip_ids=(clip_id,),
    )
    assert repository.state().project.project.current_best_variant_id == "source"  # type: ignore[union-attr]
    commands.decide_simplification(
        repository, plan_id, decision="accept", actor=Actor("human", "human")
    )
    assert repository.state().project.project.current_best_variant_id == simple  # type: ignore[union-attr]
