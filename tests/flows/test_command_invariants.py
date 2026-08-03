from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from abar.app import commands, project_session_commands, queries, session_commands
from abar.app.events import draft
from abar.app.repository import WorkspaceDegraded, WorkspaceRepository
from abar.compare.models import RecipeRef
from abar.compare.service import PreparedComparison
from abar.research.planner import presentation_order
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


def test_material_set_import_is_resumable_and_project_view_lists_clips(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(repository, name="Project", brief="Improve the sound")
    paths = (wav_file("one.wav", 220.0), wav_file("two.wav", 330.0))

    first = commands.add_materials(
        repository,
        paths,
        source_group="corpus",
        idempotency_key="material-set",
    )
    repeated = commands.add_materials(
        repository,
        paths,
        source_group="corpus",
        idempotency_key="material-set",
    )

    assert repeated == first
    view = queries.project_view(repository)
    assert {item.id for item in view.materials} == set(first)
    assert all(item.source_group == "corpus" for item in view.materials)
    assert all(item.clips for item in view.materials)
    assert all(
        clip.duration_seconds == pytest.approx(4.0)
        for item in view.materials
        for clip in item.clips
    )


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


def test_observation_session_inherits_project_recipe_and_exposes_resolved_value(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(
        repository,
        name="Project",
        brief="Improve the sound",
        material_paths=(wav_file("recipe-source.wav", 220.0),),
    )
    proposed = persist_finite_variant(repository, label="Proposal", same_as_source=False)

    inherited_id = commands.create_observation_session(
        repository,
        first_variant="source",
        second_variant=proposed,
        focus="Use the Project default",
        actor_id="agent-1",
    )
    explicit_id = commands.create_observation_session(
        repository,
        first_variant="source",
        second_variant=proposed,
        focus="Use an explicit override",
        recipe=RecipeRef("native"),
        actor_id="agent-1",
    )

    state = repository.state()
    inherited = state.research.project_sessions[inherited_id]
    explicit = state.research.project_sessions[explicit_id]
    assert inherited.recipe == RecipeRef("matched")
    assert explicit.recipe == RecipeRef("native")

    dashboard = queries.project_dashboard(repository)
    assert dashboard.primary_recipe == "matched-v1"
    cards = {item.project_session_id: item for item in dashboard.sessions}
    assert cards[inherited_id].recipe == "matched-v1"
    assert cards[explicit_id].recipe == "native-v1"
    details = {
        item.project_session_id: item for item in queries.project_view(repository).session_details
    }
    assert details[inherited_id].recipe == "matched-v1"
    assert details[explicit_id].recipe == "native-v1"

    commands.start_session(repository, inherited.core_session_id, allocation_seed=1)
    deck = queries.active_deck(
        repository,
        audio_url=lambda delivery_id, slot, _audio_id: f"/{delivery_id}/{slot}",
    )
    assert deck.recipe == "matched-v1"
    delivery = next(
        item
        for item in repository.state().compare.deliveries.values()
        if item.session_id == inherited.core_session_id
    )
    commands.record_judgment(repository, delivery.id, preference=3)
    result = queries.session_result(repository, inherited_id)
    assert result.recipe == "matched-v1"
    completion = queries.session_completion(
        repository,
        inherited.core_session_id,
        audio_url=lambda delivery_id, slot, _audio_id: f"/{delivery_id}/{slot}",
    )
    assert completion.recipe == "matched-v1"


def test_standard_session_can_use_ten_materials_and_add_optional_checks(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    material_paths = tuple(
        wav_file(f"corpus-{index}.wav", 220.0 + index * 20.0) for index in range(10)
    )
    commands.init_project(
        repository,
        name="Project",
        brief="Improve the sound",
        material_paths=material_paths,
    )
    proposed = persist_finite_variant(
        repository,
        label="Proposal",
        same_as_source=False,
    )

    project_session_id = commands.create_observation_session(
        repository,
        first_variant="source",
        second_variant=proposed,
        focus="Check the proposal across the corpus",
        size="standard",
        evidence_count=10,
        same_check=True,
        repeat_check=True,
        actor_id="agent-1",
    )

    state = repository.state()
    project_session = state.research.project_sessions[project_session_id]
    core_session = state.compare.sessions[project_session.core_session_id]
    materials = {
        state.compare.clips[clip_id].material_id for clip_id in project_session.evidence_clip_ids
    }
    assert project_session.size == "standard"
    assert len(project_session.evidence_item_ids) == 10
    assert len(project_session.evidence_clip_ids) == 10
    assert len(materials) == 10
    assert len(core_session.items) == 12
    assert project_session.same_check_item_id is not None
    assert project_session.repeat_check_item_id is not None

    commands.start_session(repository, core_session.id, allocation_seed=1234)
    state = repository.state()
    deliveries = sorted(
        (
            delivery
            for delivery in state.compare.deliveries.values()
            if delivery.session_id == core_session.id
        ),
        key=lambda delivery: delivery.sequence_index,
    )
    realized = tuple(delivery.session_item_id for delivery in deliveries)
    assert realized == presentation_order(project_session, seed=1234)
    assert realized[0] not in {
        project_session.same_check_item_id,
        project_session.repeat_check_item_id,
    }
    original_index = realized.index(project_session.repeat_of_item_id)
    repeat_index = realized.index(project_session.repeat_check_item_id)
    assert repeat_index - original_index >= 3
    original = next(
        delivery
        for delivery in deliveries
        if delivery.session_item_id == project_session.repeat_of_item_id
    )
    repeat = next(
        delivery
        for delivery in deliveries
        if delivery.session_item_id == project_session.repeat_check_item_id
    )
    assert repeat.slot_assignment == {
        "A": original.slot_assignment["B"],
        "B": original.slot_assignment["A"],
    }


def test_explicit_large_session_preserves_clips_from_one_material(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(
        repository,
        name="Project",
        brief="Improve the sound",
        material_paths=(wav_file("single-material.wav", 220.0),),
    )
    project = repository.state().project.project
    assert project is not None
    material_id = project.material_ids[0]
    clips = tuple(
        commands.add_clip(
            repository,
            material_id,
            start_seconds=index * 0.5,
            duration_seconds=0.4,
            role=f"region-{index}",
        )
        for index in range(10)
    )
    proposed = persist_finite_variant(repository, label="Proposal", same_as_source=False)
    progress: list[commands.SessionPreparationProgress] = []

    project_session_id = commands.create_observation_session(
        repository,
        first_variant="source",
        second_variant=proposed,
        focus="Check ten regions",
        size="standard",
        evidence_count=10,
        recipe=RecipeRef("native"),
        clip_ids=clips,
        actor_id="agent-1",
        progress=progress.append,
    )

    session = repository.state().research.project_sessions[project_session_id]
    assert session.evidence_clip_ids == clips
    assert session.selection_algorithm_id == "explicit"
    assert [(item.stage, item.current) for item in progress] == [
        (stage, index) for index in range(1, 11) for stage in ("started", "completed")
    ]


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


def test_best_update_rejects_even_one_no_effect_evidence_item(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands.init_project(
        repository,
        name="Project",
        brief="Improve the sound",
        material_paths=(wav_file("mixed-one.wav", 220.0), wav_file("mixed-two.wav", 330.0)),
    )
    project = repository.state().project.project
    assert project is not None
    commands.add_clip(
        repository,
        project.material_ids[0],
        start_seconds=1.0,
        duration_seconds=2.0,
    )
    proposed = persist_finite_variant(repository, label="different", same_as_source=False)
    original: Callable[..., PreparedComparison] = project_session_commands.build_comparison
    call_count = 0

    def mixed_comparison(*args: object, **kwargs: object) -> PreparedComparison:
        nonlocal call_count
        built = original(*args, **kwargs)
        call_count += 1
        if call_count == 1:
            return replace(
                built,
                prepared_pair=replace(built.prepared_pair, no_effect=True),
            )
        return built

    monkeypatch.setattr(project_session_commands, "build_comparison", mixed_comparison)
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
    assert blocked.compare.session_runtime[project_session.core_session_id].deliveries == ()
    assert queries.status(repository).ready_count == 0
    card = next(
        item
        for item in queries.project_dashboard(repository).sessions
        if item.project_session_id == session_id
    )
    assert card.status == "blocked"
    assert card.outcome == "Session audio validation failed"

    recreated = commands.create_observation_session(
        repository,
        first_variant="source",
        second_variant=proposed,
        focus="Listen for the difference",
        actor_id="agent-1",
    )
    assert recreated != session_id


def test_observation_rejects_the_same_variant(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    commands.init_project(
        repository,
        name="Project",
        brief="Improve the sound",
        material_paths=(wav_file("same-observation.wav", 220.0),),
    )

    with pytest.raises(commands.CommandError) as raised:
        commands.create_observation_session(
            repository,
            first_variant="source",
            second_variant="source",
            focus="Compare source with itself",
            actor_id="agent-1",
        )

    assert raised.value.code == "observation_same_variant"


def test_degraded_workspace_rejects_object_writes(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
) -> None:
    repository.events.append(
        draft(
            "legacy.unsupported",
            {},
            idempotency_key="degrade-workspace",
        )
    )
    before_objects = tuple(
        path for path in (repository.root / "objects").rglob("*") if path.is_file()
    )
    before_events = repository.events.read_all()

    with pytest.raises(WorkspaceDegraded, match="degraded replay"):
        commands.import_audio(repository, wav_file("degraded.wav", 220.0))

    after_objects = tuple(
        path for path in (repository.root / "objects").rglob("*") if path.is_file()
    )
    assert after_objects == before_objects
    assert repository.events.read_all() == before_events
