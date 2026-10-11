"""The same Deck supports looping, ranged notes and held human answers."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from abar.app import commands, queries
from abar.app.repository import WorkspaceRepository
from abar.compare.models import RecipeRef
from scripts.dev_seed import seed_diagnosis
from tests.e2e.test_project_ui_v2 import live_server


def _ready_diagnosis(root: Path) -> str:
    seed_diagnosis(root)
    repository = WorkspaceRepository.open(root)
    try:
        state = repository.state()
        symptom = next(iter(state.research.symptoms.values()))
        variant = next(iter(state.compare.variants))
        return commands.create_observation_session(
            repository,
            first_variant="source",
            second_variant=variant,
            symptom_id=symptom.id,
            recipe=RecipeRef("native"),
            actor_id="agent",
        )
    finally:
        repository.close()


@pytest.mark.browser
def test_loop_range_auto_switch_stamps_hold_and_reveal(tmp_path: Path, free_tcp_port: int) -> None:
    root = tmp_path / "workspace"
    session_id = _ready_diagnosis(root)
    with (
        live_server(root, tmp_path / "other", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1100, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        expect(page.get_by_text("回帰の印: ミョイン", exact=True)).to_be_visible()
        page.get_by_role("button", name="聴きはじめる", exact=True).click()
        expect(
            page.get_by_role("heading", name="この観点では、どちらを残しますか？", exact=True)  # noqa: RUF001
        ).to_be_visible()
        assert page.get_by_text("diagnostic-ablation", exact=True).count() == 0
        position = page.get_by_role("slider", name="再生位置", exact=True)
        expect(position).not_to_have_attribute("aria-disabled", "true")
        toggle = page.get_by_role("button", name="ループ", exact=True)
        toggle.click()
        start = page.get_by_role("slider", name="ループ範囲 始点", exact=True)
        end = page.get_by_role("slider", name="ループ範囲 終点", exact=True)
        expect(start).to_be_visible()
        expect(end).to_be_visible()
        expect(page.locator(".loop-band")).to_have_count(1)
        # The shortened automatic loop makes both sides audible without manual switching.
        hold = page.get_by_role("button", name="この問いでは判断できない（保留）", exact=True)  # noqa: RUF001
        expect(hold).to_be_enabled(timeout=5000)
        assert page.locator('.slot-switcher button[aria-label*="聴いた"]').count() == 2
        # Pause, then test the handles independently of moving playback.
        page.locator('.slot-switcher button[aria-label$="押すと一時停止"]').click()
        end.focus()
        page.keyboard.press("End")
        assert float(end.get_attribute("aria-valuenow") or "0") == pytest.approx(
            float(position.get_attribute("aria-valuemax") or "0"), abs=0.011
        )
        start.focus()
        page.keyboard.press("End")
        assert float(end.get_attribute("aria-valuenow") or "0") - float(
            start.get_attribute("aria-valuenow") or "0"
        ) == pytest.approx(0.25)
        page.keyboard.press("Home")
        assert float(start.get_attribute("aria-valuenow") or "nan") == 0
        page.keyboard.press("ArrowRight")
        initial_start = float(start.get_attribute("aria-valuenow") or "0")
        page.keyboard.press("Shift+ArrowRight")
        fine_start = float(start.get_attribute("aria-valuenow") or "0")
        assert fine_start - initial_start == pytest.approx(initial_start * 0.1, abs=1e-6)
        # Pointer drag changes just the endpoint and keeps the minimum range.
        box = start.bounding_box()
        assert box is not None
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + 40, box["y"] + box["height"] / 2, steps=3)
        page.mouse.up()
        assert float(start.get_attribute("aria-valuenow") or "0") > fine_start
        page.get_by_role("radio", name="3 互角", exact=True).click()
        page.get_by_role("button", name="B に問題", exact=True).click()
        problem = page.get_by_role(
            "textbox",
            name=re.compile(r"B の問題 · \d+\.\d{2} – \d+\.\d{2} s"),  # noqa: RUF001
        )
        problem.fill("ミョイン")
        memo = page.get_by_role("textbox", name="メモ", exact=True)
        memo.fill("尾が揺れる")
        stamp = page.locator("#memo-title").inner_text()
        toggle.click()
        expect(page.locator(".loop-band")).to_have_count(0)
        expect(problem).to_be_visible()
        assert page.locator("#memo-title").inner_text() == stamp
        page.get_by_role("button", name="A に問題", exact=True).click()
        expect(page.get_by_role("textbox", name="A の問題", exact=True)).to_be_visible()
        # Re-enable restores the remembered range; changing it must not overwrite stamps.
        toggle.click()
        assert float(start.get_attribute("aria-valuenow") or "0") > fine_start
        start.focus()
        page.keyboard.press("Home")
        assert page.locator("#memo-title").inner_text() == stamp
        # H works with the range handle focused, while text input keeps its own keys.
        page.keyboard.press("h")
        expect(hold).to_have_attribute("aria-pressed", "true")
        expect(page.get_by_role("radio", name="3 互角", exact=True)).to_have_attribute(
            "aria-checked", "false"
        )
        page.get_by_role("button", name="保留して次へ", exact=True).click()
        expect(
            page.get_by_role("heading", name="この問いでは判断できませんでした", exact=True)
        ).to_be_visible()
        expect(page.get_by_text("保留 1", exact=True)).to_be_visible()
        page.get_by_role("button", name="候補の正式名", exact=False).click()
        kind_name = page.locator(".names-disclosure .candidate-name").filter(
            has_text="diagnostic-ablation"
        )
        expect(kind_name).to_be_visible()
        expect(kind_name).to_contain_text("· アブレーション")
        assert errors == []
        browser.close()
    repository = WorkspaceRepository.open(root)
    try:
        result = queries.session_result(repository, session_id)
        assert result.held_count == 1
        session = repository.state().research.project_sessions[session_id]
        delivery = next(
            item
            for item in repository.state().compare.deliveries.values()
            if item.session_id == session.core_session_id
        )
        judgment = repository.state().compare.judgments[delivery.id]
        assert judgment.held and judgment.preference is None
        assert judgment.blockers["b"].range is not None
        assert judgment.blockers["a"].range is None
        assert judgment.comment_range == judgment.blockers["b"].range
        assert judgment.telemetry.loops
        assert (
            sum(loop.listen_ms["a"] + loop.listen_ms["b"] for loop in judgment.telemetry.loops) > 0
        )
        # Automatic alternation has not been reported as manual switches.
        assert judgment.telemetry.switches == 0
    finally:
        repository.close()


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1024])
def test_diagnosis_fixture_retains_existing_inbox_and_result_layout(
    tmp_path: Path, free_tcp_port: int, width: int
) -> None:
    root = tmp_path / "workspace"
    seed_diagnosis(root)
    with (
        live_server(root, tmp_path / "other", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(url)
        expect(page.get_by_text("回帰の印: ミョイン", exact=True)).to_be_visible()
        history = page.get_by_role("group", name="完了したセッション")
        history.get_by_role("button", name=re.compile("結果を見る: 観点：尾のミョイン")).click()  # noqa: RUF001
        expect(
            page.get_by_role("heading", name="この問いでは判断できませんでした", exact=True)
        ).to_be_visible()
        expect(page.get_by_text(re.compile("ミョイン.*0.20.*0.80"))).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()
