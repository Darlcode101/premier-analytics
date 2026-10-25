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


@pytest.fixture(autouse=True)
def _desk_help_already_seen(request, context):
    """DK-7 opens 'How this desk works' on a first visit; every test browser is a first visit, so mark it seen
    (except in the test of that behaviour)."""
    if "how_this_desk_works" not in request.node.name:
        context.add_init_script("try { localStorage.setItem('pa.deskHelp', 'closed') } catch (e) {}")


def _contrast(page: Page, selector: str) -> float:
    return page.evaluate("""sel => {
      const el = document.querySelector(sel), cs = getComputedStyle(el)
      const rgb = c => c.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4 })
      const lum = c => { const [r, g, b] = rgb(c); return .2126 * r + .7152 * g + .0722 * b }
      let bg = el; while (bg && getComputedStyle(bg).backgroundColor === 'rgba(0, 0, 0, 0)') bg = bg.parentElement
      const [a, b] = [lum(cs.color), lum(getComputedStyle(bg).backgroundColor)].sort((x, y) => y - x)
      return (a + .05) / (b + .05)
    }""", selector)


def pattern_match(base: str, speed: float = 600) -> str:
    r = httpx.post(f"{base}/api/matches", json={"home": "har", "away": "kin", "seed": 42, "speed": speed})
    r.raise_for_status()
    return r.json()["match_id"]


def new_match(base: str, speed: float = 300, seed: int = 42) -> str:
    r = httpx.post(f"{base}/api/matches", json={"home": "har", "away": "ngc", "seed": seed, "speed": speed})
    r.raise_for_status()
    return r.json()["match_id"]


KIT = {"har": "rgb(11, 61, 145)", "ngc": "rgb(127, 183, 232)"}  # primary kit colours (league.py)


# ---------- landing (R-10) ----------

def test_landing_starts_a_match_and_offers_the_desk_and_overlay(server, page: Page):
    page.goto(server)
    expect(page.locator("#home option")).to_have_count(8)
    page.get_by_role("button", name="60×").click()
    page.get_by_role("button", name="Kick off").click()
    expect(page).to_have_url(re.compile(r"\?match=\w+"))
    expect(page.get_by_test_id("desk-link")).to_have_attribute("href", re.compile(r"/desk\?match=\w+"))
    expect(page.get_by_test_id("overlay-link")).to_have_attribute("href", re.compile(r"/overlay\?match=\w+"))
    expect(page.get_by_test_id("qr").locator("svg")).to_be_visible()  # opens the desk on a tablet
    expect(page.get_by_test_id("fan-link")).to_have_count(0)  # DK-1: one product


def test_the_old_fan_address_falls_back_to_the_landing_page(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server)}")
    expect(page.get_by_test_id("desk-link")).to_have_attribute("href", re.compile(r"/desk\?match=\w+"))  # that match's desk


def test_language_choice_survives_a_reload(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server)}&lang=en")
    page.get_by_test_id("lang-select").select_option("es")
    expect(page).to_have_url(re.compile(r"lang=es"))
    page.reload()
    expect(page.get_by_role("tab", name="Previa")).to_be_visible()
    page.goto(f"{server}/desk?match={new_match(server)}&lang=en")  # a new match link from an English laptop
    expect(page.get_by_role("tab", name="Previa")).to_be_visible()


def test_desk_is_professional_and_readable(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=400)}")
    expect(page.get_by_test_id("goal-minute").first).to_be_visible(timeout=40_000)
    expect(page.get_by_test_id("celebration")).to_have_count(0)
    expect(page.get_by_test_id("fav-badge")).to_have_count(0)
    expect(page.locator("[data-possession]")).to_have_count(0)  # no possession colour wash
    assert page.evaluate("getComputedStyle(document.querySelector('[data-testid=desk]')).backgroundColor") == "rgb(27, 0, 33)"  # DK-10: PL purple
    assert _contrast(page, "[data-testid=desk]") >= 7
    page.get_by_role("tab", name="Timeline").click()
    assert _contrast(page, "[data-testid=timeline-item]") >= 4.5
    assert page.evaluate("getComputedStyle(document.querySelector('[data-testid=score]')).fontVariantNumeric").startswith("tabular")


