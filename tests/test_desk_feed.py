"""CD-5..CD-8, CD-11, CD-14, CD-17: the deterministic data the commentator desk is built from."""
import pytest
from fastapi.testclient import TestClient

from premier_analytics.app import create_app
from premier_analytics.desk import Incidents, last_window
from premier_analytics.engine import BIG_CHANCE_XG, MatchEngine
from premier_analytics.generator import generate_match

from test_app import collect, start


def incidents_for(match):
    engine = MatchEngine(match.meta.home_id, match.meta.away_id)
    feed = Incidents()
    out = []
    for e in match.events:
        metric = engine.apply(e)
        inc = feed.observe(e, metric)
        if inc:
            out.append(inc)
    return out, engine


@pytest.mark.parametrize("seed", [42, 7, 9])
def test_every_goal_card_and_substitution_appears_once(league, seed):
    match = generate_match("har", "ngc", seed, league)
    incs, _ = incidents_for(match)
    for etype, kinds in (("goal", {"goal"}), ("card", {"yellow", "second_yellow", "red"}), ("substitution", {"sub"})):
        events = [e for e in match.events if e.type == etype]
        found = [i for i in incs if i["kind"] in kinds]
        assert [i["event_id"] for i in found] == [e.id for e in events]
    assert len({i["id"] for i in incs}) == len(incs)


def test_goal_incident_carries_scorer_assist_and_score(league):
    match = generate_match("har", "ngc", 42, league)
    incs, _ = incidents_for(match)
    goal_events = {e.id: e for e in match.events if e.type == "goal"}
    for g in (i for i in incs if i["kind"] == "goal"):
        e = goal_events[g["event_id"]]
        assert (g["player_id"], g["assist_id"], g["team_id"]) == (e.player_id, e.assist_id, e.team_id)
        assert (g["score_home"], g["score_away"]) == (e.score_home, e.score_away)
        assert g["minute"]


def test_big_chances_and_woodwork_come_from_shots(league):
    match = generate_match("har", "ngc", 42, league)
    incs, engine = incidents_for(match)
    shots = [e for e in match.events if e.type == "shot"]
    woodwork = [e.id for e in shots if e.outcome == "woodwork"]
    missed_big = [e.id for e in shots if e.outcome not in ("goal", "woodwork") and engine.metrics[e.id].xg >= BIG_CHANCE_XG]
    assert [i["event_id"] for i in incs if i["kind"] == "woodwork"] == woodwork
    assert [i["event_id"] for i in incs if i["kind"] == "big_chance"] == missed_big
    assert all(i["xg"] >= BIG_CHANCE_XG for i in incs if i["kind"] == "big_chance")


def test_substitution_incident_names_both_players(league):
    match = generate_match("har", "ngc", 42, league)
    incs, _ = incidents_for(match)
    subs = [i for i in incs if i["kind"] == "sub"]
    assert subs and all(i["player_in_id"] and i["player_out_id"] for i in subs)


def test_last_window_is_the_difference_between_snapshots():
    then = {"goals": 1, "shots": 6, "passes": 200, "passes_completed": 170, "xg": 0.8, "possession_pct": 50.0}
    now = {"goals": 2, "shots": 9, "passes": 260, "passes_completed": 215, "xg": 1.5, "possession_pct": 55.0}
    w = last_window(now, then, now_ms=60 * 60_000, then_ms=50 * 60_000)
    assert (w["goals"], w["shots"], w["passes"], w["passes_completed"]) == (1, 3, 60, 45)
    assert w["xg"] == pytest.approx(0.7)
    assert w["pass_accuracy"] == pytest.approx(45 / 60)
    # 55% of 60 minutes minus 50% of 50 minutes, over the 10 minutes between
    assert w["possession_pct"] == pytest.approx((55 * 60 - 50 * 50) / 10)


def test_last_window_before_ten_minutes_is_the_whole_match():
    now = {"goals": 0, "shots": 2, "passes": 40, "passes_completed": 30, "xg": 0.2, "possession_pct": 60.0}
    w = last_window(now, None, now_ms=6 * 60_000, then_ms=0)
    assert w["shots"] == 2 and w["possession_pct"] == pytest.approx(60.0)


# ---------- over the WebSocket ----------

@pytest.fixture
def plain_client():
    """AI off: everything on the desk except talking points and recaps must still work (CD-17)."""
    with TestClient(create_app(llm=None, live_session=False, max_sessions=3)) as c:
        yield c


