# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
"""Exercise transport ownership while browser autoplay permission is pending."""

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from scripts.dev_seed import seed
from tests.e2e.test_project_ui_v2 import live_server

DEFERRED_AUDIO_CONTEXT = """
window.audioProbe = { contexts: [], sources: [] };
class DeferredAudioContext {
  constructor() {
    this.currentTime = 0;
    this.state = 'suspended';
    this.destination = {};
    this.resumes = [];
    window.audioProbe.contexts.push(this);
  }
  createGain() {
    return {
      gain: { value: 1, cancelScheduledValues() {}, setValueAtTime() {},
        linearRampToValueAtTime() {} },
      connect() {}, disconnect() {},
    };
  }
  decodeAudioData() {
    return Promise.resolve({ duration: 6, length: 264600, sampleRate: 44100 });
  }
  createBufferSource() {
    const source = {
      started: false, stopped: false, connected: false,
      start() { this.started = true; },
      stop() { this.stopped = true; },
      connect() { this.connected = true; },
      disconnect() { this.connected = false; },
    };
    window.audioProbe.sources.push(source);
    return source;
  }
  resume() { return new Promise(resolve => this.resumes.push(resolve)); }
  release() {
    if (this.state !== 'closed') this.state = 'running';
    this.resumes.splice(0).forEach(resolve => resolve());
  }
  close() { this.state = 'closed'; return Promise.resolve(); }
}
window.AudioContext = DeferredAudioContext;
"""


@pytest.mark.browser
@pytest.mark.parametrize("action", ["keep", "leave", "replace"])
def test_pending_autoplay_owns_only_one_source_pair(
    tmp_path: Path, free_tcp_port: int, action: str
) -> None:
    workspace = tmp_path / "playback-workspace"
    seed(workspace, project_name="Playback race regression")
    with (
        live_server(workspace, workspace, free_tcp_port) as url,
        sync_playwright() as playwright,
    ):
        browser = playwright.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(DEFERRED_AUDIO_CONTEXT)
        page.goto(url)
        page.get_by_role("button", name="続きを聴く", exact=True).click()
        page.locator(".slot-switcher button:not(:disabled)").first.wait_for()
        # Autoplay has requested resume(), but the browser has not granted it yet.
        page.wait_for_function("audioProbe.contexts.some(c => c.resumes.length > 0)")
        page.locator(".slot-switcher button").nth(1).click()
        page.get_by_role("button", name="Play", exact=True).click()
        if action != "keep":
            page.get_by_role("button", name="受信箱", exact=True).click()
            page.get_by_role("heading", name="残りのセッション", exact=True).wait_for()
        if action == "replace":
            page.get_by_role("button", name="再開", exact=True).click()
            page.locator(".slot-switcher button:not(:disabled)").first.wait_for()
        page.evaluate("audioProbe.contexts.forEach(c => c.release())")
        if action != "leave":
            page.get_by_role("button", name="Pause", exact=True).wait_for()
            assert page.evaluate("audioProbe.sources.filter(s => s.started).length") == 2
            page.get_by_role("button", name="Pause", exact=True).click()
        # No delayed start may leak into a paused/unmounted deck, and Pause must stop all sound.
        assert (
            page.evaluate(
                "audioProbe.sources.filter(s => s.started && !s.stopped && s.connected).length"
            )
            == 0
        )
        assert errors == []
        browser.close()
