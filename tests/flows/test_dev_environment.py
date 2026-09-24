"""The local development environment: scenario seeds, the mock agent and the launcher."""

import socket
from collections.abc import Callable
from pathlib import Path

import pytest

from abar.app import commands, queries
from abar.app.repository import WorkspaceRepository
from abar.app.state import ABARState
from scripts.dev import _free_port  # pyright: ignore[reportPrivateUsage]
from scripts.dev_agent import MockAgent
from scripts.dev_seed import (
    SCENARIOS,
    _answer_for_variant,  # pyright: ignore[reportPrivateUsage]
    seed_scenarios,
)


def _statuses(state: ABARState) -> list[str]:
    return [runtime.status for runtime in state.compare.session_runtime.values()]


def _project_statuses(state: ABARState) -> list[str]:
    return [
        state.compare.session_runtime[item.core_session_id].status
        for item in state.research.project_sessions.values()
    ]


def _check_standard(repository: WorkspaceRepository) -> None:
    state = repository.state()
    assert "active" in _project_statuses(state)
    assert "ready" in _project_statuses(state)
    assert "ended" in _project_statuses(state)
    assert state.research.indicators


def _check_fresh(repository: WorkspaceRepository) -> None:
    state = repository.state()
    assert _project_statuses(state) == ["ready", "ready"]
    assert state.project.project is not None
    assert state.project.project.current_best_variant_id == "source"


def _check_all_done(repository: WorkspaceRepository) -> None:
    state = repository.state()
    assert set(_project_statuses(state)) == {"ended"}
    assert state.project.project is not None
    assert state.project.project.current_best_variant_id != "source"


def _check_quick_listen(repository: WorkspaceRepository) -> None:
    state = repository.state()
    linked = {item.core_session_id for item in state.research.project_sessions.values()}
    assert any(
        runtime.status == "active" and session_id not in linked
        for session_id, runtime in state.compare.session_runtime.items()
    )


def _check_simplification(repository: WorkspaceRepository) -> None:
    assert queries.project_dashboard(repository).pending_simplifications


def _check_blocked(repository: WorkspaceRepository) -> None:
    assert "blocked" in _statuses(repository.state())


def _check_degraded(repository: WorkspaceRepository) -> None:
    assert repository.replay().degraded is not None


def _check_no_project(repository: WorkspaceRepository) -> None:
    assert repository.state().project.project is None


CHECKS: dict[str, Callable[[WorkspaceRepository], None]] = {
    "standard": _check_standard,
    "fresh": _check_fresh,
    "all-done": _check_all_done,
    "quick-listen": _check_quick_listen,
    "simplification": _check_simplification,
    "blocked": _check_blocked,
    "degraded": _check_degraded,
    "no-project": _check_no_project,
}


def test_every_scenario_has_a_check() -> None:
    assert set(CHECKS) == set(SCENARIOS)


@pytest.mark.parametrize("name", tuple(SCENARIOS))
def test_scenario_seeds_the_state_it_names(tmp_path: Path, name: str) -> None:
    (created,) = seed_scenarios(tmp_path, (name,))
    repository = WorkspaceRepository.open(created)
    try:
        CHECKS[name](repository)
    finally:
        repository.close()


def test_existing_scenarios_are_kept_unless_reset(tmp_path: Path) -> None:
    assert seed_scenarios(tmp_path, ("no-project",))
    assert seed_scenarios(tmp_path, ("no-project",)) == ()
    assert seed_scenarios(tmp_path, ("no-project",), reset=True) == (tmp_path / "no-project",)


def test_mock_agent_reports_results_measures_new_best_and_refills(tmp_path: Path) -> None:
    (workspace,) = seed_scenarios(tmp_path, ("fresh",))
    agent = MockAgent(workspace, keep_ready=2)
    assert agent.tick() == []

    repository = WorkspaceRepository.open(workspace)
    try:
        state = repository.state()
        best_update = next(plan for plan in state.project.best_update_plans.values())
        commands.start_session(repository, best_update.session_id, allocation_seed=5)
        # The human answers; the agent never does.
        _answer_for_variant(repository, best_update.session_id, best_update.proposed_variant_id)
    finally:
        repository.close()

    log = agent.tick()

    assert any("現在最良を更新" in line for line in log)
    assert any("準備" in line for line in log)
    repository = WorkspaceRepository.open(workspace)
    try:
        state = repository.state()
        project = state.project.project
        assert project is not None
        assert project.current_best_variant_id == best_update.proposed_variant_id
        assert _project_statuses(state).count("ready") == 2
        assert state.research.notes
        dashboard = queries.project_dashboard(repository)
        assert {item.label for item in dashboard.indicators} >= {"DENSITY", "ATTACK LOSS"}
        judgments = [
            event
            for event in repository.events.read_all()
            if event.event_type == "judgment.recorded"
        ]
        assert len(judgments) == 3  # only the human's answers
    finally:
        repository.close()


def test_mock_agent_leaves_degraded_and_projectless_workspaces_alone(tmp_path: Path) -> None:
    for name in ("degraded", "no-project"):
        (workspace,) = seed_scenarios(tmp_path, (name,))
        before = _event_count(workspace)
        assert len(MockAgent(workspace).tick()) == 1
        assert _event_count(workspace) == before


def test_launcher_skips_ports_that_are_already_served() -> None:
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        assert _free_port(port) != port


def _event_count(workspace: Path) -> int:
    repository = WorkspaceRepository.open(workspace)
    try:
        return len(repository.events.read_all())
    finally:
        repository.close()
