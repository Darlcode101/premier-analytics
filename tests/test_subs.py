"""SB-1, SB-2, SB-4, SB-6, SB-7: substitution cards for the desk, the fan app and the broadcast overlay."""
import re

import pytest
from fastapi.testclient import TestClient

from premier_analytics.app import create_app
from premier_analytics.engine import MatchEngine
from premier_analytics.generator import generate_match
from premier_analytics.overlay import TEMPLATES, Audience, Names, fast_overlay
from premier_analytics.scout import MomentScout
from premier_analytics.season import season_summary, simulate_season
from premier_analytics.subs import SubCards, change_type, key_stat
from premier_analytics.languages import LANGS

from test_app import collect, start



def replay(league, home="har", away="ngc", seed=42, season=None):
    """Every card from one match, with the engine's player lines captured just before each change."""
    m = generate_match(home, away, seed, league)
    engine = MatchEngine(home, away)
    cards = SubCards(league, Names.from_league(league, home, away), season)
    out, booked = [], set()
    for e in m.events:
        engine.apply(e)
        if e.type == "card" and e.card == "yellow":
            booked.add(e.player_id)
        card = cards.observe(e, engine)
        if card:
            out.append((e, {**card, "_score": tuple(engine.score)}, engine.players.get(e.player_out_id), set(booked)))
    return m, out


@pytest.fixture(scope="module")
def season(league):
    return season_summary(simulate_season(league), league, "har", "ngc")


def test_change_type_follows_the_positions():
    assert change_type("CM", "CM") == "like_for_like"
    assert change_type("CB", "FB") == "like_for_like"
    assert change_type("W", "AM") == "like_for_like"
    assert change_type("DM", "ST") == "more_attacking"
    assert change_type("ST", "CB") == "more_defensive"
    assert change_type("CM", "DM") == "more_defensive"


def test_cards_carry_the_players_numbers_at_the_change(league, season):
    found = 0
    for seed in (42, 7, 9):
        m, cards = replay(league, seed=seed, season=season)
        came_on = {}
        used = {"har": 0, "ngc": 0}
        for e, card, line, booked in cards:
            found += 1
            used[e.team_id] += 1
            off, on = card["off"], card["on"]
            assert card["team_id"] == e.team_id and card["event_id"] == e.id
            assert off["player_id"] == e.player_out_id and on["player_id"] == e.player_in_id
            assert card["subs_used"] == used[e.team_id] and card["subs_allowed"] == 5
            assert (card["score_home"], card["score_away"]) == card["_score"]
            start_ms = came_on.get(e.player_out_id, 0)
            assert off["minutes"] == (e.clock_ms - start_ms) // 60_000  # match clock: 74' means 74 minutes for a starter
            came_on[e.player_in_id] = e.clock_ms
            for k in ("passes", "passes_completed", "shots", "goals", "assists", "tackles_won", "interceptions", "fouls"):
                assert off["line"][k] == (getattr(line, k) if line else 0), k
            assert off["booked"] == (e.player_out_id in booked)
            p_off, p_on = league.player(e.player_out_id), league.player(e.player_in_id)
            assert off["position"] == p_off.position and on["number"] == p_on.number
            assert card["change"] == change_type(p_off.position, p_on.position)
            side = "home" if e.team_id == "har" else "away"
            assert on["season"] == season[side]["players"][e.player_in_id]
            assert off["season"] == season[side]["players"][e.player_out_id]
    assert found >= 6


def test_cards_work_without_a_season(league):
    _, cards = replay(league)
    assert cards and all(c["off"]["season"] is None and c["on"]["season"] is None for _, c, _, _ in cards)


@pytest.mark.parametrize("language", LANGS)
def test_fan_lines_are_plain_and_only_use_the_cards_numbers(league, season, language):
    for seed in (42, 7, 9, 11):
        _, cards = replay(league, seed=seed, season=season)
        for e, card, _, _ in cards:
            lines = card["fan"][language]
            assert 2 <= len(lines) <= 4, lines
            text = " ".join(lines)
            assert "{" not in text and "%" not in text and not re.search(r"\bxG\b", text, re.I)
            off, on = card["off"], card["on"]
            allowed = {str(v) for v in (*off["line"].values(), off["line"]["tackles_won"] + off["line"]["interceptions"],
                                        *(on["season"] or {}).values(), off["minutes"])}
            assert set(re.findall(r"\d+", text)) <= allowed, (text, allowed)
            names = Names.from_league(league, "har", "ngc")
            assert names.player(e.player_in_id) in lines[0] and names.player(e.player_out_id) in lines[0]


def test_fan_line_mentions_goals_when_the_player_scored():
    stat = key_stat({"goals": 2, "assists": 1, "passes": 30, "shots": 4, "ball_wins": 1}, "en")
    assert stat.startswith("2 goals, 1 assist")
    assert key_stat({"goals": 1, "assists": 0, "passes": 34, "shots": 1, "ball_wins": 0}, "en") == "1 goal, 34 passes"
    assert key_stat({"goals": 0, "assists": 0, "passes": 12, "shots": 3, "ball_wins": 0}, "en") == "3 shots"
    assert key_stat({"goals": 0, "assists": 0, "passes": 12, "shots": 0, "ball_wins": 6}, "en") == "6 ball wins"
    for lang in LANGS:
        assert key_stat({"goals": 1, "assists": 0, "passes": 34, "shots": 1, "ball_wins": 0}, lang)


# ---------- SB-7: the overlay graphic ----------

@pytest.mark.parametrize("language", LANGS)
def test_substitution_overlay_adds_a_key_stat_from_the_moments_facts(league, language):
    m = generate_match("har", "ngc", 42, league)
    scout = MomentScout("har", "ngc", m.meta.match_id)
    names = Names.from_league(league, "har", "ngc")
    subs = [mo for e in m.events for mo in scout.observe(e) if mo.kind == "substitution"]
    assert subs
    for mo in subs:
        facts = {f.label: f.value for f in mo.facts}
        stat = key_stat({k: facts[f"off_{k}"] for k in ("goals", "assists", "passes", "shots", "ball_wins")}, language)
        for mode in ("fan", "analyst"):
            o = fast_overlay(mo, Audience(mode=mode, language=language), names)
            assert stat in o.body and "{" not in o.body, o.body
    assert all("{out_stat}" in TEMPLATES[lang]["substitution"][1] for lang in LANGS)


# ---------- SB-6: through the app with the AI off ----------

@pytest.fixture
def client():
    with TestClient(create_app(llm=None, live_session=False)) as c:
        yield c


def test_every_sub_incident_carries_a_card_and_late_joiners_get_them(client):
    mid = start(client, seed=42)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=es") as ws:
        msgs = collect(ws)
    subs = [m["incident"] for m in msgs if m["type"] == "incident" and m["incident"]["kind"] == "sub"]
    assert subs and all(s["card"]["fan"]["es"] and s["card"]["off"]["player_id"] == s["player_out_id"] for s in subs)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst") as ws:
        hello = ws.receive_json()
    late = [i for i in hello["incidents"] if i["kind"] == "sub"]
    assert [i["card"] for i in late] == [s["card"] for s in subs]
