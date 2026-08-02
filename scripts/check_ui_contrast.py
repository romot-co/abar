"""ui/src/styles.css のカラートークンが WCAG 2.1 AA を満たすか検証する。

テキスト系ペア(ink/ink-2/ink-3 と bg/surface/wash、反転ペア)が
4.5:1 以上であることを確認する。落ちたらexit 1。

    uv run python scripts/check_ui_contrast.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

CSS_PATH = Path(__file__).resolve().parent.parent / "ui" / "src" / "styles.css"
TOKENS = (
    "bg",
    "surface",
    "wash",
    "ink",
    "ink-2",
    "ink-3",
    "inverse",
)
AA_NORMAL = 4.5

TEXT_PAIRS: tuple[tuple[str, str], ...] = (
    ("ink", "bg"),
    ("ink", "surface"),
    ("ink", "wash"),
    ("ink-2", "bg"),
    ("ink-2", "surface"),
    ("ink-3", "surface"),
    ("ink-3", "bg"),
    ("inverse", "ink"),
)


def _luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _ratio(first: str, second: str) -> float:
    lums = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lums[0] + 0.05) / (lums[1] + 0.05)


def _extract_themes(css: str) -> list[dict[str, str]]:
    themes: list[dict[str, str]] = []
    for block in re.findall(r":root\s*{([^}]*)}", css):
        tokens: dict[str, str] = {}
        for name, value in re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})", block):
            if name in TOKENS:
                tokens[name] = value
        if tokens:
            themes.append(tokens)
    return themes


def main() -> int:
    themes = _extract_themes(CSS_PATH.read_text(encoding="utf-8"))
    if not themes:
        print("styles.css からカラーテーマを抽出できませんでした")
        return 1
    failures: list[str] = []
    for index, tokens in enumerate(themes):
        theme = "light" if index == 0 else f"theme-{index + 1}"
        missing = [token for token in TOKENS if token not in tokens]
        if missing:
            failures.append(f"{theme}: トークン欠落 {missing}")
            continue
        for foreground, background in TEXT_PAIRS:
            ratio = _ratio(tokens[foreground], tokens[background])
            marker = "ok" if ratio >= AA_NORMAL else "FAIL"
            print(f"{theme:5s} {foreground:>8s} on {background:<14s} {ratio:5.2f} {marker}")
            if ratio < AA_NORMAL:
                failures.append(f"{theme}: {foreground} on {background} = {ratio:.2f}")
    if failures:
        print("\nWCAG AA違反:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("\nすべてのテキストペアが WCAG 2.1 AA (4.5:1) を満たしています")
    return 0


if __name__ == "__main__":
    sys.exit(main())
