# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Page, sync_playwright

from abar.server import create_app
from scripts.dev_seed import seed, seed_degraded


@contextmanager
def live_server(root: Path, other_root: Path, port: int) -> Generator[str]:
    origin = f"http://127.0.0.1:{port}"
    application = create_app(
        root,
        workspace_roots=(root, other_root),
        automation_token="automation-test-token",
        interaction_token="interaction-test-token",
        allowed_origins=frozenset({origin}),
    )
    server = uvicorn.Server(
        uvicorn.Config(application, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10.0
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=2.0)
        raise RuntimeError("test server did not start")
    try:
        yield f"{origin}/#token=interaction-test-token"
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


@pytest.mark.browser
def test_project_inbox_deck_and_completion_match_v7(
    tmp_path: Path,
    free_tcp_port: int,
) -> None:
    workspace = tmp_path / "browser-workspace"
    other_workspace = tmp_path / "browser-workspace-noct"
    seed(workspace, project_name="Xifa")
    seed(
        other_workspace,
        project_name="Noct",
        brief="Tighter low end, keep the vocal forward",
    )
    with (
        live_server(workspace, other_workspace, free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        _exercise_project_deck(page, url)
        browser.close()
    assert errors == []


def _exercise_project_deck(page: Page, url: str) -> None:
    page.goto(url)
    project = page.get_by_role("combobox", name="プロジェクト")
    project.wait_for()
    assert project.input_value() == project.locator("option", has_text="Xifa").get_attribute(
        "value"
    )
    project.select_option(label="Noct")
    page.get_by_text("Tighter low end, keep the vocal forward", exact=True).wait_for()
    project.select_option(label="Xifa")
    page.get_by_text("Increase density without losing attack or air", exact=True).wait_for()
    page.get_by_role("heading", name="未回答", exact=True).wait_for()
    assert page.get_by_role("button", name="Projectを作らず比較する").count() == 0
    # §8.2: 目的 → 現在最良(指標)→ 未回答 → 完了 N 件
    queue_box = page.locator(".queue-section").bounding_box()
    state_box = page.locator(".state-card").bounding_box()
    assert queue_box is not None and state_box is not None
    assert state_box["y"] < queue_box["y"]
    completed_sessions = page.get_by_text("完了 3 件を見る", exact=True)
    current_best_heading = page.get_by_role("heading", name="現在最良", exact=True)
    completed_sessions.wait_for()
    current_best_heading.wait_for()
    completed_box = completed_sessions.bounding_box()
    current_best_box = current_best_heading.bounding_box()
    assert completed_box is not None and current_best_box is not None
    assert current_best_box["y"] < completed_box["y"]
    assert page.get_by_text("完了した判定", exact=False).count() == 0
    assert page.get_by_text("支持", exact=True).count() == 0
    assert page.get_by_text("score", exact=True).count() == 0
    assert page.get_by_text("blocker", exact=True).count() == 0
    page.get_by_text("DENSITY", exact=True).wait_for()
    page.get_by_text("ATTACK LOSS", exact=True).wait_for()
    page.get_by_text("目標", exact=True).wait_for()
    page.get_by_text("制約", exact=True).wait_for()
    # 説明文・列見出し・前回からの変化は出さない(§8.2)
    assert page.get_by_text("音像を潰さず、知覚上の密度を高める", exact=True).count() == 0
    assert page.get_by_text("トランジェントの輪郭を失っていないか", exact=True).count() == 0
    assert page.locator(".indicator-track").count() == 0
    assert page.get_by_text("合格", exact=True).count() == 2
    assert page.locator(".guard-badge").count() == 2
    assert page.locator(".guard-badge .nibi-mark").count() == 2
    indicator_rows = page.locator(".indicator-row")
    assert indicator_rows.count() >= 4
    for selector in (
        ".indicator-label",
        ".indicator-value",
        ".indicator-status",
    ):
        column_left_edges = [
            round(box["x"])
            for index in range(indicator_rows.count())
            if (box := indicator_rows.nth(index).locator(selector).bounding_box()) is not None
        ]
        assert len(set(column_left_edges)) == 1

    page.get_by_role("button", name="続ける", exact=True).click()
    page.locator(".slot-switcher").wait_for()
    assert page.get_by_text("BLIND", exact=True).count() == 0
    assert page.locator(".preference-scale button:disabled").count() == 5
    assert page.locator(".progress-track").count() == 0
    assert page.locator(".deck-header").get_by_text("この比較を飛ばす", exact=True).count() == 0
    page.get_by_role("button", name="回答せずにこの比較を飛ばす", exact=True).wait_for()
    # ヘッダーは戻る操作と n / N だけ(Recipe は出さない、§2.13)
    assert page.get_by_text("Recipe matched-v1", exact=True).count() == 0
    assert page.get_by_role("button", name="再生", exact=True).count() == 0

    for remaining in (2, 1):
        page.locator(".slot-switcher button").nth(0).click()
        page.locator(".slot-switcher button").nth(1).click()
        page.locator(".preference-scale button:not(:disabled)").first.wait_for()
        assert page.get_by_text("補足（任意）· 残せない問題", exact=True).count() == 0  # noqa: RUF001
        page.locator(".preference-scale button").nth(3).click()
        page.get_by_text("補足（任意）· 残せない問題", exact=True).wait_for()  # noqa: RUF001
        page.get_by_role("button", name="A に問題", exact=True).wait_for()
        page.get_by_role("button", name="B に問題", exact=True).wait_for()
        page.get_by_role("button", name="記録して次へ", exact=True).click()
        if remaining > 1:
            page.locator(".slot-switcher").wait_for()

    page.locator("#verdict-title").wait_for()
    assert page.locator("#verdict-title").text_content() in {
        "現在最良を維持",
        "現在最良を dense-chorus-v2 に更新",
    }
    assert page.locator(".result-identity").count() == 0
    assert page.locator(".answer-table-row").count() == 3
    assert page.locator(".result-pair").count() == 3
    assert page.get_by_text("素材", exact=True).count() == 3
    assert page.locator(".answer-table-row .answer-gauge").count() == 3
    assert page.locator(".verdict-reasons .nibi-mark").count() >= 1
    assert page.locator(".verdict-stats").count() == 0
    assert page.get_by_role("heading", name="聴き直す").count() == 0
    assert page.get_by_role("textbox").count() == 0
    page.get_by_role("button", name="受信箱へ", exact=True).click()

    page.locator(".completed-sessions .nibi-disclosure__header").click()
    page.get_by_role("button", name="結果を見る: リバーブテイルの濁り").click()
    page.get_by_text(
        "支持が多い方向はありますが、優勢条件には届きませんでした",
        exact=False,
    ).wait_for()
    # 件数と必要数を言葉で(「2 / 3」のような読めない形にしない)。届かないのは失敗の印にしない
    page.get_by_text(
        "どちらも優勢に届かない: 3件中、最多はdense-chorus-v2の1件（必要 2件）",  # noqa: RUF001
        exact=True,
    ).wait_for()
    assert page.locator(".verdict-reasons li").first.locator(".nibi-mark--fail").count() == 0
    # ゲージは候補の向きに固定する(左 = 組の1つ目、右 = 2つ目)。A/Bの位置では描かない
    legend = page.locator(".gauge-legend")
    assert legend.locator(".gauge-end.start").inner_text() == "原音"
    assert legend.locator(".gauge-end.end").inner_text() == "dense-chorus-v2"
    gauges = page.locator(".answer-table-row .answer-gauge")
    orientation = gauges.evaluate_all(
        """els => els.map(el => [el.getAttribute('aria-label'), el.dataset.orientation,
          [...el.children].findIndex(cell => cell.classList.contains('active'))])"""
    )
    assert orientation[0] == ["dense-chorus-v2を明確に支持", "directed", 4]
    assert orientation[2][1] == "symmetric"
    page.get_by_text("同一音の確認: 差を報告", exact=True).wait_for()
    page.get_by_text("再現性の確認: 片方tie", exact=True).wait_for()
    page.get_by_text("同一音: 差を報告（明確）", exact=True).wait_for()  # noqa: RUF001
    page.get_by_text("再現性: 片方tie（今回: 互角）", exact=True).wait_for()  # noqa: RUF001
    page.get_by_text("原音", exact=True).first.wait_for()
    page.get_by_text("Recipe matched-v1", exact=True).wait_for()
    assert page.locator(".result-pair").count() == 5
    assert page.get_by_role("button", name="次へ", exact=False).count() == 0


@pytest.mark.browser
def test_unconnected_browser_explains_connection(tmp_path: Path, free_tcp_port: int) -> None:
    with (
        live_server(tmp_path / "one", tmp_path / "two", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(url.split("#")[0])
        page.get_by_text("ABARを開けません", exact=True).wait_for()
        assert "このブラウザはまだ接続されていません" in page.locator("body").inner_text()
        browser.close()


@pytest.mark.browser
def test_old_api_shape_shows_recovery_instead_of_blank_screen(
    tmp_path: Path, free_tcp_port: int
) -> None:
    with (
        live_server(tmp_path / "one", tmp_path / "two", free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route("**/api/project", lambda route: route.fulfill(json={"project_id": "old"}))
        page.goto(url)
        page.get_by_text("画面を表示できません", exact=True).wait_for()
        assert page.get_by_role("button", name="再読み込み", exact=True).is_visible()
        browser.close()


@pytest.mark.browser
def test_degraded_workspace_keeps_the_project_picker(
    tmp_path: Path,
    free_tcp_port: int,
) -> None:
    workspace = tmp_path / "healthy"
    degraded = tmp_path / "degraded"
    seed(workspace, project_name="Xifa")
    seed_degraded(degraded)
    with (
        live_server(workspace, degraded, free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        project = page.get_by_role("combobox", name="プロジェクト")
        project.select_option(label="停止: Degraded")
        page.get_by_role("heading", name="Workspaceを読み込めません").wait_for()
        # The selection is remembered, so without the picker there would be no way back.
        page.reload()
        page.get_by_role("heading", name="Workspaceを読み込めません").wait_for()
        project.select_option(label="Xifa")
        page.get_by_role("heading", name="未回答", exact=True).wait_for()
        browser.close()
