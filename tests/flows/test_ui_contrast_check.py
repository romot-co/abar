"""scripts/check_ui_contrast.py: ABAR の別名を nibi の役割へ解決して WCAG AA を検証する。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts import check_ui_contrast as contrast


def _token(hex_color: str, alpha: float = 1) -> dict[str, Any]:
    return {"$type": "color", "$value": {"hex": hex_color, "alpha": alpha}}


def _write(tmp_path: Path, *, muted: str) -> None:
    (tmp_path / "nibi.css").write_text(
        ":root { --ink: var(--nibi-color-text); --ink-2: var(--nibi-color-text-muted);"
        " --ink-3: var(--nibi-color-text-muted); --bg: var(--nibi-color-bg);"
        " --surface: var(--nibi-color-surface); --wash: var(--nibi-color-control);"
        " --inverse: var(--nibi-color-on-selected); --control-line: var(--nibi-color-line-control);"
        " --radius-card: var(--nibi-radius-panel); }",
        encoding="utf-8",
    )
    (tmp_path / "index.html").write_text('<html data-nibi-theme="light">', encoding="utf-8")
    light: dict[str, Any] = {
        "text": _token("#171B1F"),
        "text-muted": _token(muted),
        "bg": _token("#F7F8F8"),
        "surface": _token("#FFFFFF"),
        "control": _token("#F0F2F3"),
        "on-selected": _token("#FFFFFF"),
        "selected": _token("#171B1F"),
        "line-control": _token("#80858A"),
        "halo": _token("#171B1F", 0.2),
        "error": {"text": _token("#B42318"), "subtle": _token("#FDECEA")},
    }
    (tmp_path / "tokens.json").write_text(json.dumps({"theme": {"light": light}}), encoding="utf-8")


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(contrast, "ALIASES_PATH", tmp_path / "nibi.css")
    monkeypatch.setattr(contrast, "INDEX_PATH", tmp_path / "index.html")
    monkeypatch.setattr(contrast, "TOKENS_PATH", tmp_path / "tokens.json")
    return tmp_path


def test_aliases_map_only_nibi_colour_roles() -> None:
    css = ":root { --ink: var(--nibi-color-text); --speed: var(--nibi-motion-base); }"
    aliases = contrast.aliases_from_css(css)
    assert aliases == {"ink": "text"}


def test_passing_palette_exits_zero(paths: Path) -> None:
    _write(paths, muted="#62676B")
    assert contrast.main() == 0


def test_low_contrast_alias_fails(paths: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(paths, muted="#A0A4A8")
    assert contrast.main() == 1
    assert "ink-2 on bg" in capsys.readouterr().out


def test_missing_nibi_tokens_fail_closed(paths: Path) -> None:
    _write(paths, muted="#62676B")
    (paths / "tokens.json").unlink()
    assert contrast.main() == 1


def test_repository_ui_meets_aa_with_the_vendored_nibi() -> None:
    assert contrast.main() == 0
