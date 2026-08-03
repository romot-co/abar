from collections.abc import Callable
from pathlib import Path

from abar.app import commands
from abar.app.actors import Actor
from abar.app.queries import project_view
from abar.app.repository import WorkspaceRepository
from tests.conftest import persist_finite_variant


def test_note_and_indicator_are_observational_without_authority_change(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    tmp_path: Path,
) -> None:
    commands.init_project(
        repository,
        name="Product",
        brief="brief",
        material_paths=(wav_file("source.wav", 220.0),),
    )
    other_variant = persist_finite_variant(repository, label="other", same_as_source=False)
    before = repository.state().project.authority_snapshot()
    commands.write_note(repository, "## Current understanding", actor_id="agent-1")
    definition = tmp_path / "metric.py"
    definition.write_text("def metric(x): return 0.0\n", encoding="utf-8")
    commands.register_indicator(
        repository,
        indicator_id="ind_density_v1",
        label="Density",
        description="Increase perceived density without masking detail",
        definition_path=definition,
        subject_kind="audio",
        unit="ratio",
        role="target",
        actor_id="agent-1",
    )
    state = repository.state()
    density_indicator = state.research.indicators["ind_density_v1"]
    assert density_indicator.definition_ref.startswith("obj_")
    assert repository.objects.read(density_indicator.definition_ref) == definition.read_bytes()
    project = state.project.project
    assert project is not None
    subject = state.compare.materials[project.material_ids[0]].source_audio_id
    commands.record_indicator_value(
        repository,
        indicator_id="ind_density_v1",
        subject_id=subject,
        variant_id="source",
        value=0.57,
        actor=Actor("agent-1", "agent"),
    )
    commands.record_indicator_value(
        repository,
        indicator_id="ind_density_v1",
        subject_id=subject,
        variant_id=other_variant,
        value=0.99,
        actor=Actor("agent-1", "agent"),
    )
    commands.register_indicator(
        repository,
        indicator_id="ind_attack_v1",
        label="ATTACK LOSS",
        description="Check whether transient definition has been lost",
        definition_path=definition,
        subject_kind="audio",
        unit="ratio",
        role="guard",
        actor_id="agent-1",
    )
    commands.record_indicator_value(
        repository,
        indicator_id="ind_attack_v1",
        subject_id=subject,
        variant_id="source",
        value=0.9,
        guard_result="pass",
        actor=Actor("agent-1", "agent"),
    )
    commands.record_indicator_value(
        repository,
        indicator_id="ind_density_v1",
        subject_id=subject,
        variant_id="source",
        value=0.62,
        actor=Actor("agent-1", "agent"),
    )
    second_subject = commands.import_audio(repository, wav_file("indicator-second.wav", 440.0))
    commands.record_indicator_value(
        repository,
        indicator_id="ind_density_v1",
        subject_id=second_subject,
        variant_id="source",
        value=0.82,
        actor=Actor("agent-1", "agent"),
    )
    commands.record_indicator_value(
        repository,
        indicator_id="ind_attack_v1",
        subject_id=second_subject,
        variant_id="source",
        value=0.7,
        guard_result="fail",
        actor=Actor("agent-1", "agent"),
    )
    after = repository.state().project.authority_snapshot()
    assert after == before
    indicators = {item.id: item for item in project_view(repository).indicators}
    target = indicators["ind_density_v1"]
    assert target.value == 0.72
    assert target.description == "Increase perceived density without masking detail"
    guard = indicators["ind_attack_v1"]
    assert guard.value == 0.8
    assert guard.guard_result == "fail"

    commands.set_current_best_manual(
        repository,
        other_variant,
        ack="test current-best scope",
        actor=Actor("human", "human"),
    )
    switched = {item.id: item for item in project_view(repository).indicators}
    assert switched["ind_density_v1"].value == 0.99
    assert switched["ind_attack_v1"].value is None
    assert switched["ind_attack_v1"].guard_result is None
