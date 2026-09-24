from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright


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


@pytest.mark.browser
@pytest.mark.parametrize("width", [375, 1024])
def test_saved_criterion_stays_small_and_answer_controls_remain_reachable(
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
        page.get_by_role("button", name="続きを聴く", exact=True).click()
        purpose = page.locator(".deck-criterion")
        purpose.wait_for()
        assert purpose.inner_text() == f"目的 {criterion}"
        # nibi の value の役割(本文より1段小さい、密度で変わる)で表示する
        sizes = purpose.evaluate(
            """el => [
              parseFloat(getComputedStyle(el).fontSize),
              parseFloat(getComputedStyle(document.documentElement)
                .getPropertyValue('--nibi-type-value-size')),
              parseFloat(getComputedStyle(document.body).fontSize),
            ]"""
        )
        assert sizes[0] == sizes[1] and sizes[0] < sizes[2]
        assert purpose.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
        assert purpose.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
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
        submit = page.get_by_role("button", name="記録して次へ", exact=True)
        submit.scroll_into_view_if_needed()
        box = submit.bounding_box()
        assert box is not None and box["y"] >= 0 and box["y"] + box["height"] <= 640
        browser.close()
