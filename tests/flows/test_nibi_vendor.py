"""ui/vendor/nibi: 非公開の nibi から、使う生成済みファイルだけを改変せず同梱する。"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts import sync_nibi

VENDOR = sync_nibi.VENDOR


def test_vendored_files_are_complete_and_versioned() -> None:
    for name in sync_nibi.FILES:
        assert (VENDOR / name).is_file(), name
    version = json.loads((VENDOR / "VERSION.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", version["version"])
    assert re.fullmatch(r"[0-9a-f]{40}", version["commit"])
    assert (VENDOR / "LICENSE").read_text(encoding="utf-8").startswith("Mozilla Public License")


def test_japanese_ui_ships_plex_woff2_only() -> None:
    web = VENDOR / "dist" / "web"
    assert "@font-face" not in (web / "nibi-core.css").read_text(encoding="utf-8")
    fonts = (web / "fonts-ja.css").read_text(encoding="utf-8")
    urls = re.findall(r'url\("([^"]+)"\)', fonts)
    assert urls and "Lexend" not in fonts and ".ttf" not in fonts
    for url in urls:
        assert url.endswith(".woff2") and (web / url).resolve().is_file(), url
    shipped = {path.suffix for path in VENDOR.rglob("*") if path.is_file()}
    assert ".ttf" not in shipped


def test_ui_imports_only_the_vendored_nibi() -> None:
    main = Path("ui/src/main.tsx").read_text(encoding="utf-8")
    assert '"../vendor/nibi/dist/web/nibi-core.css"' in main
    assert '"../vendor/nibi/dist/web/fonts-ja.css"' in main
    assert "@romot/nibi" not in Path("ui/package.json").read_text(encoding="utf-8")


def _nibi_checkout(root: Path) -> Path:
    for name in sync_nibi.FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name}\n", encoding="utf-8")
    (root / "package.json").write_text('{"version": "9.9.9"}', encoding="utf-8")
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "nibi"], check=True)
    return root


def test_sync_copies_the_listed_files_and_records_the_commit(tmp_path: Path) -> None:
    source = _nibi_checkout(tmp_path / "nibi")
    vendor = tmp_path / "vendor"
    (vendor / "stale.txt").parent.mkdir(parents=True)
    (vendor / "stale.txt").write_text("old", encoding="utf-8")
    version = sync_nibi.sync(source, vendor)
    assert version["version"] == "9.9.9" and len(version["commit"]) == 40
    assert sorted(str(p.relative_to(vendor)) for p in vendor.rglob("*") if p.is_file()) == sorted(
        [*sync_nibi.FILES, "VERSION.json"]
    )


def test_sync_refuses_uncommitted_generated_files(tmp_path: Path) -> None:
    source = _nibi_checkout(tmp_path / "nibi")
    (source / "dist" / "web" / "nibi-core.css").write_text("edited", encoding="utf-8")
    with pytest.raises(RuntimeError):
        sync_nibi.sync(source, tmp_path / "vendor")
