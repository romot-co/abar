"""nibi(romot のデザインシステム)の生成済みファイルを ui/vendor/nibi へ取り込む。

nibi のリポジトリは非公開なので、ABAR は nibi に依存せず、使うファイルだけを
改変せずに同梱する(MPL-2.0 の LICENSE を添える)。取り込んだ commit は VERSION に残す。

    uv run python scripts/sync_nibi.py ../nibi
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "ui" / "vendor" / "nibi"

# 日本語だけの UI: @font-face なしの core と、IBM Plex Sans JP の woff2 だけ(Lexend・TTF は入れない)
FILES = (
    "LICENSE",
    "dist/web/nibi-core.css",
    "dist/web/fonts-ja.css",
    "dist/json/nibi.tokens.json",
    "fonts/ibm-plex-sans-jp/IBMPlexSansJP-Regular.woff2",
    "fonts/ibm-plex-sans-jp/IBMPlexSansJP-Medium.woff2",
    "fonts/ibm-plex-sans-jp/OFL.txt",
)


def _git(source: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(source), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def sync(source: Path, vendor: Path = VENDOR) -> dict[str, str]:
    missing = [name for name in FILES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(f"nibi に無いファイル: {missing}")
    if _git(source, "status", "--porcelain", "--", "dist", "fonts", "LICENSE"):
        raise RuntimeError("nibi の dist / fonts / LICENSE に未コミットの変更があります")
    package = json.loads((source / "package.json").read_text(encoding="utf-8"))
    version = {"version": package["version"], "commit": _git(source, "rev-parse", "HEAD")}
    if vendor.exists():
        shutil.rmtree(vendor)
    for name in FILES:
        target = vendor / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    (vendor / "VERSION.json").write_text(json.dumps(version, indent=2) + "\n", encoding="utf-8")
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="nibi のチェックアウト")
    version = sync(parser.parse_args().source.resolve())
    print(f"ui/vendor/nibi ← nibi {version['version']} ({version['commit'][:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