def test_thirteen_languages_in_a_dropdown(server, page: Page):
    """DK-12: each language named in itself; the choice sets the address, the page language and direction."""
    page.goto(f"{server}/desk?match={new_match(server)}&lang=en")
    select = page.get_by_test_id("lang-select")
    expect(select.locator("option")).to_have_count(13)
    expect(select.locator("option[value=ja]")).to_have_text("日本語")
    select.select_option("ja")
    expect(page).to_have_url(re.compile(r"lang=ja"))
    expect(page.locator("html")).to_have_attribute("lang", "ja")
    expect(page.locator("html")).to_have_attribute("dir", "ltr")
    expect(page.get_by_role("tab", name="準備")).to_be_visible()
    page.goto(f"{server}/")
    expect(page.get_by_test_id("lang-select")).to_have_value("ja")  # remembered on the landing page too


@pytest.mark.parametrize("lang", ["en", "fr", "de", "ja"])
def test_desk_fits_in_long_words_and_wide_scripts(server, page: Page, lang):
    """DK-12, DK-8: French and German have the longest labels, Japanese the widest glyphs. All six tabs stay in view
    (live check 10-25: at 1280 px the last tab had scrolled out of sight, even in English)."""
    page.set_viewport_size({"width": 1280, "height": 720})
    page.goto(f"{server}/desk?match={new_match(server, speed=300)}&lang={lang}")
    expect(page.get_by_test_id("lineup-home")).to_be_visible(timeout=15_000)
    expect(page.get_by_test_id("feed-item").first).to_be_visible(timeout=20_000)
    over = page.evaluate("[document.scrollingElement.scrollHeight - innerHeight, document.scrollingElement.scrollWidth - innerWidth]")
    assert over[0] <= 1 and over[1] <= 1, over
    tabs = page.evaluate("(() => { const t = document.querySelector('[role=tablist]'); return t.scrollWidth - t.clientWidth })()")
    assert tabs <= 1, tabs


@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)])
def test_desk_fits_the_screen_without_page_scroll(server, page: Page, size):
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto(f"{server}/desk?match={new_match(server, speed=300)}")
    expect(page.get_by_test_id("lineup-home")).to_be_visible(timeout=15_000)
    expect(page.get_by_test_id("feed-item").first).to_be_visible(timeout=20_000)
    over = page.evaluate("[document.scrollingElement.scrollHeight - innerHeight, document.scrollingElement.scrollWidth - innerWidth]")
    assert over[0] <= 1 and over[1] <= 1, over


def test_desk_header_lineups_and_timeline_agree(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=600)}")
    expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    for side in ("home", "away"):
        lineup = page.get_by_test_id(f"lineup-{side}")
        expect(lineup.locator("[data-testid=starter]")).to_have_count(11)
        expect(lineup.locator("[data-testid=bench-player]")).to_have_count(7)
        expect(lineup.get_by_test_id("formation")).to_have_text("4-3-3")
        expect(lineup.get_by_test_id("subs-used")).to_have_text(re.compile(r"[0-5]/5"))
    page.get_by_role("tab", name="Timeline").click()
    items = page.get_by_test_id("timeline-item")
    goals = items.locator("xpath=self::*[@data-kind='goal']").count()
    scorer_minutes = page.locator("[data-testid^=scorers-] [data-testid=goal-minute]").count()
    assert goals == scorer_minutes
    yellows = items.locator("xpath=self::*[@data-kind='yellow']").count()
    assert page.locator("[data-testid^=lineup-] [data-testid=card-yellow]").count() == yellows
    subs = items.locator("xpath=self::*[@data-kind='sub']").count()
    assert page.locator("[data-testid^=lineup-] [data-testid=sub-off]").count() == subs
    minutes = [int(re.match(r"\d+", t).group()) for t in items.locator(".tl-minute").all_inner_texts()]
    assert minutes == sorted(minutes, reverse=True)  # newest first


