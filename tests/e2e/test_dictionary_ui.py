"""Dictionary suggestions are optional memo text under the existing listening UI."""

from contextlib import closing
from pathlib import Path
from typing import Literal

import pytest
from playwright.sync_api import expect, sync_playwright

from abar.app import commands
from abar.app.repository import WorkspaceRepository
from tests.e2e.test_abar_21 import _ready_diagnosis  # pyright: ignore[reportPrivateUsage]
from tests.e2e.test_project_ui_v2 import live_server


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1100])
def test_dictionary_chips_stamp_toggle_and_preserve_free_memo(
    tmp_path: Path,
    free_tcp_port: int,
    width: int,
) -> None:
    root = tmp_path / "workspace"
    session_id = _ready_diagnosis(root)
    with closing(WorkspaceRepository.open(root)) as repository:
        terms: tuple[tuple[str, Literal["validated", "rejected"]], ...] = (
            ("尾が揺れる", "validated"),
            ("硬い", "rejected"),
            ("t" * 200, "rejected"),
        )
        for term, status in terms:
            commands.add_dictionary_entry(
                repository,
                term=term,
                definition="Test fixture only",
                status=status,
                actor_id="fixture",
            )
    with (
        live_server(root, tmp_path / "other", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 1000})
        page.goto(url)
        page.get_by_role("button", name="聴きはじめる", exact=True).click()
        page.get_by_role("slider", name="再生位置", exact=True).wait_for()
        loop = page.get_by_role("button", name="ループ", exact=True)
        expect(loop).to_be_enabled()
        loop.click()
        hold = page.get_by_role("button", name="この問いでは判断できない（保留）", exact=True)  # noqa: RUF001
        expect(hold).to_be_enabled(timeout=5000)
        hold.click()
        suggestions = page.locator(".word-chips")
        expect(suggestions.get_by_role("button")).to_have_count(4)
        expect(suggestions.get_by_role("button", name="硬い", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        first = suggestions.get_by_role("button", name="ミョイン", exact=True)
        first.click()
        memo = page.locator(".memo-input")
        expect(memo).to_have_value("ミョイン")
        expect(first).to_have_attribute("aria-pressed", "true")
        stamp = page.locator("#memo-title").inner_text()
        assert " s" in stamp
        loop.click()
        tail = suggestions.get_by_role("button", name="尾が揺れる", exact=True)
        tail.click()
        expect(memo).to_have_value("ミョイン 尾が揺れる")
        assert page.locator("#memo-title").inner_text() == stamp
        first.click()
        expect(memo).to_have_value("尾が揺れる")
        tail.click()
        expect(memo).to_have_value("")
        expect(page.locator("#memo-title")).to_have_text("メモ")
        memo.fill("自由に書いたメモ")
        first.click()
        expect(memo).to_have_value("自由に書いたメモ ミョイン")
        expect(page.locator("#memo-title")).to_have_text("メモ")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.get_by_role("button", name="保留して次へ", exact=True).click()
        expect(
            page.get_by_role("heading", name="この問いでは判断できませんでした", exact=True)
        ).to_be_visible()
        expect(page.get_by_text("自由に書いたメモ ミョイン", exact=True)).to_be_visible()
        browser.close()
    with closing(WorkspaceRepository.open(root)) as repository:
        core = repository.state().research.project_sessions[session_id].core_session_id
        delivery = next(
            d for d in repository.state().compare.deliveries.values() if d.session_id == core
        )
        judgment = repository.state().compare.judgments[delivery.id]
        assert judgment.comment == "自由に書いたメモ ミョイン"
        assert judgment.comment_range is None
        assert judgment.held


@pytest.mark.browser
def test_empty_dictionary_has_no_suggestion_row(tmp_path: Path, free_tcp_port: int) -> None:
    root = tmp_path / "workspace"
    from scripts.dev_seed import seed

    seed(root, project_name="Empty dictionary")
    with (
        live_server(root, tmp_path / "other", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.get_by_role("button", name="続きから", exact=False).click()
        page.locator(".slot-switcher button").nth(0).click()
        page.locator(".slot-switcher button").nth(1).click()
        hold = page.get_by_role("button", name="この問いでは判断できない（保留）", exact=True)  # noqa: RUF001
        expect(hold).to_be_enabled()
        hold.click()
        expect(page.get_by_role("textbox", name="メモ", exact=True)).to_be_visible()
        expect(page.locator(".word-chips")).to_have_count(0)
        browser.close()
