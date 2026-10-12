"""D-10: corners and penalties in the simulation, calibrated to the 2024/25 Premier League."""
from statistics import mean

import pytest

from premier_analytics.engine import MatchEngine, xg
from premier_analytics.generator import generate_match
from premier_analytics.schema import PITCH_LENGTH as L, PITCH_WIDTH as W, Event


def near(value, target, tol):
    return abs(value - target) <= tol


def test_schema_accepts_corners_and_penalties():
    Event(id="e1", match_id="m", seq=1, period=1, clock_ms=0, elapsed_ms=0, type="corner", team_id="har",
          player_id="har-07", x=104.5, y=0.5)
    Event(id="e2", match_id="m", seq=2, period=1, clock_ms=0, elapsed_ms=0, type="penalty", team_id="har",
          player_id="har-09", x=94.0, y=34.0)
    with pytest.raises(ValueError):
        Event(id="e3", match_id="m", seq=3, period=1, clock_ms=0, elapsed_ms=0, type="corner", team_id="har")


def test_corners_per_match(season):
    corners = [sum(e.type == "corner" for e in m.events) for m in season]
    assert near(mean(corners), 10.8, 1.5), mean(corners)


def test_corners_are_taken_from_the_corner_flag_and_delivered_into_the_box(season):
    for m in season[:40]:
        events = m.events
        for i, e in enumerate(events):
            if e.type != "corner":
                continue
            assert e.x >= L - 1 and (e.y <= 1 or e.y >= W - 1)
            delivery = next(d for d in events[i + 1:] if d.type == "pass")
            assert delivery.set_piece == "corner" and delivery.team_id == e.team_id
            assert delivery.end_x >= L - 16.5


def test_about_three_percent_of_corners_lead_to_a_goal(season):
    corners = sum(e.type == "corner" for m in season for e in m.events)
    shots = {e.id: e for m in season for e in m.events if e.type == "shot"}
    from_corners = sum(1 for m in season for e in m.events
                       if e.type == "goal" and shots[e.related_event_id].set_piece == "corner")
    assert near(from_corners / corners, 0.03, 0.02), (from_corners, corners)


def test_penalties_per_match_and_conversion(season):
    pens = [e for m in season for e in m.events if e.type == "penalty"]
    assert near(len(pens) / len(season), 0.23, 0.12), len(pens) / len(season)
    shots = [e for m in season for e in m.events if e.type == "shot" and e.set_piece == "penalty"]
    assert len(shots) == len(pens)
    scored = sum(s.outcome == "goal" for s in shots)
    assert near(scored / len(shots), 0.83, 0.12), (scored, len(shots))


def test_penalties_follow_a_foul_in_the_box_and_are_taken_from_the_spot(season):
    for m in season:
        for i, e in enumerate(m.events):
            if e.type == "penalty":
                foul = next(f for f in reversed(m.events[:i]) if f.type == "foul")
                assert foul.team_id != e.team_id
                assert foul.x <= 16.5 and abs(foul.y - W / 2) <= 20.16 + 0.01  # in the fouling side's own box
                kick = next(s for s in m.events[i + 1:] if s.type == "shot")
                assert kick.set_piece == "penalty" and (kick.x, kick.y) == (L - 11, W / 2)


def test_a_penalty_is_worth_about_078_xg(league):
    m = next(generate_match("har", "kin", seed, league) for seed in range(200)
             if any(e.type == "penalty" for e in generate_match("har", "kin", seed, league).events))
    engine = MatchEngine("har", "kin")
    for e in m.events:
        metric = engine.apply(e)
        if e.type == "shot" and e.set_piece == "penalty":
            assert metric.xg == pytest.approx(0.78)
    assert xg(L - 11, W / 2) < 0.6  # an open-play shot from the spot is worth much less


def test_engine_counts_corners(league):
    m = generate_match("har", "kin", 42, league)
    engine = MatchEngine("har", "kin")
    for e in m.events:
        engine.apply(e)
    for team in ("har", "kin"):
        assert engine.teams[team].corners == sum(e.type == "corner" and e.team_id == team for e in m.events)


# ---------- set pieces in the product ----------

def _first_with_penalty(league):
    for seed in range(300):
        m = generate_match("har", "kin", seed, league)
        if any(e.type == "penalty" for e in m.events):
            return m
    raise AssertionError("no penalty in 300 matches")


def test_a_penalty_is_a_moment_and_set_pieces_are_facts(league):
    from premier_analytics.scout import FAN_THRESHOLD, MomentScout
    m = _first_with_penalty(league)
    scout = MomentScout("har", "kin", m.meta.match_id)
    moments = [mo for e in m.events for mo in scout.observe(e)]
    pens = [mo for mo in moments if mo.kind == "penalty"]
    assert pens and all(mo.severity >= FAN_THRESHOLD for mo in pens)
    facts = {f.label: f.value for f in pens[0].facts}
    assert {"score_home", "score_away", "minute"} <= set(facts)
    shot_moments = [mo for mo in moments if mo.kind in ("goal", "big_chance", "woodwork", "shot_on_target")]
    tagged = [mo for mo in shot_moments if any(f.label == "set_piece" for f in mo.facts)]
    assert tagged and all(f.value in ("corner", "penalty") for mo in tagged for f in mo.facts if f.label == "set_piece")


@pytest.mark.parametrize("language", ["en", "es", "ar"])
def test_penalty_has_template_wording(language, league):
    from premier_analytics.overlay import Audience, Names, fast_overlay
    from premier_analytics.scout import MomentScout
    m = _first_with_penalty(league)
    scout = MomentScout("har", "kin", m.meta.match_id)
    pen = next(mo for e in m.events for mo in scout.observe(e) if mo.kind == "penalty")
    o = fast_overlay(pen, Audience(mode="fan", language=language), Names.from_league(league, "har", "kin"))
    assert o.headline and o.body and "{" not in o.headline + o.body


def test_desk_feed_has_corners_and_penalties(league):
    from fastapi.testclient import TestClient
    from premier_analytics.app import create_app
    from test_app import collect
    m = _first_with_penalty(league)
    with TestClient(create_app(llm=None, live_session=False)) as c:
        mid = c.post("/api/matches", json={"home": "har", "away": "kin", "seed": m.meta.seed, "speed": 0,
                                           "autostart": False}).json()["match_id"]
        with c.websocket_connect(f"/ws/matches/{mid}?mode=analyst") as ws:
            ws.receive_json()
            c.post(f"/api/matches/{mid}/start")
            msgs = collect(ws)
    stats = [x for x in msgs if x["type"] == "stats"][-1]
    assert stats["home"]["corners"] + stats["away"]["corners"] == sum(e.type == "corner" for e in m.events)
    kinds = [x["incident"]["kind"] for x in msgs if x["type"] == "incident"]
    assert "penalty" in kinds