def test_desk_messages_with_ai_off(plain_client, league):
    mid = start(plain_client, autostart=False)
    with plain_client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["subs_allowed"] == 5
        assert hello["incidents"] == []
        assert [p["position"] for p in hello["home"]["lineup"]][0] == "GK"
        plain_client.post(f"/api/matches/{mid}/start")
        msgs = collect(ws)
    incs = [m["incident"] for m in msgs if m["type"] == "incident"]
    match = generate_match("har", "ngc", 42, league)
    expected, engine = incidents_for(match)
    assert [i["id"] for i in incs] == [i["id"] for i in expected]

    last_stats = [m for m in msgs if m["type"] == "stats"][-1]
    players = last_stats["players"]
    for pid, p in engine.players.items():
        assert players[pid]["passes"] == p.passes and players[pid]["goals"] == p.goals
        assert players[pid]["xg"] == pytest.approx(p.xg, abs=0.001)
    assert {"shots", "xg", "passes", "final_third_passes", "possession_pct", "pass_accuracy"} <= set(last_stats["home"]["last10"])


def test_late_joiner_gets_incident_history(plain_client):
    mid = start(plain_client)
    with plain_client.websocket_connect(f"/ws/matches/{mid}") as ws:
        collect(ws)
    with plain_client.websocket_connect(f"/ws/matches/{mid}?mode=analyst") as ws:
        hello = ws.receive_json()
    assert any(i["kind"] == "goal" for i in hello["incidents"])


def test_hello_carries_season_context(plain_client, league):
    mid = start(plain_client, autostart=False)
    with plain_client.websocket_connect(f"/ws/matches/{mid}") as ws:
        hello = ws.receive_json()
    season = hello["season"]
    assert season["matches"] == 56 and len(season["table"]) == len(league.clubs)
    assert {r["short_name"] for r in season["table"]} == {c.short_name for c in league.clubs}
    for side in ("home", "away"):
        ctx = season[side]
        assert {"position", "points", "form", "players", "top_scorers"} <= set(ctx)


# ---------- late joiners get recaps and agent activity ----------

def _played(client, mode):
    mid = start(client, autostart=False)
    with client.websocket_connect(f"/ws/matches/{mid}?mode={mode}&language=en") as ws:
        ws.receive_json()
        client.post(f"/api/matches/{mid}/start")
        collect(ws)
    return mid


@pytest.fixture
def ai_client():
    from premier_analytics.demo_llm import scripted_llm
    with TestClient(create_app(llm=scripted_llm(delay=0), live_session=False, max_sessions=3)) as c:
        yield c


def test_late_desk_gets_recaps_and_agent_activity(ai_client):
    mid = _played(ai_client, "analyst")
    with ai_client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as ws:
        hello = ws.receive_json()
    assert {r["kind"] for r in hello["recaps"]} == {"half_time", "full_time"}
    assert all(r["mode"] == "analyst" and r["language"] == "en" for r in hello["recaps"])
    assert hello["trace"] and {"agent", "outcome", "moment_id"} <= set(hello["trace"][0])
    assert hello["trace_counts"]["published"] > 0


def test_late_viewer_gets_a_recap_even_if_only_the_other_mode_was_written(ai_client):
    mid = _played(ai_client, "fan")
    with ai_client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as ws:
        hello = ws.receive_json()
    assert {r["kind"] for r in hello["recaps"]} == {"half_time", "full_time"}
    assert all(r["language"] == "en" for r in hello["recaps"])


def test_desk_sees_the_whole_systems_agent_activity(ai_client):
    """The Production tab is about the system: a desk joining late sees work done for fans too."""
    mid = _played(ai_client, "fan")
    with ai_client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as ws:
        hello = ws.receive_json()
    assert hello["trace_counts"]["published"] > 0
    assert any(t["audience"].startswith("fan.") for t in hello["trace"])


# ---------- stats by half ----------

def test_stats_split_by_half(plain_client):
    mid = start(plain_client, autostart=False)
    with plain_client.websocket_connect(f"/ws/matches/{mid}?mode=analyst") as ws:
        ws.receive_json()
        plain_client.post(f"/api/matches/{mid}/start")
        msgs = collect(ws)
    stats = [m for m in msgs if m["type"] == "stats"]
    first_half_live = next(s for s in stats if s["period"] == 1 and s["elapsed_ms"] > 20 * 60_000)
    for side in ("home", "away"):
        assert first_half_live[side]["first_half"]["shots"] == first_half_live[side]["shots"]  # in progress
        assert first_half_live[side]["second_half"] is None
    final = stats[-1]
    for side in ("home", "away"):
        t, h1, h2 = final[side], final[side]["first_half"], final[side]["second_half"]
        for k in ("goals", "shots", "passes", "corners", "fouls", "yellow_cards"):
            assert h1[k] + h2[k] == t[k], (side, k)
        assert h1["xg"] + h2["xg"] == pytest.approx(t["xg"], abs=0.01)
        assert 0 <= h2["possession_pct"] <= 100 and 0 <= h2["pass_accuracy"] <= 1
    assert final["home"]["first_half"]["possession_pct"] + final["away"]["first_half"]["possession_pct"] == pytest.approx(100, abs=1)