def test_selecting_a_player_shows_their_match_line(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=300)}")
    first = page.get_by_test_id("lineup-home").get_by_test_id("starter").nth(5)
    expect(first).to_be_visible(timeout=15_000)
    first.click()
    line = page.get_by_test_id("player-line")
    expect(line).to_contain_text("Passes")
    expect(line).to_contain_text("Season")


def test_desk_works_with_ai_off(page: Page):
    proc, base = _serve("off")
    try:
        page.goto(f"{base}/desk?match={new_match(base, speed=600)}")
        expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
        expect(page.get_by_test_id("feed-item").first).to_be_visible()
        expect(page.locator(".ai-tag")).to_have_count(0)
        page.get_by_role("tab", name="Timeline").click()
        expect(page.locator("[data-testid=timeline-item][data-kind=sub]").first).to_be_visible()
        page.get_by_role("tab", name="Prep").click()  # DK-5: the season sits in Prep
        expect(page.get_by_test_id("season-home")).to_contain_text(re.compile(r"[WDL]"))
    finally:
        _stop(proc)


def test_used_talking_points_survive_a_reload(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=120)}")
    point = page.get_by_test_id("feed-item").first
    expect(point).to_be_visible(timeout=20_000)
    pid = point.get_attribute("data-id")
    point.get_by_role("button", name="Mark as used").click()
    expect(page.locator(f"[data-testid=feed-item][data-id='{pid}']")).to_have_attribute("data-used", "true")
    page.reload()
    expect(page.locator(f"[data-testid=feed-item][data-id='{pid}']")).to_have_attribute("data-used", "true", timeout=20_000)


def test_desk_in_arabic_is_right_to_left(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server)}&lang=ar")
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    expect(page.get_by_test_id("score")).to_have_text(re.compile(r"^[٠-٩]+ – [٠-٩]+$"), timeout=15_000)
    expect(page.get_by_role("tab", name="الإحصائيات")).to_be_visible()


def test_model_outage_keeps_graphics_flowing(page: Page):
    proc, base = _serve("down")
    try:
        page.goto(f"{base}/desk?match={new_match(base)}")
        expect(page.get_by_test_id("feed-item").first).to_be_visible(timeout=20_000)
        page.get_by_role("tab", name="Production").click()
        expect(page.get_by_test_id("on-air")).to_be_visible()
        expect(page.get_by_test_id("agents")).to_contain_text("error", timeout=20_000)
        expect(page.locator(".ai-tag")).to_have_count(0)
    finally:
        _stop(proc)


def test_attack_momentum_bars_explain_themselves(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=300)}")
    page.wait_for_timeout(5000)  # let a few minutes of bars build up
    page.get_by_role("tab", name="Stats").click()
    chart = page.get_by_test_id("attack-momentum")  # DK-5: momentum lives in Stats
    expect(chart).to_be_visible()
    assert page.get_by_test_id("attack-bar").count() >= 5
    page.get_by_test_id("attack-bar").nth(2).dispatch_event("click")
    why = page.get_by_test_id("attack-why")
    expect(why).to_contain_text(re.compile(r"on top|Evenly balanced|Quiet spell"))
    expect(why).to_contain_text(re.compile(r"\d+'–\d+'"))


def test_a_picked_momentum_bar_returns_to_live(server, page: Page):
    """DK-13 (user report 10-25: a clicked bar stayed stuck)."""
    page.goto(f"{server}/desk?match={new_match(server, speed=300)}")
    page.wait_for_timeout(5000)
    page.get_by_role("tab", name="Stats").click()
    why, live, bar = page.get_by_test_id("attack-why"), page.get_by_test_id("attack-live"), page.get_by_test_id("attack-bar").nth(2)

    def pick():
        bar.dispatch_event("click")
        expect(live).to_be_visible()
        expect(why.locator(".hint")).to_have_count(0)

    def is_live():
        expect(live).to_have_count(0)
        expect(why.locator(".hint")).to_be_visible()

    pick()
    why.locator(".attack-why-head b").click()  # reading the explanation keeps the pick
    expect(live).to_be_visible()
    page.locator(".cd-details").click()  # a click off the chart
    is_live()
    pick()
    page.keyboard.press("Escape")
    is_live()
    pick()
    live.click()
    is_live()
    pick()
    bar.dispatch_event("click")  # the same bar again
    is_live()


