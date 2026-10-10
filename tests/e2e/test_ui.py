"""End-to-end: the built app in a real browser (TEST_PLAN §7).

Runs the production server (FastAPI serving web/dist) with scripted offline models, so
results are deterministic and free. Build the frontend first: `npm --prefix web run build`.
"""
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not (ROOT / "web" / "dist" / "index.html").exists(), reason="frontend not built"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(mode: str):
    port = _free_port()
    env = {**os.environ, "PA_AI": mode, "PA_MAX_SESSIONS": "50", "PYTHONPATH": str(ROOT / "src")}
    log = os.environ.get("E2E_SERVER_LOG")  # set to a path to capture server output when debugging
    out = open(f"{log}.{mode}.{port}", "w") if log else subprocess.DEVNULL
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "premier_analytics.server:app", "--port", str(port),
         "--timeout-graceful-shutdown", "2"],
        env=env, cwd=ROOT, stdout=out, stderr=out,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/api/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("server did not start")
    return proc, base


def _stop(proc) -> None:
    proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def server():
    proc, base = _serve("fake")
    yield base
    _stop(proc)


def new_match(base: str, speed: float = 300, seed: int = 42) -> str:
    r = httpx.post(f"{base}/api/matches", json={"home": "har", "away": "ngc", "seed": seed, "speed": speed})
    r.raise_for_status()
    return r.json()["match_id"]


def test_setup_flow_kicks_off_a_match(server, page: Page):
    page.goto(server)
    expect(page.get_by_role("heading", name="Premier Analytics")).to_be_visible()
    expect(page.locator("#home option")).to_have_count(8)
    page.get_by_role("button", name="60×").click()
    page.get_by_role("button", name="Kick off").click()
    expect(page).to_have_url(re.compile(r"\?match=\w+"))
    expect(page.get_by_test_id("score")).to_have_text(re.compile(r"\d+ – \d+"))
    expect(page.get_by_test_id("pitch")).to_be_visible()


def test_overlays_appear_and_upgrade_in_place(server, page: Page):
    page.goto(f"{server}/?match={new_match(server)}")
    first = page.locator("[data-testid^='overlay-']").first
    expect(first).to_be_visible(timeout=20_000)
    expect(page.get_by_text("✦ AI explained").first).to_be_visible(timeout=20_000)


def test_why_reveals_the_evidence(server, page: Page):
    page.goto(f"{server}/?match={new_match(server)}")
    item = page.get_by_test_id("feed-item").first
    expect(item).to_be_visible(timeout=20_000)
    item.get_by_role("button", name="Why?").click()
    # New moments are prepended, so the expanded item may no longer be first: find it wherever it is.
    evidence = page.locator("[data-testid='feed-item'] dl.evidence")
    expect(evidence).to_have_count(1)
    expect(evidence.locator("dt").first).not_to_be_empty()


def test_arabic_switches_layout_to_rtl(server, page: Page):
    page.goto(f"{server}/?match={new_match(server)}")
    expect(page.get_by_test_id("pitch")).to_be_visible()
    page.get_by_role("button", name="العربية").click()
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    expect(page.get_by_role("tab", name=re.compile("اللقطات"))).to_be_visible()
    expect(page.locator("[data-testid='feed-item'][dir='rtl']").first).to_be_visible(timeout=20_000)


def test_analyst_mode_shows_the_numbers(server, page: Page):
    page.goto(f"{server}/?match={new_match(server)}")
    page.get_by_role("button", name="Analyst").click()
    expect(page.get_by_test_id("feed-item").first).to_be_visible(timeout=20_000)
    page.get_by_role("tab", name="Stats").click()
    expect(page.get_by_test_id("stats")).to_contain_text("Possession")


def test_two_viewers_see_different_experiences(server, browser):
    mid = new_match(server, speed=200)
    fan = browser.new_page()
    analyst = browser.new_page()
    fan.goto(f"{server}/?match={mid}")
    analyst.goto(f"{server}/?match={mid}")
    analyst.get_by_role("button", name="Analyst").click()
    analyst.get_by_role("button", name="Español").click()
    expect(analyst.get_by_role("tab", name="Jugadas")).to_be_visible()
    expect(fan.get_by_role("tab", name="Feed")).to_be_visible()
    expect(analyst.get_by_test_id("feed-item").first).to_be_visible(timeout=20_000)
    expect(fan.get_by_test_id("feed-item").first).to_be_visible(timeout=20_000)
    fan.close()
    analyst.close()


def test_phone_width_has_no_horizontal_scroll(server, page: Page):
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{server}/?match={new_match(server)}")
    expect(page.get_by_test_id("pitch")).to_be_visible()
    page.wait_for_timeout(1500)
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 0, f"page is {overflow}px wider than the screen"


def test_model_outage_keeps_graphics_flowing(page: Page):
    proc, base = _serve("down")
    try:
        page.goto(f"{base}/?match={new_match(base)}")
        expect(page.locator("[data-testid^='overlay-']").first).to_be_visible(timeout=20_000)
        page.get_by_role("tab", name=re.compile("Agents")).click()
        expect(page.get_by_test_id("agents")).to_contain_text("error", timeout=20_000)
        expect(page.get_by_text("✦ AI explained")).to_have_count(0)
    finally:
        _stop(proc)
