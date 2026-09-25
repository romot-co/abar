"""受信箱・Deckの画面の組み方(1列、画面下のdock)が仕様の約束を保つこと。

- 受信箱の主操作は一つ(進行中のSessionの「続ける」)。
- 記録ボタンは選好を決めた後だけ回答欄に出る(§2.13)。画面下のdockは弱いskipのリンクだけ。
- Plan付きSessionのskip確認は、押したdockの中に画面内で出て、「続ける」にフォーカスする。
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from scripts.dev_seed import seed
from tests.e2e.test_project_ui_v2 import live_server


@pytest.mark.browser
@pytest.mark.parametrize(("width", "touch"), [(375, True), (1024, False)])
def test_key_hint_only_with_keys_and_no_gap_after_choosing(
    tmp_path: Path, free_tcp_port: int, width: int, touch: bool
) -> None:
    root = tmp_path / "workspace"
    seed(root, project_name="Touch hint test")
    with (
        live_server(root, tmp_path / "other", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": width, "height": 800}, has_touch=touch, is_mobile=touch
        )
        page = context.new_page()
        page.goto(url)
        page.get_by_role("button", name="続ける", exact=True).click()
        page.locator(".slot-switcher button").nth(0).click()
        page.locator(".slot-switcher button").nth(1).click()
        page.locator(".preference-scale button:not(:disabled)").first.wait_for()
        # 指の端末(pointer: coarse)ではキーの案内を出さない
        key_hint = page.get_by_text("キー 1〜5 でも選べます", exact=True)
        if touch:
            expect(key_hint).to_be_hidden()
        else:
            expect(key_hint).to_be_visible()
        page.locator(".preference-scale button").nth(3).click()
        # 選んだ後の空の理由の文は場所を取らない(読み上げの live region としては残る)
        hint = page.locator("#answer-hint")
        expect(hint).to_have_text("")
        expect(hint).to_have_attribute("aria-live", "polite")
        box = hint.bounding_box()
        assert box is None or box["height"] <= 1
        scale = page.locator(".preference-scale").bounding_box()
        after = page.locator(".key-hint" if not touch else ".blocker-question").bounding_box()
        assert scale is not None and after is not None
        gap = page.evaluate(
            "parseFloat(getComputedStyle(document.querySelector('.answer-panel')).rowGap)"
        )
        assert after["y"] - (scale["y"] + scale["height"]) <= gap + 1
        browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("width", [375, 1024])
def test_inbox_and_deck_keep_one_primary_action_and_confirm_in_the_dock(
    tmp_path: Path, free_tcp_port: int, width: int
) -> None:
    root = tmp_path / "workspace"
    seed(root, project_name="Layout test")
    height = 720
    with (
        live_server(root, tmp_path / "other", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(url)
        queue = page.locator(".queue-list")
        queue.wait_for()
        assert page.locator(".nibi-button--primary").count() == 1
        assert queue.locator(".nibi-button--primary").count() == 1
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

        queue.get_by_role("button", name="続ける", exact=True).click()
        dock = page.locator(".answer-dock")
        dock.wait_for()
        assert page.get_by_role("button", name="記録して次へ", exact=True).count() == 0
        skip = dock.get_by_role("button", name="回答せずにこの比較を飛ばす", exact=True)
        skip.click()
        confirm = dock.get_by_role("alertdialog")
        expect(confirm).to_be_visible()
        box = confirm.bounding_box()
        assert box is not None and box["y"] >= 0 and box["y"] + box["height"] <= height
        expect(confirm.get_by_role("button", name="続ける", exact=True)).to_be_focused()
        confirm.get_by_role("button", name="続ける", exact=True).click()
        expect(confirm).to_have_count(0)
        expect(skip).to_be_visible()

        page.locator(".slot-switcher button").nth(1).click()
        page.locator(".slot-switcher button").nth(0).click()
        page.locator(".preference-scale button:not(:disabled)").first.wait_for()
        # 再生の状態は語でも(再生中)、聴いたことは再生の印と別の場所に「✓ 聴いた」
        cards = page.locator(".slot-switcher button")
        expect(cards.nth(0).locator(".slot-state")).to_have_text("再生中")
        expect(cards.nth(1).locator(".slot-state")).to_have_text("")
        for index in (0, 1):
            expect(cards.nth(index).locator(".slot-heard")).to_have_text("聴いた")
            expect(cards.nth(index).locator(".slot-heard .ui-icon")).to_have_count(1)
        expect(cards.nth(0)).to_have_attribute("aria-label", "A、再生中、聴いた。押すと一時停止")
        page.locator(".preference-scale button").nth(1).click()
        # 入力欄はnibiの枠(line-control の 1px)で入力できると分かる(C-3、WCAG 1.4.11)
        memo = page.get_by_role("textbox", name="この比較のメモ")
        line_control = page.evaluate(
            """() => {
              const probe = document.createElement('i');
              probe.style.color = 'var(--nibi-color-line-control)';
              document.body.append(probe);
              const color = getComputedStyle(probe).color;
              probe.remove();
              return color;
            }"""
        )
        expect(memo).to_have_css("border-top-width", "1px")
        expect(memo).to_have_css("border-top-style", "solid")
        expect(memo).to_have_css("border-top-color", line_control)
        submit = page.get_by_role("button", name="記録して次へ", exact=True)
        expect(submit).to_be_enabled()
        # 記録は回答欄の中、その後(文書の順で下)に dock の弱い skip(§2.13)。dock は画面下に留まる
        assert dock.get_by_role("button", name="記録して次へ", exact=True).count() == 0
        assert submit.evaluate(
            "(el, other) => !!(el.compareDocumentPosition(other)"
            " & Node.DOCUMENT_POSITION_FOLLOWING)",
            skip.element_handle(),
        )
        skip_box = skip.bounding_box()
        assert skip_box is not None and skip_box["y"] + skip_box["height"] <= height
        browser.close()
