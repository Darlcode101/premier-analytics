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

def test_possession_is_shown_low_key_with_a_ball_marker(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=120)}")
    hero = page.get_by_test_id("hero")
    expect(hero).to_have_attribute("data-possession", re.compile(r"^(har|ngc)$"), timeout=15_000)
    background = page.evaluate("getComputedStyle(document.querySelector('[data-testid=hero]')).backgroundImage")
    first = hero.get_attribute("data-possession")
    ball = page.get_by_test_id("possession-ball")
    expect(ball).to_have_count(1)
    side = "hero-left" if page.get_by_test_id("hero-left").get_by_test_id("possession-ball").count() else "hero-right"
    expect(page.get_by_test_id(side)).to_contain_text("Harbourside" if first == "har" else "Northgate", ignore_case=True)
    dot = page.evaluate("getComputedStyle(document.querySelector('.possession-line .dot')).backgroundColor")
    assert dot == KIT[first]
    other = "ngc" if first == "har" else "har"
    expect(hero).to_have_attribute("data-possession", other, timeout=15_000)  # a turnover moves the marker...
    expect(ball).to_have_count(1)
    assert page.evaluate("getComputedStyle(document.querySelector('[data-testid=hero]')).backgroundImage") == background  # ...not the colours


def test_fan_pitch_is_bare_and_centred_with_the_zone_as_its_label(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server)}")
    pitch = page.get_by_test_id("mini-pitch")
    expect(pitch).to_have_attribute(
        "aria-label", re.compile(r"(Harbourside|Northgate) · (defensive third|midfield|final third) · (left|centre|right)"),
        timeout=15_000)
    card = page.get_by_test_id("zone-map")
    expect(card.locator(".zone-head")).to_have_count(0)
    expect(card.get_by_test_id("zone-text")).to_have_count(0)
    expect(card.locator(".attack-chevron")).to_have_count(0)
    expect(card.get_by_test_id("ball")).to_be_visible()          # a football marks where the ball is…
    expect(card.get_by_test_id("pitch-hue")).to_have_count(0)    # …instead of a coloured glow
    p, c = pitch.bounding_box(), card.bounding_box()
    assert abs((p["x"] + p["width"] / 2) - (c["x"] + c["width"] / 2)) < 2  # centred


def test_goal_takes_over_the_screen_in_the_scorers_colours(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=400)}")
    goal = page.locator("[data-testid=celebration][data-kind=goal]")
    expect(goal).to_be_visible(timeout=40_000)
    expect(goal).to_contain_text("GOAL!")
    # names can be hyphenated or have apostrophes (Pablo Wakefield-Ames)
    expect(goal.get_by_test_id("celebration-scorer")).to_have_text(re.compile(r"[\w'-]+ [\w'-]+ · [\d+]+'"))


def test_fan_settings_switch_language_to_arabic(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server)}")
    page.get_by_role("button", name="Me").click()
    expect(page.get_by_test_id("me")).to_contain_text("Fictional league")
    page.get_by_role("button", name="العربية").click()
    expect(page.locator("html")).to_have_attribute("dir", "rtl")
    expect(page.get_by_role("button", name="أنا")).to_be_visible()
    expect(page.get_by_test_id("score")).to_have_text(re.compile(r"^[٠-٩]+–[٠-٩]+$"))  # Eastern Arabic digits
    expect(page.get_by_test_id("clock")).not_to_contain_text(re.compile(r"[0-9]"))


def test_language_choice_survives_a_reload(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server)}&lang=en")
    page.get_by_role("button", name="Me").click()
    page.get_by_role("button", name="Español").click()
    expect(page).to_have_url(re.compile(r"lang=es"))
    page.reload()
    expect(page.get_by_role("button", name="Yo")).to_be_visible()
    page.goto(f"{server}/fan?match={new_match(server)}&lang=en")  # a new match link from an English laptop
    expect(page.get_by_role("button", name="Yo")).to_be_visible()


def test_fan_moment_cards_explain_why(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server)}")
    item = page.get_by_test_id("feed-item").first
    expect(item).to_be_visible(timeout=20_000)
    item.get_by_role("button", name="Why?").click()
    why = page.get_by_test_id("why")  # new cards may push it down the list
    expect(why).to_have_count(1)
    expect(why.locator(".why-lines li").first).to_be_visible()  # F-7: plain sentences first
    assert not re.search(r"xG|%", why.locator(".why-lines").inner_text())
    expect(why.locator("dl.evidence")).to_have_count(0)
    why.get_by_role("button", name="See the numbers").click()  # F-8: the raw facts are one tap away
    expect(why.locator("dl.evidence")).to_have_count(1)