def test_desk_shows_sourced_context_beside_moments(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=300)}")
    card = page.get_by_test_id("context-card").first
    expect(card).to_be_visible(timeout=40_000)
    expect(card).to_contain_text("real Premier League")
    link = card.locator("a").first
    assert link.get_attribute("href").startswith("https://")
    assert link.get_attribute("target") == "_blank" and "noopener" in link.get_attribute("rel")


def test_ask_box_answers_with_a_source(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=60)}")
    page.get_by_role("tab", name="Ask").click()
    page.get_by_test_id("ask-input").fill("What is the average xG per team in the Premier League?")
    page.get_by_role("button", name="Ask").click()
    answer = page.get_by_test_id("ask-answer").first
    expect(answer).to_contain_text("web search", timeout=15_000)
    expect(answer).to_contain_text("From the web, not checked against match data")
    assert answer.locator("a").first.get_attribute("href").startswith("https://")
    expect(page.get_by_test_id("ask-remaining")).to_contain_text("14")


def test_stat_labels_open_their_explainer(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=60)}")
    page.get_by_role("button", name=re.compile("^xG")).first.click(timeout=15_000)
    expect(page.get_by_test_id("explainer")).to_contain_text("Expected")


def test_search_outage_is_reported_and_nothing_else_breaks(page: Page):
    proc, base = _serve("down")
    try:
        page.goto(f"{base}/desk?match={new_match(base, speed=300)}")
        expect(page.get_by_test_id("feed-item").first).to_be_visible(timeout=20_000)
        page.get_by_role("tab", name="Ask").click()
        page.get_by_test_id("ask-input").fill("Average xG?")
        page.get_by_role("button", name="Ask").click()
        expect(page.get_by_test_id("ask-answer").first).to_contain_text("couldn't", timeout=15_000)
        expect(page.get_by_test_id("context-card")).to_have_count(0)
    finally:
        _stop(proc)


# ---------- fan app polish (F-*) ----------

def test_desk_patterns_panel_shows_notes_and_their_pitch(server, page: Page):
    page.goto(f"{server}/desk?match={pattern_match(server)}")
    expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    page.get_by_role("tab", name="Patterns").click()
    notes = page.get_by_test_id("pattern-note")
    expect(notes.first).to_be_visible(timeout=10_000)
    expect(page.locator("[data-testid=pattern-note][data-scope=match]").first).to_contain_text("down the left")
    expect(page.locator("[data-testid=pattern-note][data-scope=season]").first).to_contain_text("this season")
    page.locator("[data-testid=pattern-note][data-kind=flank]").first.click()
    pitch = page.get_by_test_id("pattern-pitch")
    expect(pitch).to_have_attribute("data-kind", "flank")
    expect(pitch.locator("[data-testid=channel-share]")).to_have_count(3)


def test_pattern_alerts_appear_among_talking_points(server, page: Page):
    page.goto(f"{server}/desk?match={pattern_match(server)}")
    alert = page.get_by_test_id("pattern-alert").first
    expect(alert).to_be_visible(timeout=60_000)
    expect(alert).to_contain_text("Hyperion keep going down the left")


