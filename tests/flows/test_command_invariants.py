from collections.abc import Callable
from pathlib import Path

import pytest

from abar.app import commands, queries, session_commands
from abar.app.repository import WorkspaceRepository
from abar.compare.models import RecipeRef
from tests.conftest import persist_finite_variant


def test_invalid_project_command_appends_no_events(repository: WorkspaceRepository) -> None:
    with pytest.raises(commands.CommandError) as raised:
        commands.init_project(repository, name="", brief="")
    assert raised.value.code == "invalid_project"
    assert repository.events.read_all() == ()
    assert repository.state().project.project is None


def test_idempotency_key_rejects_any_project_request_difference(
    repository: WorkspaceRepository,
) -> None:
    key = "same-operation"
    project_id = commands.init_project(
        repository, name="First", brief="first brief", idempotency_key=key
    )
    assert (
        commands.init_project(repository, name="First", brief="first brief", idempotency_key=key)
        == project_id
    )
    with pytest.raises(commands.CommandError) as raised:
        commands.init_project(repository, name="Second", brief="second brief", idempotency_key=key)
    assert raised.value.code == "idempotency_conflict"


def test_same_audio_can_be_registered_as_distinct_materials(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    path = wav_file("source.wav", 220.0)
    first = commands.add_material(repository, path, name="reference")
    second = commands.add_material(repository, path, name="evaluation")
    state = repository.state()
    assert first != second
    assert (
        state.compare.materials[first].source_audio_id
        == state.compare.materials[second].source_audio_id
    )
    assert state.compare.materials[first].name == "reference"
    assert state.compare.materials[second].name == "evaluation"


def test_variant_content_identity_cannot_overwrite_display_definition(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    material_path = wav_file("variant-source.wav", 220.0)
    commands.init_project(
        repository,
        name="Project",
        brief="Improve the sound",
        material_paths=(material_path,),
    )
    variant_id = persist_finite_variant(
        repository,
        label="First label",
        same_as_source=True,
    )
    state = repository.state()
    variant = state.compare.variants[variant_id]
    manifest = state.compare.manifests[variant.manifest_id]
    before = repository.events.read_all()

    with pytest.raises(commands.CommandError) as raised:
        commands.add_variant(repository, manifest, label="Different label")

    assert raised.value.code == "variant_definition_conflict"
    assert repository.events.read_all() == before
    assert repository.state().compare.variants[variant_id].label == "First label"


def test_project_session_close_uses_core_session_as_single_status_source(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(
        repository,
        name="Project",
        brief="Improve the sound",
        material_paths=(wav_file("close-source.wav", 220.0),),
    )
    variant_id = persist_finite_variant(
        repository,
        label="Proposal",
        same_as_source=False,
    )
    project_session_id = commands.create_observation_session(
        repository,
        first_variant="source",
        second_variant=variant_id,
        focus="Check the proposal",
        actor_id="agent-1",
    )
    project_session = repository.state().research.project_sessions[project_session_id]
    key = "close-project-session"

    commands.close_project_session(
        repository,
        project_session_id,
        actor_id="agent-1",
        idempotency_key=key,
    )
    commands.close_project_session(
        repository,
        project_session_id,
        actor_id="agent-1",
        idempotency_key=key,
    )

    state = repository.state()
    runtime = state.compare.session_runtime[project_session.core_session_id]
    assert runtime.status == "closed"
    assert runtime.outcome == "closed"
    assert [event.event_type for event in repository.events.read_operation(key)] == [
        "session.ended"
    ]
    card = next(
        item
        for item in queries.project_dashboard(repository).sessions
        if item.project_session_id == project_session_id
    )
    assert card.status == "closed"


def test_reversed_comparison_does_not_mutate_existing_plan(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    first = wav_file("a.wav", 220.0)
    second = wav_file("b.wav", 330.0)
    forward_session = commands.create_quick_listen(
        repository, f"file:{first}", f"file:{second}", recipe=RecipeRef("native")
    )
    before = repository.state()
    forward_id = before.compare.sessions[forward_session].items[0].comparison_id
    forward_plan = before.compare.comparisons[forward_id]

    reverse_session = commands.create_quick_listen(
        repository, f"file:{second}", f"file:{first}", recipe=RecipeRef("native")
    )
    after = repository.state()
    reverse_id = after.compare.sessions[reverse_session].items[0].comparison_id
    assert reverse_id != forward_id
    assert after.compare.comparisons[forward_id] == forward_plan
    assert after.compare.comparisons[reverse_id].pair[0].audio_id == forward_plan.pair[1].audio_id


def test_default_allocation_seed_is_generated_once_and_recorded(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = wav_file("seed-a.wav", 220.0)
    second = wav_file("seed-b.wav", 330.0)
    session_id = commands.create_quick_listen(
        repository, f"file:{first}", f"file:{second}", recipe=RecipeRef("native")
    )

    def fixed_seed(_bits: int) -> int:
        return 912_345

    monkeypatch.setattr(session_commands.secrets, "randbits", fixed_seed)
    key = "start-with-generated-seed"
    commands.start_session(repository, session_id, idempotency_key=key)
    commands.start_session(repository, session_id, idempotency_key=key)
    started = next(
        event
        for event in repository.events.read_operation(key)
        if event.event_type == "session.started"
    )
    assert started.payload["allocation_seed"] == 912_345


def test_invalid_best_update_appends_no_events(
    repository: WorkspaceRepository,
) -> None:
    commands.init_project(repository, name="Project", brief="Improve the sound")
    before = repository.events.read_all()
    with pytest.raises(commands.CommandError) as raised:
        commands.create_best_update_session(
            repository,
            proposed_variant="source",
            actor_id="agent-1",
        )
    assert raised.value.code == "best_update_same_variant"
    assert repository.events.read_all() == before
    assert repository.replay().degraded is None


def test_no_effect_best_update_is_rejected_before_events(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(
        repository,
        name="Project",
        brief="Improve the sound",
        material_paths=(wav_file("one.wav", 220.0), wav_file("two.wav", 330.0)),
    )
    project = repository.state().project.project
    assert project is not None
    commands.add_clip(
        repository,
        project.material_ids[0],
        start_seconds=1.0,
        duration_seconds=2.0,
    )
    proposed = persist_finite_variant(repository, label="same", same_as_source=True)
    before = repository.events.read_all()
    with pytest.raises(commands.CommandError) as raised:
        commands.create_best_update_session(
            repository,
            proposed_variant=proposed,
            actor_id="agent-1",
        )
    assert raised.value.code == "best_update_no_effect"
    assert repository.events.read_all() == before


def test_blocked_session_has_one_authoritative_status_and_does_not_consume_wip(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(
        repository,
        name="Project",
        brief="Improve the sound",
        material_paths=(wav_file("source.wav", 220.0),),
    )
    proposed = persist_finite_variant(repository, label="different", same_as_source=False)
    session_id = commands.create_observation_session(
        repository,
        first_variant="source",
        second_variant=proposed,
        focus="Listen for the difference",
        actor_id="agent-1",
    )
    state = repository.state()
    project_session = state.research.project_sessions[session_id]
    core_session = state.compare.sessions[project_session.core_session_id]
    comparison = state.compare.comparisons[core_session.items[0].comparison_id]
    prepared = state.compare.prepared_pairs[comparison.prepared_pair_id]
    audio = state.compare.audio[next(iter(prepared.output_audio_by_input_key.values()))]
    digest = audio.object_id.removeprefix("obj_")
    (repository.root / "objects" / digest[:2] / digest[2:]).unlink()

    with pytest.raises(commands.CommandError) as raised:
        commands.start_session(repository, project_session.core_session_id)
    assert raised.value.code == "project_session_blocked"
    blocked = repository.state()
    assert blocked.compare.session_runtime[project_session.core_session_id].status == "blocked"
    assert queries.status(repository).ready_count == 0