def test_fan_app_fits_a_phone(server, page: Page):
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{server}/fan?match={new_match(server)}")
    expect(page.get_by_test_id("fan-app")).to_be_visible()
    page.wait_for_timeout(1500)
    assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 0


# ---------- commentator desk (CD-*) ----------

def _contrast(page: Page, selector: str) -> float:
    return page.evaluate("""sel => {
      const el = document.querySelector(sel), cs = getComputedStyle(el)
      const rgb = c => c.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4 })
      const lum = c => { const [r, g, b] = rgb(c); return .2126 * r + .7152 * g + .0722 * b }
      let bg = el; while (bg && getComputedStyle(bg).backgroundColor === 'rgba(0, 0, 0, 0)') bg = bg.parentElement
      const [a, b] = [lum(cs.color), lum(getComputedStyle(bg).backgroundColor)].sort((x, y) => y - x)
      return (a + .05) / (b + .05)
    }""", selector)


def test_desk_is_neutral_and_professional(server, page: Page):
    page.goto(f"{server}/desk?match={new_match(server, speed=400)}")
    expect(page.get_by_test_id("goal-minute").first).to_be_visible(timeout=40_000)
    expect(page.get_by_test_id("celebration")).to_have_count(0)
    expect(page.get_by_test_id("fav-badge")).to_have_count(0)
    expect(page.locator("[data-possession]")).to_have_count(0)  # no possession colour wash
    assert page.evaluate("getComputedStyle(document.querySelector('[data-testid=desk]')).backgroundColor") == "rgb(21, 24, 29)"
    assert _contrast(page, "[data-testid=desk]") >= 7
    page.get_by_role("tab", name="Timeline").click()
    assert _contrast(page, "[data-testid=timeline-item]") >= 4.5
    assert page.evaluate("getComputedStyle(document.querySelector('[data-testid=score]')).fontVariantNumeric").startswith("tabular")


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
        page.get_by_role("tab", name="Season").click()
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
        page.get_by_role("tab", name="Production").click()
        expect(page.get_by_test_id("on-air")).to_be_visible()
        expect(page.get_by_test_id("agents")).to_contain_text("error", timeout=20_000)
        expect(page.locator(".ai-tag")).to_have_count(0)
    finally:
        _stop(proc)


def test_favourite_club_is_pinned_left_with_a_badge(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=60)}")
    left = page.get_by_test_id("hero-left")
    expect(left).to_contain_text("Harbourside")          # home-left by default
    expect(page.get_by_test_id("fav-badge")).to_have_count(0)
    page.get_by_role("button", name="Me").click()
    page.get_by_role("button", name="Northgate").click()  # away side
    expect(left).to_contain_text("Northgate")
    badge = page.get_by_test_id("fav-badge")
    expect(badge).to_be_visible()
    expect(badge).to_have_attribute("aria-label", "Your club")   # low-key star, but still announced
    box = badge.bounding_box()
    assert box and box["width"] <= 16 and box["height"] <= 16, box   # an icon, not a text pill
    expect(page.get_by_test_id("hero-right")).to_contain_text("Harbourside")


def test_favourite_flips_the_pitch_and_is_remembered(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=20)}")
    pitch = page.get_by_test_id("mini-pitch")
    expect(pitch).to_have_attribute("data-mirrored", "false")         # TV view: home attacks right
    page.get_by_role("button", name="Me").click()
    page.get_by_role("button", name="Northgate").click()             # away side attacks left in the first half
    page.get_by_role("button", name="Live").click()
    expect(pitch).to_have_attribute("data-mirrored", "true")          # so the pitch flips for them
    page.reload()
    expect(page.get_by_test_id("fav-badge")).to_be_visible()          # remembered after a refresh
    expect(page.get_by_test_id("hero-left")).to_contain_text("Northgate")
    expect(page.get_by_test_id("mini-pitch")).to_have_attribute("data-mirrored", "true")


def test_attack_momentum_bars_explain_themselves(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=300)}")
    expect(page.get_by_test_id("mini-pitch")).not_to_have_attribute("aria-label", "Ball out of play", timeout=15_000)
    page.wait_for_timeout(4000)  # let a few minutes of bars build up
    page.get_by_role("button", name="Stats").click()
    chart = page.get_by_test_id("attack-momentum")
    expect(chart).to_be_visible()
    assert page.get_by_test_id("attack-bar").count() >= 5
    page.get_by_test_id("attack-bar").nth(2).dispatch_event("click")
    why = page.get_by_test_id("attack-why")
    expect(why).to_contain_text(re.compile(r"on top|Evenly balanced|Quiet spell"))
    expect(why).to_contain_text(re.compile(r"\d+'–\d+'"))