def test_desk_opened_after_full_time_still_has_recaps_and_agent_activity(server, browser):
    mid = new_match(server, speed=600)
    watcher = browser.new_page()
    watcher.goto(f"{server}/desk?match={mid}")
    expect(watcher.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    watcher.wait_for_timeout(1500)  # let the full-time recap finish
    late = browser.new_page()
    late.goto(f"{server}/desk?match={mid}")
    expect(late.get_by_test_id("clock")).to_have_text("FT", timeout=15_000)
    late.get_by_role("tab", name="Production").click()  # DK-5: recaps and agent activity together
    expect(late.get_by_test_id("recaps")).to_contain_text("recap", ignore_case=True)
    expect(late.get_by_test_id("agents").locator(".trace-item").first).to_be_visible()
    watcher.close()
    late.close()


def test_overlay_page_is_transparent_with_a_scorebug(server, page: Page):
    page.goto(f"{server}/overlay?match={new_match(server, speed=60)}")
    bug = page.get_by_test_id("scorebug")
    expect(bug).to_be_visible(timeout=15_000)
    expect(bug).to_contain_text(re.compile(r"HAR\s*0\s*–\s*0\s*NGC"))
    expect(bug.get_by_test_id("clock")).to_have_text(re.compile(r"^\d{2}:\d{2}"))
    backgrounds = page.evaluate("[getComputedStyle(document.documentElement).backgroundColor, getComputedStyle(document.body).backgroundColor]")
    assert backgrounds == ["rgba(0, 0, 0, 0)", "rgba(0, 0, 0, 0)"], backgrounds


def test_overlay_lower_third_pops_up_with_the_current_graphic(server, page: Page):
    page.goto(f"{server}/overlay?match={new_match(server, speed=120)}&bug=0")
    expect(page.get_by_test_id("scorebug")).to_have_count(0)
    third = page.get_by_test_id("lower-third")
    expect(third).to_have_attribute("data-state", "in", timeout=30_000)
    expect(third.locator("strong")).not_to_be_empty()
    fits = page.evaluate("""[...document.querySelectorAll('[data-testid=lower-third] strong, [data-testid=lower-third-body]')]
      .map(el => el.scrollHeight <= el.clientHeight + 1)""")
    assert fits == [True, True]  # capped to what the box holds: nothing clipped
    expect(third).to_have_attribute("data-state", "out", timeout=30_000)  # slides away again


def test_overlay_is_linked_from_the_desk(server, page: Page):
    mid = new_match(server, speed=60)
    page.goto(f"{server}/desk?match={mid}")
    page.get_by_role("tab", name="Production").click()
    expect(page.get_by_role("link", name=re.compile("overlay", re.I))).to_have_attribute("href", re.compile(rf"/overlay\?match={mid}"))


# ---------- corners and penalties (D-10) ----------

def test_desk_shows_corners_and_penalties(server, page: Page):
    r = httpx.post(f"{server}/api/matches", json={"home": "har", "away": "kin", "seed": 7, "speed": 600})
    page.goto(f"{server}/desk?match={r.json()['match_id']}")
    expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    stats = page.get_by_test_id("desk-stats")
    expect(stats).to_contain_text("Corners")
    page.get_by_role("tab", name="Timeline").click()
    expect(page.locator("[data-testid=timeline-item][data-kind=penalty]").first).to_contain_text("Penalty awarded")


def test_stats_can_be_split_by_half(server, page: Page):
    mid = new_match(server, speed=600)
    page.goto(f"{server}/desk?match={mid}")
    expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    table = page.get_by_test_id("desk-stats")
    shots = lambda: table.locator("tr", has_text="Shots").first.locator("td").first.inner_text()  # noqa: E731
    total = int(shots())
    page.get_by_role("button", name="1st half").click()
    expect(table).to_have_attribute("data-period", "first_half")
    first = int(shots())
    page.get_by_role("button", name="2nd half").click()
    second = int(shots())
    assert first + second == total and first <= total


def test_desk_pops_up_a_substitution_card_that_can_be_reopened(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=600)}")
    card = page.get_by_test_id("sub-card")
    expect(card).to_be_visible(timeout=60_000)
    expect(card).to_contain_text("Going off")
    expect(card).to_contain_text("Coming on")
    expect(card.get_by_test_id("sub-change-type").first).to_have_text(re.compile("Like-for-like|More attacking|More defensive"))
    expect(card).to_contain_text(re.compile(r"Subs used \d/5"))
    expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    page.get_by_test_id("sub-card-close").click()
    expect(card).to_have_count(0)
    page.get_by_role("tab", name="Timeline").click()
    page.get_by_test_id("open-sub-card").last.click()  # the earliest change
    expect(card).to_be_visible()


