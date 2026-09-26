"""受信箱が、聴くもの・確かめるもの・開始できなかったものを隠さないこと(§8.2、C10)。

- 開始できなかったSessionは「完了」の折りたたみに混ぜず、独立した欄に理由の文と印で出す。
- 「全て判定済みです」は、未回答・開始できない・確認待ちのどれもないときだけ。
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from scripts.dev_seed import seed_all_done, seed_blocked, seed_fresh, seed_simplification
from tests.e2e.test_project_ui_v2 import live_server


@pytest.mark.browser
@pytest.mark.parametrize("width", [375, 1024])
def test_blocked_session_is_listed_with_its_reason(
    tmp_path: Path, free_tcp_port: int, width: int
) -> None:
    root = tmp_path / "blocked"
    seed_blocked(root)
    with (
        live_server(root, tmp_path / "other", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 800})
        page.goto(url)
        heading = page.get_by_role("heading", name="開始できない 1 件", exact=True)
        heading.wait_for()
        blocked = page.get_by_role("list", name="開始できないセッション")
        row = blocked.get_by_role("listitem")
        expect(row).to_have_count(1)
        expect(row).to_be_visible()
        expect(row).to_contain_text("音声が欠けたSession")
        # 理由は読める文で(title属性だけにしない)、状態は印と語で(色だけにしない)
        expect(row.locator(".blocked-reason")).to_have_text(
            "理由: 比較する音声を検証できませんでした（欠落または内容の不一致）"  # noqa: RUF001
        )
        expect(row.locator(".blocked-status .nibi-mark--fail")).to_have_count(1)
        expect(row.locator(".blocked-status")).to_have_text("開始できません")
        assert row.get_attribute("title") is None
        # 判定済みとは言わない。完了の折りたたみにも入れない
        assert page.get_by_text("全て判定済み", exact=False).count() == 0
        page.get_by_text("開始できるセッションはありません。", exact=True).wait_for()
        assert page.get_by_text("件を見る", exact=False).count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        browser.close()


@pytest.mark.browser
def test_all_judged_only_when_nothing_waits(tmp_path: Path, free_tcp_port: int) -> None:
    simplification = tmp_path / "simplification"
    all_done = tmp_path / "all-done"
    seed_simplification(simplification)
    seed_all_done(all_done)
    with (
        live_server(simplification, all_done, free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        page.get_by_text("同一の音でした。単純な方へまとめますか。", exact=True).wait_for()
        # 単純化の確認が待っている間は「全て判定済み」と言わない
        assert page.get_by_text("全て判定済み", exact=False).count() == 0
        project = page.get_by_role("combobox", name="プロジェクト")
        project.select_option(label="完了済み: Quiet")
        page.get_by_text("全て判定済みです。", exact=False).wait_for()
        assert page.get_by_role("heading", name="開始できない", exact=False).count() == 0
        browser.close()


@pytest.mark.browser
def test_first_ready_session_leads_and_the_rest_keep_their_own_start(
    tmp_path: Path, free_tcp_port: int
) -> None:
    """進行中がなければ最初の準備済みが次の一手の面に載り、残りの行はそれぞれ控えめな「開始」を持つ(§8.2)。"""
    root = tmp_path / "fresh"
    seed_fresh(root)
    with (
        live_server(root, tmp_path / "other", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        lead = page.locator(".lead-panel")
        lead.get_by_role("heading", name="次に聴く", exact=True).wait_for()
        expect(lead.get_by_role("button", name="聴きはじめる", exact=True)).to_be_visible()
        assert page.locator(".nibi-button--primary").count() == 1
        rows = page.get_by_role("list", name="このあとのセッション").get_by_role("listitem")
        starts = page.get_by_role("list", name="このあとのセッション").get_by_role(
            "button", name="開始", exact=True
        )
        expect(starts).to_have_count(rows.count())
        assert starts.first.evaluate("el => !el.classList.contains('nibi-button--primary')")
        browser.close()
