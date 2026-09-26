from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.browser
@pytest.mark.parametrize("width", [375, 1024])
def test_long_labels_and_notes_wrap_without_clipping(width: int) -> None:
    css = (
        Path("ui/vendor/nibi/dist/web/nibi-core.css").read_text()
        + Path("ui/src/styles.css").read_text()
    )
    text = "目的と判断の根拠を省略せず最後まで確認する。" * 12
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 800})
        page.set_content(f"""<style>{css}</style>
          <main style="width:160px">
            <strong class="best-id">{text}</strong>
            <p class="nibi-body answer-comment">{text}</p>
            <span class="nibi-rowlist__sub blocked-reason">{text}</span>
            <p class="nibi-body notice-reason">{text}</p>
          </main>""")
        for selector in (
            ".best-id",
            ".answer-comment",
            ".blocked-reason",
            ".notice-reason",
        ):
            item = page.locator(selector)
            assert item.inner_text() == text
            assert item.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
            assert item.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
            assert item.evaluate("el => el.clientHeight > 40")
        browser.close()


@pytest.mark.browser
@pytest.mark.parametrize("width", [375, 1024])
def test_long_criterion_is_clamped_and_expands_and_answer_controls_remain_reachable(
    tmp_path: Path, free_tcp_port: int, width: int
) -> None:
    from playwright.sync_api import Route

    from scripts.dev_seed import seed
    from tests.e2e.test_project_ui_v2 import live_server

    root = tmp_path / "workspace"
    seed(root, project_name="Purpose test")
    criterion = "アタックと余韻を保ち、不要なノイズだけを減らしているか確認します。" * 12
    with (
        live_server(root, tmp_path / "other", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 640})

        def long_saved_criterion(route: Route) -> None:
            response = route.fetch()
            body = response.json()
            body["criterion_text"] = criterion
            body["criterion_label"] = "目的"
            route.fulfill(response=response, json=body)

        page.route("**/api/deck/active", long_saved_criterion)
        page.goto(url)
        page.get_by_role("button", name="続きから", exact=False).click()
        purpose = page.locator(".deck-criterion")
        purpose.wait_for()
        # 観点は画面の主題の一文(lead)。2行(480px 未満は3行)で止め、「全文を表示」で開く(§2.13)
        assert purpose.inner_text() == criterion
        sizes = purpose.evaluate(
            """el => [
              parseFloat(getComputedStyle(el).fontSize),
              parseFloat(getComputedStyle(document.documentElement)
                .getPropertyValue('--nibi-type-lead-size')),
              parseFloat(getComputedStyle(el).lineHeight),
              el.clientHeight,
            ]"""
        )
        assert sizes[0] == sizes[1]
        lines = round(sizes[3] / sizes[2])
        assert lines == (3 if width < 480 else 2)
        assert purpose.evaluate("el => el.scrollHeight > el.clientHeight + 1")
        toggle = page.get_by_role("button", name="全文を表示", exact=True)
        expect(toggle).to_have_attribute("aria-expanded", "false")
        toggle.click()
        collapse = page.get_by_role("button", name="たたむ", exact=True)
        expect(collapse).to_have_attribute("aria-expanded", "true")
        assert purpose.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
        assert purpose.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
        collapse.click()
        expect(page.get_by_role("button", name="全文を表示", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / f"purpose-{width}.png"), full_page=True)
        page.locator(".slot-switcher button").nth(1).click()
        page.locator(".preference-scale button").nth(2).click()
        # 主題の選択(聴いている A/B と選んだ回答)は両方ともインク反転する(nibi 0005)
        inverted = page.evaluate(
            """() => {
              const probe = document.createElement('i');
              probe.style.color = 'var(--nibi-color-selected)';
              document.body.append(probe);
              const color = getComputedStyle(probe).color;
              probe.remove();
              return color;
            }"""
        )
        expect(page.locator('.preference-scale button[aria-checked="true"]')).to_have_css(
            "background-color", inverted
        )
        expect(page.locator('.slot-switcher button[aria-pressed="true"]')).to_have_css(
            "background-color", inverted
        )
        # 記録は画面下に固定した操作欄(選んだ後だけ)。スクロールしなくても画面の中にある
        submit = page.locator(".answer-dock").get_by_role("button", name="記録して次へ", exact=True)
        box = submit.bounding_box()
        assert box is not None and box["y"] >= 0 and box["y"] + box["height"] <= 640
        browser.close()


@pytest.mark.browser
def test_programmatic_focus_keeps_the_ring_and_errors_use_the_nibi_alert() -> None:
    styles = Path("ui/src/styles.css").read_text()
    # nibi は 400 / 500 だけ。エラーの印は手描きの「!」でなく nibi の alert の印
    assert "font-weight: 600" not in styles
    assert 'content: "!"' not in styles
    assert "InlineError" in Path("ui/src/deck/DeckScreen.tsx").read_text()
    css = Path("ui/vendor/nibi/dist/web/nibi-core.css").read_text() + styles
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 600})
        page.set_content(f"""<style>{css}</style>
          <div class="nibi-segmented nibi-segmented--cards slot-switcher" tabindex="-1"
            role="group" aria-label="試聴"><button class="nibi-segmented__option">A</button></div>
          <main class="screen summary-shell"><h1 tabindex="-1" class="nibi-title">結果</h1></main>
          <p class="nibi-alert nibi-alert--banner inline-error" role="alert">
            <span class="nibi-alert__icon" aria-hidden="true"></span>
            <span class="nibi-alert__text">記録できませんでした。</span></p>""")
        # キーボードの人には、移したフォーカスの輪が見える(比較が変わった時・結果の見出し)
        page.keyboard.press("Shift")
        for selector in (".slot-switcher", ".summary-shell h1"):
            page.locator(selector).evaluate("el => el.focus()")
            expect(page.locator(selector)).to_have_css("outline-style", "solid")
        icon = page.locator(".inline-error .nibi-alert__icon")
        box = icon.bounding_box()
        assert box is not None and box["width"] > 0
        browser.close()
