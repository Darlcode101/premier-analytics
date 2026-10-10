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


KIT = {"har": "rgb(11, 61, 145)", "ngc": "rgb(127, 183, 232)"}  # primary kit colours (league.py)


# ---------- landing (R-10) ----------

def test_landing_starts_a_match_and_offers_both_surfaces(server, page: Page):
    page.goto(server)
    expect(page.locator("#home option")).to_have_count(8)
    page.get_by_role("button", name="60×").click()
    page.get_by_role("button", name="Kick off").click()
    expect(page).to_have_url(re.compile(r"\?match=\w+"))
    expect(page.get_by_test_id("fan-link")).to_have_attribute("href", re.compile(r"/fan\?match=\w+"))
    expect(page.get_by_test_id("desk-link")).to_have_attribute("href", re.compile(r"/desk\?match=\w+"))
    expect(page.get_by_test_id("qr").locator("svg")).to_be_visible()


# ---------- fan app (R-2, R-7, R-8) ----------

def test_fan_screen_washes_to_the_team_in_possession(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=120)}")
    hero = page.get_by_test_id("hero")
    expect(hero).to_have_attribute("data-possession", re.compile(r"^(har|ngc)$"), timeout=15_000)
    first = hero.get_attribute("data-possession")
    wash = page.evaluate("getComputedStyle(document.querySelector('[data-testid=hero]')).getPropertyValue('--wash')").strip()
    assert page.evaluate(f"(() => {{ const d = document.createElement('i'); d.style.color = '{wash}'; document.body.append(d); "
                         f"const c = getComputedStyle(d).color; d.remove(); return c }})()") == KIT[first]
    other = "ngc" if first == "har" else "har"
    expect(hero).to_have_attribute("data-possession", other, timeout=15_000)  # a turnover changes the colour


def test_fan_zone_card_names_where_the_ball_is(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server)}")
    expect(page.get_by_test_id("zone-text")).to_have_text(
        re.compile(r"(Harbourside|Northgate) · (defensive third|midfield|final third) · (left|centre|right)"), timeout=15_000)


def test_goal_takes_over_the_screen_in_the_scorers_colours(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=400)}")
    goal = page.locator("[data-testid=celebration][data-kind=goal]")
    expect(goal).to_be_visible(timeout=40_000)
    expect(goal).to_contain_text("GOAL!")
    expect(goal.get_by_test_id("celebration-scorer")).to_have_text(re.compile(r"\w+ \w+ · [\d+]+'"))


def test_fan_settings_switch_language_to_arabic(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server)}")
    page.get_by_role("button", name="Me").click()
    expect(page.get_by_test_id("me")).to_contain_text("Fictional league")
    page.get_by_role("button", name="العربية").click()
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    expect(page.get_by_role("button", name="أنا")).to_be_visible()


def test_fan_moment_cards_explain_why(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server)}")
    item = page.get_by_test_id("feed-item").first
    expect(item).to_be_visible(timeout=20_000)
    item.get_by_role("button", name="Why?").click()
    evidence = page.locator("[data-testid='feed-item'] dl.evidence")  # new cards may push it down the list
    expect(evidence).to_have_count(1)


def test_fan_app_fits_a_phone(server, page: Page):
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{server}/fan?match={new_match(server)}")
    expect(page.get_by_test_id("fan-app")).to_be_visible()
    page.wait_for_timeout(1500)
    assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 0


# ---------- commentator desk (R-9) ----------

def test_desk_shows_talking_points_on_air_and_agents(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server)}")
    expect(page.get_by_test_id("feed-item").first).to_be_visible(timeout=20_000)
    expect(page.get_by_test_id("on-air")).to_be_visible()
    expect(page.get_by_test_id("zone-map")).to_be_visible()
    page.get_by_role("tab", name=re.compile("Agents")).click()
    expect(page.get_by_test_id("agents")).to_contain_text("explainer", timeout=20_000)
    page.get_by_role("button", name="Español").click()
    expect(page.get_by_role("heading", name="Claves para comentar")).to_be_visible()


def test_fan_and_desk_on_the_same_match_differ(server, browser):
    mid = new_match(server, speed=200)
    fan, desk = browser.new_page(), browser.new_page()
    fan.goto(f"{server}/fan?match={mid}")
    desk.goto(f"{server}/desk?match={mid}")
    expect(desk.get_by_test_id("feed-item").nth(3)).to_be_visible(timeout=30_000)
    fan_n, desk_n = fan.get_by_test_id("feed-item").count(), desk.get_by_test_id("feed-item").count()
    assert desk_n > fan_n, (desk_n, fan_n)  # commentators see more moments than fans
    fan.close()
    desk.close()


def test_model_outage_keeps_graphics_flowing(page: Page):
    proc, base = _serve("down")
    try:
        page.goto(f"{base}/desk?match={new_match(base)}")
        expect(page.get_by_test_id("feed-item").first).to_be_visible(timeout=20_000)
        page.get_by_role("tab", name=re.compile("Agents")).click()
        expect(page.get_by_test_id("agents")).to_contain_text("error", timeout=20_000)
        expect(page.locator(".ai-tag")).to_have_count(0)
    finally:
        _stop(proc)
