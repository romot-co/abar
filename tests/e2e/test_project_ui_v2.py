# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import re
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Page, expect, sync_playwright

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
    page.get_by_role("heading", name="途中の試聴", exact=True).wait_for()
    # 見出しの段: 題名(h1、display)= Project名、欄(h2、heading)。IDは見出しでない値(§8.2)
    expect(page.get_by_role("heading", level=1)).to_have_count(1)
    expect(page.get_by_role("heading", level=1, name="Xifa", exact=True)).to_have_count(1)
    assert page.get_by_role("heading", level=2).all_inner_texts() == [
        "途中の試聴",
        "このあと 1 件",
        "これまで",
        "現在最良",
    ]
    assert page.get_by_role("heading", name="dense-chorus-v2").count() == 0
    sizes = page.evaluate(
        """() => [
          parseFloat(getComputedStyle(
            document.querySelector('.project-title .nibi-display')).fontSize),
          parseFloat(getComputedStyle(document.querySelector('#queue-heading')).fontSize),
          parseFloat(getComputedStyle(document.querySelector('#queue-heading')).fontWeight),
        ]"""
    )
    assert sizes[0] > sizes[1]
    assert sizes[2] == 500
    assert page.get_by_role("button", name="Projectを作らず比較する").count() == 0
    # 次の一手の面は画面に1つで反転、主ボタンは画面に1つ(nibi 0014 D-2)
    lead = page.locator(".lead-panel")
    expect(lead).to_have_count(1)
    expect(lead).to_have_class(re.compile(r"nibi-panel--lead"))
    assert page.locator(".nibi-button--primary").count() == 1
    expect(lead.get_by_role("button", name="続きから（2 / 3）", exact=True)).to_be_visible()  # noqa: RUF001
    # このあと: 残りの行は自分の操作(進行中がある間は押せない理由を語で)
    queue = page.get_by_role("list", name="このあとのセッション")
    expect(queue.get_by_role("listitem")).to_have_count(1)
    expect(queue.get_by_text("進行中の完了後", exact=True)).to_have_count(1)
    # 横の欄: 900px 以上は2列(現在最良は右)
    side = page.locator(".inbox-side").bounding_box()
    main = page.locator(".queue-section").bounding_box()
    assert side is not None and main is not None
    assert side["x"] > main["x"] + main["width"]
    # これまで: 新しい順に開いたまま並び、行を押すと結果
    history = page.get_by_role("group", name="完了したセッション")
    expect(history.get_by_role("button")).to_have_count(3)
    assert page.get_by_text("件を見る", exact=False).count() == 0
    assert page.get_by_text("支持", exact=True).count() == 0
    assert page.get_by_text("score", exact=True).count() == 0
    page.get_by_text("DENSITY", exact=True).wait_for()
    page.get_by_text("ATTACK LOSS", exact=True).wait_for()
    page.get_by_text("目標", exact=True).wait_for()
    page.get_by_text("守る性質", exact=True).wait_for()
    # 説明文・前回からの変化は出さない(§8.2)
    assert page.get_by_text("音像を潰さず、知覚上の密度を高める", exact=True).count() == 0
    assert page.locator(".indicator-track").count() == 0
    assert page.get_by_text("合格", exact=True).count() == 2
    assert page.locator(".guard-badge .nibi-mark").count() == 2
    indicator_rows = page.locator(".indicator-row")
    assert indicator_rows.count() >= 4
    # 名前は左、値は右寄せ(右端が揃う)、同じ単位は小数の桁を揃える
    right_edges = {
        round(box["x"] + box["width"])
        for index in range(indicator_rows.count())
        if (box := indicator_rows.nth(index).locator(".indicator-value").bounding_box()) is not None
    }
    assert len(right_edges) == 1
    values = page.locator(".indicator-row .indicator-number").all_inner_texts()
    assert "0.90" in values and "0.97" in values

    lead.get_by_role("button", name="続きから", exact=False).click()
    page.locator(".slot-switcher").wait_for()
    assert page.get_by_text("BLIND", exact=True).count() == 0
    assert page.locator(".preference-scale button:disabled").count() == 5
    page.get_by_text("両方を聴くと選べます", exact=False).wait_for()
    assert page.locator(".progress-track").count() == 0
    dock = page.locator(".answer-dock")
    dock.get_by_role("button", name="回答せずにこの比較を飛ばす", exact=True).wait_for()
    # ヘッダーは戻る操作と n / N だけ(Recipe は出さない、§2.13)
    assert page.get_by_text("Recipe matched-v1", exact=True).count() == 0
    assert page.get_by_role("button", name="再生", exact=True).count() == 0

    for remaining in (2, 1):
        page.locator(".slot-switcher button").nth(0).click()
        page.locator(".slot-switcher button").nth(1).click()
        page.locator(".preference-scale button:not(:disabled)").first.wait_for()
        # 選ぶまでは残せない問題・メモ・記録を出さない(段階的な開示、§2.13)
        assert page.get_by_role("heading", name="残せない問題がありますか").count() == 0
        assert page.get_by_role("button", name="記録して次へ", exact=True).count() == 0
        page.locator(".preference-scale button").nth(3).click()
        page.get_by_role("heading", name="残せない問題がありますか").wait_for()
        page.get_by_role("button", name="A に問題", exact=True).wait_for()
        page.get_by_role("button", name="B に問題", exact=True).wait_for()
        memo = page.get_by_role("textbox", name="メモ")
        expect(memo).to_have_attribute("maxlength", "500")
        expect(memo).to_have_attribute("rows", "3")
        dock.get_by_role("button", name="記録して次へ", exact=True).click()
        if remaining > 1:
            page.locator(".slot-switcher").wait_for()

    page.locator("#verdict-title").wait_for()
    assert page.locator("#verdict-title").text_content() in {
        "現在最良を維持しました",
        "現在最良を提案に更新しました",
    }
    # 結論は見出しと支える文1つ。Recipe と「観察として記録しました」は出さない
    assert page.locator(".verdict-detail").count() == 1
    assert page.get_by_text("Recipe", exact=False).count() == 0
    assert page.locator(".answer-row").count() == 3
    assert page.locator(".answer-row .row-gauge").count() == 3
    assert page.locator(".support-chart").count() == 1
    assert page.get_by_role("textbox").count() == 0
    page.get_by_role("button", name="受信箱へ", exact=True).click()

    page.get_by_role("button", name="結果を見る: リバーブテイルの濁り").click()
    # 候補名が長い(12字超)ので軸は「候補 1 / 2」、対応は集計の欄に一度だけ
    expect(page.locator("#verdict-title")).to_have_text(
        "候補 2 の支持が多いが、優勢には届きませんでした"
    )
    expect(page.locator(".verdict-detail")).to_have_text(
        "優勢には 3 件中 2 件が必要です。現在最良は変わりません。"
    )
    expect(page.locator(".tally-name.start")).to_have_text("← 原音")
    expect(page.locator(".tally-name.end")).to_have_text("dense-chorus-v2 →")
    expect(page.locator(".tally-role.start")).to_have_text("候補 1")
    # 問いは「問い」の欄に、比較ごとのゲージは候補の向きに固定する(左 = 組の1つ目)
    page.get_by_role("heading", name="問い", exact=True).wait_for()
    gauges = page.locator(".answer-row .row-gauge")
    orientation = gauges.evaluate_all(
        "els => els.map(el => [el.getAttribute('aria-label'), el.dataset.side])"
    )
    assert orientation[0] == ["候補 2 を明確に支持", "right"]
    expect(page.locator(".answer-row").first.locator(".row-gauge__word")).to_have_text("明確")
    # A/B の対応は既定で隠し、押すと出す(終了後だけ、§7.9)
    assert page.locator(".answer-slots").count() == 0
    page.get_by_role("button", name="A/B の割り当てを表示").click()
    expect(page.locator(".answer-slots")).to_have_count(3)
    # 同一音・再現性の確認は「回答の確かさ」に印と語で
    checks = page.get_by_role("list", name="回答の確かさ")
    expect(checks.get_by_text("差を報告（明確）", exact=True)).to_be_visible()  # noqa: RUF001
    expect(checks.get_by_text("片方が互角", exact=True)).to_be_visible()
    expect(checks.locator(".nibi-mark")).to_have_count(2)
    page.locator(".names-disclosure .nibi-disclosure__header").click()
    expect(page.locator(".candidate-names")).to_be_visible()
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
        page.get_by_role("heading", name="途中の試聴", exact=True).wait_for()
        browser.close()
