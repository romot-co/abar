"""ABAR 2.1 preserves sealed human evidence while adding local diagnosis."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from abar.app import commands, queries
from abar.app.actors import Actor
from abar.app.dashboard_queries import project_dashboard
from abar.app.diagnostic_queries import symptom_summaries
from abar.app.repository import WorkspaceRepository
from abar.app.state import EVENT_SCHEMAS, ABARState, reduce_state
from abar.cli import app
from abar.compare.models import (
    BlockerInput,
    Judgment,
    LoopTelemetry,
    RecipeRef,
    Telemetry,
    TimeRange,
    VariantKind,
)
from abar.foundation.replay import full_replay
from abar.project.current_best import evaluate_best_update
from abar.project.models import BestEvidence
from abar.research.verification import VerificationCheck, VerificationReport
from abar.server import create_app
from abar.server.request_models import JudgmentRequest
from tests.conftest import persist_finite_variant


def _project(repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]) -> str:
    commands.init_project(
        repository,
        name="2.1",
        brief="keep attack and texture",
        material_paths=tuple(
            wav_file(f"material-{index}.wav", 220.0 + index * 110) for index in range(3)
        ),
    )
    return persist_finite_variant(repository, label="candidate", same_as_source=False)


def _observation(
    repository: WorkspaceRepository,
    variant: str,
    *,
    clip: str | None = None,
    symptom: str | None = None,
    checks: bool = False,
) -> str:
    session_id = commands.create_observation_session(
        repository,
        first_variant="source",
        second_variant=variant,
        focus=None if symptom else "観点：texture",  # noqa: RUF001
        symptom_id=symptom,
        clip_ids=() if clip is None else (clip,),
        recipe=RecipeRef("native"),
        same_check=checks,
        repeat_check=checks,
        actor_id="agent",
    )
    commands.start_session(
        repository,
        repository.state().research.project_sessions[session_id].core_session_id,
        allocation_seed=2,
    )
    return session_id


def _deliveries(repository: WorkspaceRepository, session_id: str) -> list[str]:
    core_id = repository.state().research.project_sessions[session_id].core_session_id
    return [
        delivery.id
        for delivery in sorted(
            repository.state().compare.deliveries.values(),
            key=lambda delivery: delivery.sequence_index,
        )
        if delivery.session_id == core_id
    ]


def _report(
    repository: WorkspaceRepository,
    variant: str,
    check_id: str,
    *,
    against: str | None = None,
    symptom_id: str | None = None,
    digest: str | None = None,
) -> VerificationReport:
    state = repository.state()
    project = state.project.project
    assert project is not None
    material = project.material_ids[0]
    manifest = state.compare.manifests[state.compare.variants[variant].manifest_id]
    # Test fixtures use finite full renders; hash the bytes of the final WAV.
    import hashlib
    from typing import cast

    mapping = cast(
        dict[str, dict[str, str]], cast(dict[str, object], manifest["renderer"])["finite_map"]
    )
    audio = state.compare.audio[mapping[material]["audio_object_id"]]
    actual = f"sha256:{hashlib.sha256(repository.objects.read(audio.object_id)).hexdigest()}"
    return VerificationReport(
        schema_version=1,
        producer="test-fixture 1",
        variant_id=variant,
        material_id=material,
        final_wav_sha256=digest or actual,
        checks=[
            VerificationCheck(id=check_id, verdict="fail", against=against, symptom_id=symptom_id)
        ],
    )  # type: ignore[list-item]


@pytest.mark.parametrize(
    "start,end", [(1, 1), (2, 1), (-1, 1), (0, float("inf")), (float("nan"), 1)]
)
def test_range_is_finite_and_ordered(start: float, end: float) -> None:
    with pytest.raises(ValueError):
        TimeRange(start, end)


def test_judgment_xor_and_ranged_blocker_contract() -> None:
    range_ = TimeRange(0.2, 0.5)
    with pytest.raises(ValueError):
        BlockerInput(range=range_)
    with pytest.raises(ValueError):
        LoopTelemetry(range_, {"a": -1, "b": 0})
    base = Judgment(
        "j",
        "d",
        3,
        {"a": BlockerInput(), "b": BlockerInput()},
        None,
        False,
        Telemetry({"a": 0, "b": 0}, 0, 0),
    )
    assert replace(base, preference=None, held=True).held
    for preference, held in ((None, False), (3, True)):
        with pytest.raises(ValueError):
            replace(base, preference=preference, held=held)
    with pytest.raises(ValueError):
        replace(base, comment_range=range_)


def test_held_best_update_has_incomplete_evidence(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]
) -> None:
    proposed = _project(repository, wav_file)
    session_id = commands.create_best_update_session(
        repository, proposed_variant=proposed, actor_id="agent"
    )
    session = repository.state().research.project_sessions[session_id]
    commands.start_session(repository, session.core_session_id, allocation_seed=4)
    ids = _deliveries(repository, session_id)
    for index, delivery_id in enumerate(ids):
        delivery = repository.state().compare.deliveries[delivery_id]
        preference: Literal[1, 5] = 5 if delivery.slot_assignment["B"] == "p2" else 1
        commands.record_judgment(
            repository, delivery_id, preference=None if index == 0 else preference, held=index == 0
        )
    state = repository.state()
    assert state.project.project is not None
    assert state.project.project.current_best_variant_id == "source"
    result = queries.session_result(repository, session_id)
    assert result.held_count == 1
    assert result.evidence_direction_counts["tie"] == 0
    assert result.best_update_evidence is not None
    assert result.best_update_evidence.answered_count == 2
    plan = next(iter(state.project.best_update_plans.values()))
    evidence = tuple(
        BestEvidence(item_id, None if index == 0 else 2, False, False)
        for index, item_id in enumerate(plan.evidence_item_ids)
    )
    decision = evaluate_best_update(state.project.authority_snapshot(), plan, evidence)  # type: ignore[arg-type]
    assert decision.reason == "evidence_incomplete"
    assert "保留 1" in (project_dashboard(repository).sessions[0].outcome or "")


def test_judgment_schema_replays_old_new_and_rejects_future(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]
) -> None:
    variant = _project(repository, wav_file)
    session_id = _observation(repository, variant)
    delivery_id = _deliveries(repository, session_id)[0]
    range_ = TimeRange(0.2, 0.8)
    commands.record_judgment(
        repository,
        delivery_id,
        held=True,
        blocker_b=BlockerInput(True, "texture", range_),
        comment="tail",
        comment_range=range_,
        telemetry=Telemetry(
            {"a": 10, "b": 20}, 1, 50, (LoopTelemetry(range_, {"a": 10, "b": 20}),)
        ),
        idempotency_key="answer",
    )
    same = commands.record_judgment(
        repository,
        delivery_id,
        held=True,
        blocker_b=BlockerInput(True, "texture", range_),
        comment="tail",
        comment_range=range_,
        telemetry=Telemetry(
            {"a": 10, "b": 20}, 1, 50, (LoopTelemetry(range_, {"a": 10, "b": 20}),)
        ),
        idempotency_key="answer",
    )
    assert same == repository.state().compare.judgments[delivery_id].id
    events = repository.events.read_all()
    current = full_replay(ABARState(), events, schemas=EVENT_SCHEMAS, reducer=reduce_state)
    assert current.degraded is None
    assert current.state.compare.judgments[delivery_id].telemetry.loops[0].range == range_
    legacy = tuple(
        event.model_copy(
            update={"schema_version": 1, "payload": {**event.payload, "preference": 3}}
        )
        if event.event_type == "judgment.recorded"
        else event
        for event in events
    )
    old = full_replay(ABARState(), legacy, schemas=EVENT_SCHEMAS, reducer=reduce_state)
    assert old.degraded is None
    assert not old.state.compare.judgments[delivery_id].held
    assert old.state.compare.judgments[delivery_id].blockers["b"].range is None
    assert old.state.compare.judgments[delivery_id].telemetry.loops == ()
    future = tuple(
        event.model_copy(update={"schema_version": 3})
        if event.event_type == "judgment.recorded"
        else event
        for event in events
    )
    assert (
        full_replay(ABARState(), future, schemas=EVENT_SCHEMAS, reducer=reduce_state).degraded
        is not None
    )
    completion = queries.session_completion(
        repository, session_id, audio_url=lambda _delivery, _slot, _object: "audio"
    )
    assert completion.items[0].judgment is not None
    assert completion.items[0].judgment.held
    assert completion.items[0].judgment.comment_range is not None
    assert completion.items[0].judgment.blockers["b"].range is not None


def test_held_checks_are_missing_but_blockers_survive(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]
) -> None:
    variant = _project(repository, wav_file)
    session_id = _observation(repository, variant, checks=True)
    for delivery in _deliveries(repository, session_id):
        commands.record_judgment(
            repository, delivery, held=True, blocker_a=BlockerInput(True, "rough")
        )
    result = queries.session_result(repository, session_id)
    assert result.held_count == 1
    assert result.same_result == result.repeat_result == "missing"
    assert result.favored_variant_id is None
    assert sum(len(blockers) for blockers in result.blockers_by_variant.values()) == 1


def test_symptom_round_trip_is_sealed_and_material_relative(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]
) -> None:
    variant = _project(repository, wav_file)
    project = repository.state().project.project
    assert project is not None
    clip_id = commands.add_clip(
        repository, project.material_ids[0], start_seconds=1, duration_seconds=2
    )
    session_id = _observation(repository, variant, clip=clip_id)
    delivery_id = _deliveries(repository, session_id)[0]
    with pytest.raises(commands.CommandError, match="ended"):
        commands.add_symptom(repository, delivery_id=delivery_id, side="b", actor_id="agent")
    commands.record_judgment(
        repository,
        delivery_id,
        preference=3,
        blocker_b=BlockerInput(True, "ミョイン", TimeRange(0.2, 0.7)),
    )
    symptom_id = commands.add_symptom(
        repository, delivery_id=delivery_id, side="b", actor_id="agent", idempotency_key="symptom"
    )
    assert (
        commands.add_symptom(
            repository,
            delivery_id=delivery_id,
            side="b",
            actor_id="agent",
            idempotency_key="symptom",
        )
        == symptom_id
    )
    symptom = repository.state().research.symptoms[symptom_id]
    assert symptom.range == TimeRange(1.2, 1.7)
    assert symptom.title == "ミョイン"
    commands.update_symptom(
        repository,
        symptom_id,
        facts="human word",
        hypotheses="possible mechanism",
        actor_id="agent",
    )
    for action, status in (("resolve", "resolved"), ("reopen", "open"), ("withdraw", "withdrawn")):
        commands.transition_symptom(
            repository,
            symptom_id,
            action=cast(Literal["resolve", "reopen", "withdraw"], action),
            reason="bounded observation",
            session_id=session_id,
            actor_id="agent",
        )  # type: ignore[arg-type]
        assert repository.state().research.symptoms[symptom_id].status == status
    followup = _observation(repository, variant, clip=clip_id, symptom=symptom_id)
    deck = queries.active_deck(repository, audio_url=lambda _delivery, _slot, _object: "audio")
    assert deck.criterion_label == "観点"
    assert deck.criterion_text == "観点：ミョイン"  # noqa: RUF001
    assert deck.identity_by_slot is None
    for delivery in _deliveries(repository, followup):
        commands.record_judgment(repository, delivery, preference=3)
    assert symptom_summaries(repository.state())[0].listen_count == 1
    commands.flag_current_best(
        repository,
        symptom_id=symptom_id,
        session_id=followup,
        reason="recurrence",
        actor_id="agent",
    )
    assert queries.status(repository).current_best_flags[0].title == "ミョイン"
    commands.set_current_best_manual(
        repository, variant, ack="test fixture decision", actor=Actor("human", "human")
    )
    assert queries.status(repository).current_best_flags == ()
    assert any(event.event_type == "current_best.flagged" for event in repository.events.read_all())


def test_unranged_symptom_rejected_and_baseline_is_observation_only(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]
) -> None:
    variant = _project(repository, wav_file)
    session_id = _observation(repository, variant)
    delivery_id = _deliveries(repository, session_id)[0]
    commands.record_judgment(
        repository, delivery_id, preference=3, blocker_b=BlockerInput(True, "rough")
    )
    with pytest.raises(commands.CommandError, match="ranged blocker"):
        commands.add_symptom(repository, delivery_id=delivery_id, side="b", actor_id="agent")
    commands.record_baseline(repository, variant, label="old output", actor_id="agent")
    with pytest.raises(commands.CommandError, match="baseline"):
        commands.create_best_update_session(repository, proposed_variant=variant, actor_id="agent")
    assert _observation(repository, variant)


@pytest.mark.parametrize(
    "check_id,reject_observation,reject_best",
    [
        ("exp.provenance.match", True, True),
        ("exp.region.excerpt_from_full", True, True),
        ("exp.baseline.reproduce", True, True),
        ("exp.output.measured_is_final", False, False),
        ("exp.sources.distinct", False, True),
        ("exp.candidate.acted_on_target", False, True),
        ("exp.candidate.no_op", False, True),
        ("exp.control.matched", False, False),
    ],
)
def test_verification_guard_table(
    repository: WorkspaceRepository,
    wav_file: Callable[[str, float], Path],
    check_id: str,
    reject_observation: bool,
    reject_best: bool,
) -> None:
    variant = _project(repository, wav_file)
    report = _report(repository, variant, check_id)
    commands.record_verification(repository, report, actor_id="agent")
    state = repository.state()
    project = state.project.project
    assert project is not None
    clip_id = state.compare.materials[project.material_ids[0]].clip_ids[0]
    best_clips = tuple(
        state.compare.materials[material].clip_ids[0] for material in project.material_ids
    )
    if reject_observation:
        with pytest.raises(commands.CommandError, match=check_id):
            _observation(repository, variant, clip=clip_id)
    else:
        session_id = _observation(repository, variant, clip=clip_id)
        assert any(
            check_id in warning
            for warning in repository.state().research.project_sessions[session_id].warnings
        )
        commands.record_judgment(repository, _deliveries(repository, session_id)[0], preference=3)
    if reject_best:
        with pytest.raises(commands.CommandError, match=check_id):
            commands.create_best_update_session(
                repository, proposed_variant=variant, clip_ids=best_clips, actor_id="agent"
            )
    else:
        best = commands.create_best_update_session(
            repository, proposed_variant=variant, clip_ids=best_clips, actor_id="agent"
        )
        warnings = repository.state().research.project_sessions[best].warnings
        assert bool(warnings) == (check_id == "exp.output.measured_is_final")


def test_verification_is_scoped_and_wrong_audio_is_rejected(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path]
) -> None:
    variant = _project(repository, wav_file)
    state = repository.state()
    assert state.project.project is not None
    clips = tuple(
        state.compare.materials[m].clip_ids[0] for m in state.project.project.material_ids
    )
    # A pair-specific failure against itself is irrelevant to comparison against source.
    report = _report(repository, variant, "exp.sources.distinct", against=variant)
    commands.record_verification(repository, report, actor_id="agent")
    best = commands.create_best_update_session(
        repository, proposed_variant=variant, clip_ids=clips, actor_id="agent"
    )
    assert repository.state().research.project_sessions[best].warnings == ()
    # Close the unstarted Session before checking a stale/mislabelled external artifact.
    commands.close_project_session(repository, best, actor_id="agent")
    commands.record_verification(
        repository,
        _report(repository, variant, "future.check", digest="sha256:" + "0" * 64),
        actor_id="agent",
    )
    with pytest.raises(commands.CommandError, match="current full render"):
        commands.create_best_update_session(
            repository, proposed_variant=variant, clip_ids=clips, actor_id="agent"
        )


def test_http_rejects_invalid_answers_and_out_of_bounds_range(
    tmp_path: Path, wav_file: Callable[[str, float], Path]
) -> None:
    root = tmp_path / "http-workspace"
    repository = WorkspaceRepository.open(root)
    variant = _project(repository, wav_file)
    session_id = _observation(repository, variant)
    delivery = _deliveries(repository, session_id)[0]
    repository.close()
    app = create_app(
        root,
        automation_token="agent",
        interaction_token="human",
        allowed_origins=frozenset({"http://testserver"}),
    )
    headers = {"Authorization": "Bearer human"}
    valid: dict[str, object] = {
        "preference": None,
        "held": True,
        "blockers": {"a": {"selected": False}, "b": {"selected": False}},
        "telemetry": {
            "listen_ms": {"a": 0, "b": 0},
            "switches": 0,
            "answer_ms": 0,
            "loops": [
                {"range": {"start_seconds": 0, "end_seconds": 0.5}, "listen_ms": {"a": 50, "b": 60}}
            ],
        },
    }
    with TestClient(app) as client:
        for change in (
            {"held": False},
            {"preference": 3},
            {"comment": "memo", "comment_range": {"start_seconds": 1, "end_seconds": 0.5}},
        ):
            assert (
                client.post(
                    f"/api/deliveries/{delivery}/judgments",
                    headers=headers,
                    json={**valid, **change},
                ).status_code
                == 422
            )
        out_of_bounds = client.post(
            f"/api/deliveries/{delivery}/judgments",
            headers=headers,
            json={
                **valid,
                "comment": "memo",
                "comment_range": {"start_seconds": 0, "end_seconds": 99},
            },
        )
        assert out_of_bounds.status_code == 409
        assert (
            client.post(
                f"/api/deliveries/{delivery}/judgments", headers=headers, json=valid
            ).status_code
            == 200
        )
    with pytest.raises(ValidationError):
        JudgmentRequest.model_validate(
            {**valid, "telemetry": {"listen_ms": {"a": 0}, "switches": 0, "answer_ms": 0}}
        )


@pytest.mark.parametrize("kind", ["control", "reference", "tap", "symptom_region", "baseline"])
def test_diagnostic_kinds_cannot_supply_adoption_evidence(
    repository: WorkspaceRepository, wav_file: Callable[[str, float], Path], kind: VariantKind
) -> None:
    commands.init_project(
        repository,
        name="kind",
        brief="keep natural tails",
        material_paths=(wav_file("voice.wav", 220),),
    )
    variant = persist_finite_variant(repository, label=kind, same_as_source=False, kind=kind)
    assert repository.state().compare.variants[variant].kind == kind
    with pytest.raises(commands.CommandError):
        commands.create_best_update_session(repository, proposed_variant=variant, actor_id="agent")
    session = _observation(repository, variant)
    for delivery in _deliveries(repository, session):
        commands.record_judgment(repository, delivery, preference=3)
    completion = queries.session_completion(
        repository, session, audio_url=lambda _delivery, _slot, _object: "audio"
    )
    assert any(identity.kind == kind for identity in completion.items[0].identity_by_slot.values())


def test_cli_completes_diagnosis_loop_with_json_arrays_and_idempotency(tmp_path: Path) -> None:
    from scripts.dev_seed import seed_diagnosis

    root = tmp_path / "cli-workspace"
    seed_diagnosis(root)
    repository = WorkspaceRepository.open(root)
    state = repository.state()
    existing = next(iter(state.research.symptoms.values()))
    variant = next(iter(state.compare.variants))
    report = _report(repository, variant, "future.external.check")
    repository.close()
    report_file = tmp_path / "verification.json"
    report_file.write_text(report.model_dump_json(), encoding="utf-8")
    runner = CliRunner()
    prefix = ["--workspace", str(root), "--json", "--actor", "cli-agent"]

    def invoke(*arguments: str) -> dict[str, object]:
        result = runner.invoke(app, [*prefix, *arguments])
        assert result.exit_code == 0, result.stdout
        return json.loads(result.stdout)

    args = (
        "--idempotency-key",
        "symptom-cli",
        "symptom",
        "add",
        "--from-judgment",
        existing.source_delivery_id,
        "--side",
        existing.source_slot,
        "--title",
        "尾" * 200,
    )
    symptom = str(invoke(*args)["result"])
    assert invoke(*args)["result"] == symptom
    invoke("symptom", "note", symptom, "--facts", "human wording", "--hypotheses", "bounded")
    invoke("verification", "record", "--json", str(report_file))
    created = invoke(
        "project",
        "session",
        "create",
        "--a",
        "source",
        "--b",
        variant,
        "--symptom",
        symptom,
        "--recipe",
        "native",
    )
    assert created["warnings"] == []
    repository = WorkspaceRepository.open(root)
    try:
        state = repository.state()
        assert state.research.symptoms[symptom].title == "尾" * 200
        assert state.research.symptoms[symptom].facts == "human wording"
        session = state.research.project_sessions[str(created["result"])]
        assert session.focus == "観点：" + "尾" * 200  # noqa: RUF001
        assert session.symptom_id == symptom
        assert state.project.project is not None
        assert state.project.project.current_best_variant_id == "source"
        assert queries.status(repository).health.status == "ok"
    finally:
        repository.close()
