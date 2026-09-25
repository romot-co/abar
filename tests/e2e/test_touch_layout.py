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
