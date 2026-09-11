from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.browser
@pytest.mark.parametrize("width", [375, 1024])
def test_long_labels_and_notes_wrap_without_clipping(width: int) -> None:
    css = Path("ui/src/styles.css").read_text()
    text = "目的と判断の根拠を省略せず最後まで確認する。" * 12
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 800})
        page.set_content(f"""<style>{css}</style>
          <main style="width:160px">
            <p class="queue-focus">{text}</p>
            <strong class="best-id">{text}</strong>
            <div class="completed-row" style="display:block"><p>{text}</p></div>
            <div class="result-pair"><span>{text}</span><small>{text}</small></div>
            <div class="answer-note">{text}</div>
          </main>""")
        for selector in (
            ".queue-focus",
            ".best-id",
            ".completed-row p",
            ".result-pair > span",
            ".result-pair small",
            ".answer-note",
        ):
            item = page.locator(selector)
            assert item.inner_text() == text
            assert item.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            assert item.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
            assert item.evaluate("el => el.clientHeight > 40")
        browser.close()