def test_desk_producer_cues_what_to_say_and_used_moves_it_on(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=120, seed=292)}")
    card = page.get_by_test_id("cue-card")
    expect(card).to_have_attribute("data-state", "on_air", timeout=30_000)  # a break comes within minutes
    expect(card.get_by_test_id("cue-source")).to_contain_text("→ Producer")
    expect(card.get_by_test_id("cue-note")).to_contain_text("Producer", timeout=10_000)  # GP-5: the AI producer adds a line
    expect(card).to_contain_text(re.compile(r"Goal|Penalty|Free kick|Card|Substitution|Goal kick|Half-time"))
    ref = card.get_attribute("data-ref")
    card.get_by_test_id("cue-used").click()
    expect(card).not_to_have_attribute("data-ref", ref, timeout=10_000)  # the producer moves on
    page.reload()  # used is shared server state, so it survives a reload
    expect(page.get_by_test_id("cue-card")).not_to_have_attribute("data-ref", ref, timeout=20_000)


# ---------- Ask about this match (AM-*) ----------

def test_ask_box_answers_match_questions_from_the_match_data(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=60)}")
    expect(page.get_by_test_id("clock")).not_to_have_text(re.compile("^0'?$"), timeout=20_000)
    page.get_by_role("tab", name="Ask").click()
    page.get_by_test_id("ask-input").fill("Who is winning?")
    page.get_by_role("button", name="Ask").click()
    answer = page.get_by_test_id("match-answer").first
    expect(answer).to_have_attribute("data-status", "ok", timeout=15_000)
    expect(answer).to_contain_text(re.compile(r"Hyperion \d+-\d+ Selene"))
    expect(answer).to_contain_text("From the match data, checked · as of")
    answer.get_by_test_id("how-i-know").click()
    expect(answer.locator(".cd-evidence")).to_contain_text("get_score()")


# ---------- prep and storylines (PS-*) ----------

def test_desk_preps_storylines_then_kicks_off_and_follows_them(server, page: Page):
    r = httpx.post(f"{server}/api/matches", json={"home": "har", "away": "ngc", "seed": 292, "speed": 300, "autostart": False})
    page.goto(f"{server}/desk?match={r.json()['match_id']}")
    expect(page.get_by_test_id("prep")).to_be_visible(timeout=10_000)  # before kick-off, prep comes first
    expect(page.get_by_test_id("brief-home")).to_contain_text("Players to watch")
    page.get_by_test_id("storyline-suggestion").first.get_by_role("button").click()
    page.get_by_test_id("storyline-input").fill("Can Zane Kowalczyk make a difference off the bench?")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_test_id("storyline")).to_have_count(2)
    page.get_by_test_id("storyline-input").fill("Will it rain?")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_test_id("storyline-error")).to_contain_text("player or club")
    page.get_by_test_id("kick-off").click()
    expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    page.get_by_role("tab", name="Prep").click()
    story = page.get_by_test_id("storyline").filter(has_text="Kowalczyk")
    expect(story.get_by_test_id("storyline-update").first).to_be_visible()


def test_landing_can_hold_kick_off_for_the_desk(server, page: Page):
    page.goto(server)
    page.get_by_test_id("hold-for-desk").check()
    page.get_by_role("button", name="Kick off").click()
    page.get_by_test_id("desk-link").click()
    expect(page.get_by_test_id("kick-off")).to_be_visible(timeout=10_000)  # waiting for the commentator
    expect(page.get_by_test_id("clock")).not_to_contain_text("1'")
    page.get_by_test_id("kick-off").click()
    expect(page.get_by_test_id("kick-off")).to_have_count(0, timeout=10_000)


# ---------- live fact-check (FC-*) ----------

