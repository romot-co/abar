"""再生位置はnibiのスライダー行(位置の形)で、nibi SPEC §7 の操作に従うこと。

- role="slider" と読める時刻(aria-valuetext)を持つ。
- レール上の押下はその位置へ、ドラッグで続けて動かせる。
- 矢印は1ステップ(範囲の1%)、Home / End は最初・最後。
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from scripts.dev_seed import seed
from tests.e2e.test_project_ui_v2 import live_server


@pytest.mark.browser
def test_position_slider_follows_the_nibi_contract(tmp_path: Path, free_tcp_port: int) -> None:
    root = tmp_path / "workspace"
    seed(root, project_name="Slider test")
    with (
        live_server(root, tmp_path / "other", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1024, "height": 800})
        page.goto(url)
        page.get_by_role("button", name="続ける", exact=True).click()
        slider = page.get_by_role("slider", name="再生位置")
        slider.wait_for()
        assert page.locator('input[type="range"]').count() == 0
        assert "nibi-slider--position" in (slider.get_attribute("class") or "")
        expect(slider).not_to_have_attribute("aria-disabled", "true")
        # 位置が再生で動かないよう、再生中のカードを押して止める
        cards = page.locator(".slot-switcher button")
        cards.nth(0).click()
        playing = page.locator('.slot-switcher button[aria-label$="押すと一時停止"]')
        if playing.count():
            playing.click()
        expect(page.locator('.slot-switcher button[aria-label$="押すと一時停止"]')).to_have_count(0)

        maximum = float(slider.get_attribute("aria-valuemax") or "0")
        assert maximum > 0

        def value() -> float:
            return float(slider.get_attribute("aria-valuenow") or "nan")

        slider.focus()
        page.keyboard.press("End")
        assert value() == pytest.approx(maximum)
        page.keyboard.press("Home")
        assert value() == 0
        expect(slider).to_have_attribute("aria-valuetext", f"0:00 / {_clock(maximum)}")
        page.keyboard.press("ArrowRight")
        assert value() == pytest.approx(maximum * 0.01, abs=0.011)

        rail = page.locator(".position-slider .nibi-slider__rail").bounding_box()
        assert rail is not None
        middle_y = rail["y"] + rail["height"] / 2
        page.mouse.click(rail["x"] + rail["width"] / 2, middle_y)
        assert value() == pytest.approx(maximum / 2, abs=maximum * 0.03)
        page.mouse.move(rail["x"] + rail["width"] * 0.25, middle_y)
        page.mouse.down()
        assert value() == pytest.approx(maximum * 0.25, abs=maximum * 0.03)
        page.mouse.move(rail["x"] + rail["width"] * 0.75, middle_y, steps=5)
        page.mouse.up()
        assert value() == pytest.approx(maximum * 0.75, abs=maximum * 0.03)
        browser.close()


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"