def test_stats_follow_the_pinned_club(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=120)}")
    page.get_by_role("button", name="Me").click()
    page.get_by_role("button", name="Northgate").click()
    page.get_by_role("button", name="Stats").click()
    expect(page.get_by_test_id("stats-left")).to_have_text("Northgate", timeout=15_000)
    expect(page.get_by_test_id("stats-right")).to_have_text("Harbourside")


# ---------- real-world context (CX-*) ----------

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
    page.get_by_role("tab", name="Research").click()
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
        page.get_by_role("tab", name="Research").click()
        page.get_by_test_id("ask-input").fill("Average xG?")
        page.get_by_role("button", name="Ask").click()
        expect(page.get_by_test_id("ask-answer").first).to_contain_text("couldn't", timeout=15_000)
        expect(page.get_by_test_id("context-card")).to_have_count(0)
    finally:
        _stop(proc)


# ---------- fan app polish (F-*) ----------

def test_following_a_player_is_visible(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=60)}")
    page.get_by_role("button", name="Me").click()
    select = page.locator("select")
    first = select.locator("optgroup").first.locator("option").nth(9)
    value, label = first.get_attribute("value"), first.inner_text()
    name = label.split(". ", 1)[1]
    select.select_option(value)
    expect(page.get_by_test_id("follow-confirm")).to_contain_text(name)
    expect(page.get_by_test_id("following")).to_contain_text(name)
    select.select_option("")
    expect(page.get_by_test_id("following")).to_have_count(0)


def test_latest_moment_is_visible_without_scrolling(server, page: Page):
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(f"{server}/fan?match={new_match(server, speed=120)}")
    card = page.get_by_test_id("feed-item").first
    expect(card).to_be_visible(timeout=30_000)
    box = card.bounding_box()
    tabbar = page.locator("nav.tabbar").bounding_box()
    assert box["y"] + 60 < tabbar["y"], (box, tabbar)  # the headline of the latest card is above the tab bar


def test_fan_header_is_flat_with_scorers_under_each_team(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=400)}")
    hero = page.get_by_test_id("hero")
    expect(hero).to_be_visible()
    style = page.evaluate("""(() => { const h = document.querySelector('[data-testid=hero]');
      return [getComputedStyle(h).backgroundImage, getComputedStyle(h).backgroundColor, getComputedStyle(h, '::after').content] })()""")
    assert style[0] == "none" and style[1] == "rgb(55, 0, 60)" and style[2] in ("none", "normal"), style
    expect(page.get_by_test_id("clock")).to_have_text(re.compile(r"^\d{1,2}:\d{2}"), timeout=15_000)  # minutes and seconds
    box, digits = page.get_by_test_id("score").bounding_box(), page.evaluate("""(() => {
      const el = document.querySelector('[data-testid=score]'), r = document.createRange(); r.selectNodeContents(el);
      const b = r.getBoundingClientRect(); return {x: b.x, y: b.y, width: b.width, height: b.height} })()""")
    assert abs((box["x"] + box["width"] / 2) - (digits["x"] + digits["width"] / 2)) < 2  # scoreline centred in its box
    assert abs((box["y"] + box["height"] / 2) - (digits["y"] + digits["height"] / 2)) < 3
    assert page.get_by_test_id("clock").bounding_box()["y"] < page.get_by_test_id("score").bounding_box()["y"]  # above the score
    added = page.get_by_test_id("added-time")
    expect(added).to_have_text(re.compile(r"^\+\d+:\d{2}$"), timeout=40_000)  # stoppage time, e.g. 45:00 +2:13
    expect(page.get_by_test_id("clock")).to_contain_text(re.compile(r"^(45|90):00"))
    assert page.evaluate("getComputedStyle(document.querySelector('[data-testid=added-time]')).backgroundColor") == "rgb(233, 0, 82)"
    expect(hero.locator("[data-testid^=scorers-] li").first).to_be_visible(timeout=40_000)
    expect(hero.locator("[data-testid^=scorers-] li").first).to_contain_text(re.compile(r"\w+ \d+'"))


# ---------- Pattern Analyst (PA-*) ----------

def pattern_match(base: str, speed: float = 600) -> str:
    r = httpx.post(f"{base}/api/matches", json={"home": "har", "away": "kin", "seed": 42, "speed": speed})
    r.raise_for_status()
    return r.json()["match_id"]


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
    expect(alert).to_contain_text("Harbourside keep going down the left")


