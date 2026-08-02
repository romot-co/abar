from pathlib import Path

from typer.testing import CliRunner

from abar.cli import app


def test_cli_exposes_only_v2_top_level_surface() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("listen", "ui", "project", "material", "variant", "note", "indicator"):
        assert command in result.stdout
    for removed in ("crank", "candidate", "board", "deck"):
        assert removed not in result.stdout


def test_agent_document_tracks_standard_loop_commands() -> None:
    document = Path("AGENTS.md").read_text(encoding="utf-8")
    for command in ("abar --json status", "project show", "note", "variant", "project session"):
        assert command in document