def test_desk_fact_checks_a_typed_line_and_flags_the_right_number(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=600, seed=292)}")
    expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    panel = page.get_by_test_id("fact-check")
    panel.get_by_test_id("say-input").fill("Kowalczyk has 3 shots since he came on")
    panel.get_by_role("button", name="Check").click()
    flag = panel.get_by_test_id("fact-flag").first
    expect(flag).to_contain_text("Zane Kowalczyk: 1 shot, not 3", timeout=10_000)
    expect(flag).to_contain_text("get_player_stats")
    expect(panel.get_by_test_id("fact-count")).to_contain_text("1 checked · 1 flagged")
    panel.get_by_test_id("say-input").fill("Kowalczyk has 1 shot")  # correct: confirmed, no new flag
    panel.get_by_role("button", name="Check").click()
    expect(panel.get_by_test_id("fact-count")).to_contain_text("2 checked · 1 flagged", timeout=10_000)
    log = panel.get_by_test_id("fact-log")  # 10-25: every line gets a visible answer
    expect(log.get_by_test_id("fact-correct").first).to_contain_text("Zane Kowalczyk: 1 shot")
    panel.get_by_test_id("say-input").fill("What an atmosphere")
    panel.get_by_role("button", name="Check").click()
    expect(log.locator("li").first).to_contain_text("no stat to check", timeout=10_000)


# ---------- one product: the desk (DK-*) ----------

def test_desk_header_clock_ticks_and_shows_possession(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=60)}")
    clock = page.get_by_test_id("clock")
    expect(clock).to_have_text(re.compile(r"^\d+:\d\d"), timeout=15_000)  # DK-3: minutes and seconds
    first = clock.inner_text()
    page.wait_for_timeout(1500)
    assert clock.inner_text() != first  # it ticks between events
    expect(page.get_by_test_id("possession-ball")).to_have_count(1)  # beside the team on the ball


def test_say_it_simply_gives_plain_lines(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=600, seed=292)}")
    expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    point = page.get_by_test_id("feed-item").filter(has_text="GOAL").first
    point.get_by_test_id("say-simply").click()
    lines = point.get_by_test_id("simple-lines")
    expect(lines).to_contain_text(re.compile(r"puts .+ ahead|levels the game|bigger cushion|back in the game|penalty spot|chances like this"))
    assert not re.search(r"xG", lines.inner_text())


def test_focus_player_highlights_what_they_do(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=600, seed=292)}")
    expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    page.get_by_test_id("lineup-home").get_by_test_id("starter").filter(has_text="Northcott").click()
    page.get_by_test_id("focus-player").click()
    expect(page.get_by_test_id("focus-chip")).to_contain_text("Reuben Northcott")
    expect(page.locator("[data-testid=feed-item][data-focus=true]").first).to_be_visible()  # his goal
    page.get_by_role("tab", name="Timeline").click()
    expect(page.locator("[data-testid=timeline-item][data-focus=true]").first).to_be_visible()
    page.get_by_test_id("focus-chip").get_by_role("button").click()
    expect(page.get_by_test_id("focus-chip")).to_have_count(0)
    expect(page.locator("[data-focus=true]")).to_have_count(0)


def test_desk_has_six_tabs_and_a_clear_main_column(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server)}")
    tabs = page.get_by_role("tab")
    expect(tabs).to_have_count(6)
    assert [t.inner_text().strip().lower() for t in tabs.all()] == ["prep", "stats", "patterns", "timeline", "ask", "production"]
    tops = [page.get_by_test_id(t).bounding_box()["y"] for t in ("block-cue", "block-factcheck", "block-points")]
    assert tops == sorted(tops)  # DK-6: cue, then fact-check, then talking points


def test_how_this_desk_works_opens_once_and_stays_closed(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server)}")
    help_ = page.get_by_test_id("desk-help")
    expect(help_).to_have_attribute("data-open", "true")  # first visit
    expect(help_).to_contain_text("Producer cue")
    page.get_by_test_id("help-close").click()
    expect(help_).to_have_attribute("data-open", "false")
    page.reload()
    expect(page.get_by_test_id("desk-help")).to_have_attribute("data-open", "false")
