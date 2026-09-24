"""Commands reject what their reducers would drop or refuse, before appending."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from abar.app import commands
from abar.app.exporting import write_project_export
from abar.app.repository import WorkspaceRepository
from abar.compare.bundles import build_command_bundle
from abar.foundation.json_types import JSONValue
from tests.conftest import persist_finite_variant

_INDICATOR = "ind_loudness_v1"


def _definition(tmp_path: Path, text: str = "loudness") -> Path:
    path = tmp_path / f"{text}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _register(
    repository: WorkspaceRepository,
    definition: Path,
    *,
    label: str = "Loudness",
    role: str = "none",
) -> None:
    commands.register_indicator(
        repository,
        indicator_id=_INDICATOR,
        label=label,
        description="Integrated loudness",
        definition_path=definition,
        subject_kind="audio",
        unit="LUFS",
        role=role,  # type: ignore[arg-type]
        actor_id="agent-1",
    )


def test_reregistering_an_indicator_with_another_definition_is_rejected(
    repository: WorkspaceRepository, tmp_path: Path
) -> None:
    commands.init_project(repository, name="P", brief="b")
    definition = _definition(tmp_path)
    _register(repository, definition)
    before = repository.events.latest_sequence()

    # Identical re-registration under a new key is a no-op, not an isolated event.
    _register(repository, definition)
    assert repository.events.latest_sequence() == before

    for changed in (
        {"label": "Other label"},
        {"role": "guard"},
    ):
        with pytest.raises(commands.CommandError) as raised:
            _register(repository, definition, **changed)  # type: ignore[arg-type]
        assert raised.value.code == "indicator_exists"
    with pytest.raises(commands.CommandError) as raised:
        _register(repository, _definition(tmp_path, "other definition"))
    assert raised.value.code == "indicator_exists"

    assert repository.events.latest_sequence() == before
    replay = repository.replay()
    assert replay.isolated_event_seqs == ()
    assert replay.state.research.indicators[_INDICATOR].label == "Loudness"


def test_reregistering_after_a_role_update_keeps_the_current_role(
    repository: WorkspaceRepository, tmp_path: Path
) -> None:
    commands.init_project(repository, name="P", brief="b")
    definition = _definition(tmp_path)
    _register(repository, definition)
    commands.update_indicator(repository, _INDICATOR, role="target")

    with pytest.raises(commands.CommandError) as raised:
        _register(repository, definition)
    assert raised.value.code == "indicator_exists"
    _register(repository, definition, role="target")
    assert repository.replay().isolated_event_seqs == ()


def test_unreadable_indicator_definition_is_a_command_error(
    repository: WorkspaceRepository, tmp_path: Path
) -> None:
    commands.init_project(repository, name="P", brief="b")
    with pytest.raises(commands.CommandError) as raised:
        _register(repository, tmp_path / "missing.md")
    assert raised.value.code == "indicator_definition_unreadable"


@pytest.mark.parametrize(
    ("start", "duration"),
    [(-1.0, 1.0), (0.0, 0.0), (0.0, 0.00001), (5.5, 1.0), (float("nan"), 1.0)],
)
def test_invalid_clip_is_rejected_before_any_event(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    start: float,
    duration: float,
) -> None:
    commands.init_project(
        repository, name="P", brief="b", material_paths=(wav_file("m.wav", 220.0),)
    )
    material_id = next(iter(repository.state().compare.materials))
    before = repository.events.latest_sequence()

    with pytest.raises(commands.CommandError) as raised:
        commands.add_clip(repository, material_id, start_seconds=start, duration_seconds=duration)

    assert raised.value.code == "invalid_clip"
    assert repository.events.latest_sequence() == before


@pytest.mark.parametrize(("name", "brief"), [(" ", "b"), ("P", ""), ("P", "x" * 201)])
def test_invalid_project_is_rejected_before_any_event(
    repository: WorkspaceRepository, name: str, brief: str
) -> None:
    with pytest.raises(commands.CommandError) as raised:
        commands.init_project(repository, name=name, brief=brief)
    assert raised.value.code == "invalid_project"
    assert repository.events.latest_sequence() == 0


def test_variant_whose_archive_is_missing_is_a_command_error(
    repository: WorkspaceRepository, tmp_path: Path
) -> None:
    bundle = tmp_path / "renderer"
    bundle.mkdir()
    (bundle / "render.sh").write_text('#!/bin/sh\ncp "$1" "$3"\n', encoding="utf-8")
    built = build_command_bundle(bundle, "render.sh")
    digest = hashlib.sha256(built.archive).hexdigest()
    manifest: dict[str, JSONValue] = {
        **built.manifest,
        "source_archive": {"object_id": f"obj_{digest}", "sha": f"sha256:{digest}"},
    }

    with pytest.raises(commands.CommandError) as raised:
        commands.add_variant(repository, manifest)

    assert raised.value.code == "object_missing"
    assert repository.events.latest_sequence() == 0


def _outside_clip(repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]) -> str:
    # Registered before the Project exists, so never attached to it.
    outside = commands.add_material(repository, wav_file("outside.wav", 440.0))
    commands.init_project(
        repository, name="P", brief="b", material_paths=(wav_file("inside.wav", 220.0),)
    )
    return repository.state().compare.materials[outside].clip_ids[0]


def test_explicit_evidence_clip_must_belong_to_an_attached_material(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]
) -> None:
    outside_clip = _outside_clip(repository, wav_file)
    proposed = persist_finite_variant(repository, label="Proposal", same_as_source=False)
    inside_clips = next(
        material.clip_ids
        for material in repository.state().compare.materials.values()
        if outside_clip not in material.clip_ids
    )
    before = repository.events.latest_sequence()

    with pytest.raises(commands.CommandError) as observation:
        commands.create_observation_session(
            repository,
            first_variant="source",
            second_variant=proposed,
            focus="f",
            clip_ids=(outside_clip,),
            actor_id="agent-1",
        )
    with pytest.raises(commands.CommandError) as best_update:
        commands.create_best_update_session(
            repository,
            proposed_variant=proposed,
            clip_ids=(*inside_clips[:2], outside_clip),
            actor_id="agent-1",
        )

    assert observation.value.code == "clip_not_in_project"
    assert best_update.value.code == "clip_not_in_project"
    assert outside_clip in str(best_update.value)
    assert repository.events.latest_sequence() == before


def test_export_reports_render_resolutions_and_reuses_the_callers_render_cache(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    tmp_path: Path,
) -> None:
    commands.init_project(
        repository, name="P", brief="b", material_paths=(wav_file("m.wav", 220.0),)
    )
    bundle = tmp_path / "renderer"
    bundle.mkdir()
    (bundle / "render.sh").write_text('#!/bin/sh\ncp "$1" "$3"\n', encoding="utf-8")
    built = build_command_bundle(bundle, "render.sh", timeout_seconds=10)
    variant_id = commands.add_variant_archive(repository, built.manifest, built.archive)
    state = repository.state()
    project = state.project.project
    assert project is not None
    clip_count = sum(len(state.compare.materials[m].clip_ids) for m in project.material_ids)

    result = write_project_export(
        state.compare,
        state.project,
        variant_id,
        tmp_path / "export.json",
        objects=repository.objects,
        render_clips=tmp_path / "clips",
        render_cache=repository.render_memo,
    )

    assert len(result.rendered_files) == clip_count
    assert len(result.resolutions) == clip_count
    renders = [
        effect
        for resolution in result.resolutions
        for effect in resolution.effects
        if effect.kind == "render"
    ]
    assert renders and all(effect.render is not None for effect in renders)
    assert len(repository.render_memo) == len(project.material_ids)
    assert json.loads((tmp_path / "export.json").read_text())["variant_ref"] == variant_id