def test_fan_stats_show_how_each_team_is_playing(server, page: Page):
    page.goto(f"{server}/fan?match={pattern_match(server, speed=300)}")
    page.get_by_role("button", name="Stats").click()
    card = page.get_by_test_id("how-they-play")
    expect(card).to_be_visible(timeout=60_000)
    expect(card).to_contain_text(re.compile(r"Harbourside attack mostly down the left|Jovanovic is running Harbourside"))
    expect(card.locator(r"text=/\d/")).to_have_count(0)  # plain words, no numbers


def test_desk_opened_after_full_time_still_has_recaps_and_agent_activity(server, browser):
    mid = new_match(server, speed=600)
    watcher = browser.new_page()
    watcher.goto(f"{server}/fan?match={mid}")
    expect(watcher.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    watcher.wait_for_timeout(1500)  # let the full-time recap finish
    late = browser.new_page()
    late.goto(f"{server}/desk?match={mid}")
    expect(late.get_by_test_id("clock")).to_have_text("FT", timeout=15_000)
    late.get_by_role("tab", name="Recap").click()
    expect(late.get_by_test_id("recaps")).to_contain_text("recap", ignore_case=True)
    late.get_by_role("tab", name="Production").click()
    expect(late.get_by_test_id("agents").locator(".trace-item").first).to_be_visible()
    watcher.close()
    late.close()


# ---------- on-screen overlay (OV-*) ----------

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
    fan = page.context.new_page()
    fan.goto(f"{server}/fan?match={mid}")
    fan.get_by_role("button", name="Stats").click()
    fan.get_by_role("button", name="2nd half").click()
    expect(fan.get_by_test_id("stats")).to_have_attribute("data-period", "second_half")
    fan.close()


# ---------- substitution cards (SB-*) ----------

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


def test_fan_feed_explains_substitutions_and_marks_a_followed_player(server, page: Page):
    page.goto(f"{server}/fan?match={new_match(server, speed=600)}")
    sub = page.get_by_test_id("sub-feed-item").last
    expect(sub).to_be_visible(timeout=60_000)
    swap = sub.locator("h3").inner_text()
    on, off = re.match(r"(.+) comes on for (.+)", swap).groups()
    expect(sub.locator(".sub-lines li").first).to_contain_text(re.compile(rf"{re.escape(off)}: .+ in \d+ minutes"))
    assert not re.search(r"xG|%", sub.inner_text())
    page.get_by_role("button", name="Me").click()
    select = page.locator("select")
    value = select.locator("option", has_text=off).first.get_attribute("value")
    select.select_option(value)
    page.get_by_role("button", name="Live").click()
    expect(page.get_by_test_id("sub-feed-item").filter(has_text=swap)).to_have_attribute("data-mine", "true")


def test_fan_stats_list_the_cards(server, page: Page):
    from premier_analytics.generator import generate_match
    from premier_analytics.league import load_league
    events = generate_match("har", "ngc", 42, load_league()).events
    cards = [e for e in events if e.type == "card"]
    assert cards, "seed 42 should have at least one card"
    page.goto(f"{server}/fan?match={new_match(server, speed=600)}")
    expect(page.get_by_test_id("clock")).to_have_text("FT", timeout=60_000)
    page.get_by_role("button", name="Stats").click()
    items = page.get_by_test_id("cards-list").locator("li")
    expect(items).to_have_count(len(cards))
    expect(items.first).to_contain_text(re.compile(r"\d+'"))
    expect(page.get_by_test_id("cards-list")).not_to_contain_text("on a yellow")
    items.first.get_by_test_id("card-row").click()  # F-6a: the › opens why
    expect(items.first.get_by_test_id("card-why")).to_have_text(re.compile(
        r"Late tackle|counter-attack|Pulled back|Holding|Handball|Dissent|Time-wasting|Dangerous|clear chance|Violent|Offensive"))
    page.get_by_role("button", name="1st half").click()
    expect(items).to_have_count(sum(e.period == 1 for e in cards))


# ---------- the Producer (GP-*) ----------

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
    page.get_by_role("tab", name="Research").click()
    page.get_by_test_id("ask-input").fill("Who is winning?")
    page.get_by_role("button", name="Ask").click()
    answer = page.get_by_test_id("match-answer").first
    expect(answer).to_have_attribute("data-status", "ok", timeout=15_000)
    expect(answer).to_contain_text(re.compile(r"Harbourside \d+-\d+ Northgate"))
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
