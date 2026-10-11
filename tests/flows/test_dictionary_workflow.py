"""Vocabulary is observational; human prescreen selection never votes on adoption."""

import json
from contextlib import closing
from pathlib import Path
from typing import Literal, cast

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from abar.app import commands, queries
from abar.app.actors import Actor
from abar.app.repository import WorkspaceRepository
from abar.app.state import EVENT_SCHEMAS, ABARState, reduce_state
from abar.cli import app
from abar.compare.models import RecipeRef
from abar.foundation.json_types import JSONValue
from abar.foundation.replay import EventAuthority, full_replay
from abar.server import create_app
from scripts.dev_seed import seed_diagnosis
from tests.conftest import persist_finite_variant


def _indicator(repository: WorkspaceRepository, path: Path) -> str:
    path.write_text(
        "External detector fixture; ABAR does not execute this definition.", encoding="utf-8"
    )
    indicator_id = "ind_texture_v1"
    commands.register_indicator(
        repository,
        indicator_id=indicator_id,
        label="texture",
        description="fixture",
        definition_path=path,
        subject_kind="audio",
        unit="ratio",
        actor_id="fixture",
    )
    return indicator_id


def _seed(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "workspace"
    seed_diagnosis(root)
    repository = WorkspaceRepository.open(root)
    try:
        indicator = _indicator(repository, tmp_path / "detector.md")
        state = repository.state()
        symptom = next(iter(state.research.symptoms))
        return root, indicator, symptom
    finally:
        repository.close()


def test_dictionary_cli_retains_partial_fields_and_idempotent_history(tmp_path: Path) -> None:
    root, indicator, symptom = _seed(tmp_path)
    with closing(WorkspaceRepository.open(root)) as repository:
        evidence = next(iter(repository.state().research.project_sessions))
        authority = repository.state().project.authority_snapshot()
    runner = CliRunner()
    prefix = ["--workspace", str(root), "--json", "--actor", "dictionary-agent"]

    def invoke(*arguments: str) -> dict[str, object]:
        result = runner.invoke(app, [*prefix, *arguments])
        assert result.exit_code == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    add = (
        "--idempotency-key",
        "word-add",
        "dictionary",
        "add",
        "ざらつき",
        "--definition",
        "人の試聴で用いた語",
        "--indicator",
        indicator,
        "--symptom",
        symptom,
        "--evidence",
        evidence,
        "--scope",
        "fixture only",
    )
    assert invoke(*add)["result"] == "ざらつき"
    assert invoke(*add)["result"] == "ざらつき"
    update = (
        "--idempotency-key",
        "word-set",
        "dictionary",
        "set",
        "ざらつき",
        "--status",
        "validated",
    )
    invoke(*update)
    invoke("dictionary", "set", "ざらつき", "--definition", "更新した説明")
    # Retrying an older operation cannot overwrite a newer definition.
    invoke(*update)
    listed = invoke("dictionary", "list")
    document = cast(dict[str, object], listed["document"])
    assert len(cast(list[object], document["entries"])) == 2
    with closing(WorkspaceRepository.open(root)) as repository:
        state = repository.state()
        entry = state.research.dictionary["ざらつき"]
        assert entry.status == "validated"
        assert entry.definition == "更新した説明"
        assert entry.indicator_id == indicator
        assert entry.evidence_session_ids == (evidence,)
        assert entry.scope == "fixture only"
        assert "ざらつき" in state.research.symptoms[symptom].dictionary_terms
        assert state.project.authority_snapshot() == authority
        assert queries.project_view(repository).dictionary[-1].term == "ざらつき"
    invoke(
        "dictionary",
        "set",
        "ざらつき",
        "--status",
        "rejected",
        "--clear-indicator",
        "--clear-evidence",
        "--clear-symptoms",
        "--scope",
        "",
    )
    with closing(WorkspaceRepository.open(root)) as repository:
        entry = repository.state().research.dictionary["ざらつき"]
        assert entry.indicator_id is None
        assert entry.evidence_session_ids == entry.symptom_ids == ()
        assert entry.status == "rejected"
        assert "ざらつき" not in repository.state().research.symptoms[symptom].dictionary_terms
        assert (
            len(
                [
                    e
                    for e in repository.events.read_all()
                    if e.event_type == "dictionary.entry.recorded"
                ]
            )
            == 2
        )


def test_dictionary_rejects_unknown_or_unfinished_evidence_without_writing(tmp_path: Path) -> None:
    root, _, _ = _seed(tmp_path)
    with closing(WorkspaceRepository.open(root)) as repository:
        variant = next(iter(repository.state().compare.variants))
        unfinished = commands.create_observation_session(
            repository,
            first_variant="source",
            second_variant=variant,
            focus="観点：検査",  # noqa: RUF001
            recipe=RecipeRef("native"),
            actor_id="agent",
        )
        before = repository.events.latest_sequence()
        for fields in (
            {"indicator_id": "unknown"},
            {"symptom_ids": ("unknown",)},
            {"evidence_session_ids": ("unknown",)},
            {"evidence_session_ids": (unfinished,)},
            {"status": "unknown"},
            {"definition": ""},
            {"term": "語\n別の語"},
        ):
            with pytest.raises(commands.CommandError):
                commands.add_dictionary_entry(
                    repository,
                    **{"term": "言葉", "definition": "説明", "actor_id": "agent", **fields},  # type: ignore[arg-type]
                )
        assert repository.events.latest_sequence() == before


@pytest.mark.parametrize(
    ("schema_version", "damaged_fields"),
    [(1, {"status": "unknown"}), (1, {"term": 7}), (1, {"definition": None}), (2, {})],
)
def test_invalid_dictionary_events_are_isolated_and_legacy_workspace_remains_healthy(
    tmp_path: Path,
    schema_version: int,
    damaged_fields: dict[str, JSONValue],
) -> None:
    root, _, _ = _seed(tmp_path)
    with closing(WorkspaceRepository.open(root)) as repository:
        events = repository.events.read_all()
        word = next(e for e in events if e.event_type == "dictionary.entry.recorded")
        damaged = tuple(
            e.model_copy(
                update={
                    "schema_version": schema_version,
                    "payload": {**e.payload, **damaged_fields},
                }
            )
            if e.event_seq == word.event_seq
            else e
            for e in events
        )
        replay = full_replay(ABARState(), damaged, schemas=EVENT_SCHEMAS, reducer=reduce_state)
        assert replay.degraded is None
        assert replay.isolated_event_seqs == (word.event_seq,)
        assert replay.state.research.dictionary == {}
        assert (
            replay.state.project.authority_snapshot()
            == repository.state().project.authority_snapshot()
        )
        legacy = tuple(e for e in events if not e.event_type.startswith("dictionary."))
        old = full_replay(ABARState(), legacy, schemas=EVENT_SCHEMAS, reducer=reduce_state)
        assert old.degraded is None
        assert old.state.research.dictionary == {}
    for event_type in (
        "dictionary.entry.recorded",
        "dictionary.entry.updated",
        "project.prescreen_indicator.changed",
    ):
        assert EVENT_SCHEMAS[event_type].authority is EventAuthority.OBSERVATIONAL


def test_prescreen_is_human_selected_reversible_and_observational(tmp_path: Path) -> None:
    root, indicator, _ = _seed(tmp_path)
    with closing(WorkspaceRepository.open(root)) as repository:
        authority = repository.state().project.authority_snapshot()
        commands.update_dictionary_entry(
            repository, "ミョイン", indicator_id=indicator, actor_id="agent"
        )
        with pytest.raises(commands.CommandError, match="validated"):
            commands.configure_project(
                repository, prescreen_indicator_id=indicator, actor=Actor("human", "human")
            )
        commands.update_dictionary_entry(
            repository, "ミョイン", status="validated", actor_id="agent"
        )
        for actor in (None, Actor("agent", "agent")):
            with pytest.raises(commands.CommandError, match="human authority"):
                commands.configure_project(
                    repository, prescreen_indicator_id=indicator, actor=actor
                )
    runner = CliRunner()
    prefix = ["--workspace", str(root)]
    for automation in (["--json", "--actor", "agent"], ["--actor", "human"]):
        denied = runner.invoke(
            app,
            [*prefix, *automation, "project", "config", "set", "--prescreen-indicator", indicator],
        )
        assert denied.exit_code != 0
    options = [
        "--idempotency-key",
        "human-choice",
        "project",
        "config",
        "set",
        "--prescreen-indicator",
        indicator,
        "--ready-session-limit",
        "8",
    ]
    for _ in range(2):
        result = runner.invoke(app, [*prefix, *options])
        assert result.exit_code == 0, result.stdout + result.stderr
    with closing(WorkspaceRepository.open(root)) as repository:
        state = repository.state()
        assert queries.project_view(repository).prescreen_indicator_id == indicator
        assert state.project.project is not None and state.project.project.ready_session_limit == 8
        assert state.project.authority_snapshot() == authority
        assert (
            len(
                [
                    e
                    for e in repository.events.read_all()
                    if e.event_type == "project.prescreen_indicator.changed"
                ]
            )
            == 1
        )
    result = runner.invoke(
        app, [*prefix, "project", "config", "set", "--clear-prescreen-indicator"]
    )
    assert result.exit_code == 0
    with closing(WorkspaceRepository.open(root)) as repository:
        assert queries.project_view(repository).prescreen_indicator_id is None
        assert repository.replay().degraded is None


def test_http_prescreen_requires_human_capability(tmp_path: Path) -> None:
    root, indicator, _ = _seed(tmp_path)
    with closing(WorkspaceRepository.open(root)) as repository:
        commands.update_dictionary_entry(
            repository, "ミョイン", indicator_id=indicator, status="validated", actor_id="agent"
        )
    app_ = create_app(
        root,
        automation_token="agent-token",
        interaction_token="human-token",
        allowed_origins=frozenset({"http://testserver"}),
    )
    automation = {"Authorization": "Bearer agent-token", "X-ABAR-Actor": "agent"}
    human = {"Authorization": "Bearer human-token"}
    with TestClient(app_) as client:
        for body in ({"prescreen_indicator_id": indicator}, {"clear_prescreen_indicator": True}):
            assert (
                client.post("/api/project/config", headers=automation, json=body).status_code == 403
            )
        assert (
            client.post(
                "/api/project/config", headers=automation, json={"ready_session_limit": 9}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/project/config", headers=human, json={"prescreen_indicator_id": indicator}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/project/config", headers=human, json={"clear_prescreen_indicator": True}
            ).status_code
            == 200
        )


def test_dictionary_words_and_prescreen_never_change_three_answer_adoption(tmp_path: Path) -> None:
    root, indicator, _ = _seed(tmp_path)
    with closing(WorkspaceRepository.open(root)) as repository:
        commands.update_dictionary_entry(
            repository, "ミョイン", indicator_id=indicator, status="validated", actor_id="agent"
        )
        commands.configure_project(
            repository, prescreen_indicator_id=indicator, actor=Actor("human", "human")
        )
        candidate = persist_finite_variant(
            repository, label="adoption fixture", same_as_source=False
        )
        session_id = commands.create_best_update_session(
            repository, proposed_variant=candidate, actor_id="agent"
        )
        session = repository.state().research.project_sessions[session_id]
        commands.start_session(repository, session.core_session_id, allocation_seed=1)
        deck = queries.active_deck(repository, audio_url=lambda _delivery, _slot, _object: "audio")
        assert deck.word_candidates == ("ミョイン",)
        assert deck.identity_by_slot is None
        deliveries = [
            d
            for d in repository.state().compare.deliveries.values()
            if d.session_id == session.core_session_id
        ]
        for index, delivery in enumerate(deliveries):
            preference: Literal[1, 5] = 5 if delivery.slot_assignment["B"] == "p2" else 1
            commands.record_judgment(repository, delivery.id, preference=preference)
            state = repository.state()
            assert state.project.project is not None
            assert state.project.project.current_best_variant_id == (
                candidate if index == 2 else "source"
            )
        assert queries.session_result(repository, session_id).current_best_updated
