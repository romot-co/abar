"""ABAR UI の色の組が WCAG 2.1 AA を満たすか検証する。

色は nibi(`@romot/nibi`)の役割から来る。`ui/src/nibi.css` の `:root` にある
ABAR の別名(`--ink: var(--nibi-color-text)` など)を nibi の役割へ解決し、
`ui/index.html` の `data-nibi-theme` が指すテーマの値を、取り込んだ
nibi のトークン(`ui/vendor/nibi/dist/json/nibi.tokens.json`)から読む。

テキスト系ペア(ink/ink-2/ink-3 と bg/surface/wash、反転ペア、エラー文)が
4.5:1 以上、フォームコントロールの境界(control-line)が 3:1 以上
(WCAG 1.4.11)であることを確認する。落ちたらexit 1。

    uv run python scripts/check_ui_contrast.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIASES_PATH = ROOT / "ui" / "src" / "nibi.css"
INDEX_PATH = ROOT / "ui" / "index.html"
NIBI_PATH = ROOT / "ui" / "vendor" / "nibi"
TOKENS_PATH = NIBI_PATH / "dist" / "json" / "nibi.tokens.json"

AA_NORMAL = 4.5
AA_NON_TEXT = 3.0

TEXT_PAIRS: tuple[tuple[str, str], ...] = (
    ("ink", "bg"),
    ("ink", "surface"),
    ("ink", "wash"),
    ("ink-2", "bg"),
    ("ink-2", "surface"),
    ("ink-3", "surface"),
    ("ink-3", "bg"),
    ("inverse", "ink"),
    # 選好・A/B の反転(nibi 0005)と、エラー文
    ("nibi:on-selected", "nibi:selected"),
    ("nibi:error-text", "nibi:error-subtle"),
)

CONTROL_PAIRS: tuple[tuple[str, str], ...] = (
    ("control-line", "bg"),
    ("control-line", "surface"),
    ("control-line", "wash"),
)


def _luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _ratio(first: str, second: str) -> float:
    lums = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lums[0] + 0.05) / (lums[1] + 0.05)


def aliases_from_css(css: str) -> dict[str, str]:
    """ABAR の別名 → nibi の色の役割(`--ink: var(--nibi-color-text)` → ink: text)。"""
    root = re.search(r":root\s*{([^}]*)}", css)
    if root is None:
        return {}
    return dict(re.findall(r"--([a-z0-9-]+):\s*var\(--nibi-color-([a-z0-9-]+)\)", root.group(1)))


def _themes(html: str) -> list[str]:
    return re.findall(r'data-nibi-theme="(dark|light)"', html) or ["dark"]


def _palette(tokens: dict, theme: str) -> dict[str, str]:
    """nibi のテーマの役割名 → 16進(不透明な色だけ)。エラーは error-<key> に平らにする。"""
    palette: dict[str, str] = {}
    for role, value in tokens["theme"][theme].items():
        if role == "error":
            for key, token in value.items():
                name = "error-" + re.sub(r"[A-Z]", lambda m: "-" + m.group(0).lower(), key)
                if token["$value"].get("alpha", 1) == 1:
                    palette[name] = token["$value"]["hex"]
        elif isinstance(value, dict) and "$value" in value and value["$value"].get("alpha", 1) == 1:
            palette[role] = value["$value"]["hex"]
    return palette


def main() -> int:
    if not TOKENS_PATH.is_file():
        print(f"nibi のトークンが見つかりません: {TOKENS_PATH}(scripts/sync_nibi.py で取り込む)")
        return 1
    aliases = aliases_from_css(ALIASES_PATH.read_text(encoding="utf-8"))
    if not aliases:
        print("ui/src/nibi.css の :root から nibi の役割への別名を抽出できませんでした")
        return 1
    tokens = json.loads(TOKENS_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []
    for theme in _themes(INDEX_PATH.read_text(encoding="utf-8")):
        palette = _palette(tokens, theme)

        def color(name: str, palette: dict[str, str] = palette, theme: str = theme) -> str | None:
            role = name.removeprefix("nibi:") if name.startswith("nibi:") else aliases.get(name)
            value = palette.get(role) if role else None
            if value is None:
                failures.append(f"{theme}: {name} を nibi の色に解決できません")
            return value

        for pairs, floor in ((TEXT_PAIRS, AA_NORMAL), (CONTROL_PAIRS, AA_NON_TEXT)):
            for foreground, background in pairs:
                fg, bg = color(foreground), color(background)
                if fg is None or bg is None:
                    continue
                ratio = _ratio(fg, bg)
                marker = "ok" if ratio >= floor else "FAIL"
                print(f"{theme:5s} {foreground:>16s} on {background:<18s} {ratio:5.2f} {marker}")
                if ratio < floor:
                    failures.append(f"{theme}: {foreground} on {background} = {ratio:.2f}")
    if failures:
        print("\nWCAG AA違反または解決できない色:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("\nすべてのテキストペアが WCAG 2.1 AA (4.5:1)、境界が 3:1 を満たしています")
    return 0


if __name__ == "__main__":
    sys.exit(main())
