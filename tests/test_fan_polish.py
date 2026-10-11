"""F-1, F-3, F-4: fan app polish on the server side."""
import asyncio

from fastapi.testclient import TestClient

from premier_analytics.agents import CriticAgent, FakeLLM
from premier_analytics.app import create_app
from premier_analytics.demo_llm import scripted_llm
from premier_analytics.generator import generate_match
from premier_analytics.orchestrator import TREND_KINDS, Orchestrator, TrendThrottle
from premier_analytics.overlay import Audience, Names
from premier_analytics.recap import RecapDraft, RecapProducer
from premier_analytics.scout import Moment

from test_app import collect, start

MIN = 60_000


def trend(kind, team, minute, i=0):
    return Moment(id=f"m{minute}-{i}", kind=kind, severity=0.6, event_id="e", period=1, clock_ms=minute * MIN,
                  elapsed_ms=minute * MIN, team_id=team, facts=[])


# ---------- F-1 ----------

def test_throttle_one_trend_card_per_team_per_15_minutes():
    t = TrendThrottle()
    assert t.allow(trend("momentum_shift", "har", 17))
    assert not t.allow(trend("pressure_spell", "har", 18))      # same story a minute later
    assert t.allow(trend("pressure_spell", "ngc", 20))           # the other team takes over
    assert t.allow(trend("momentum_shift", "har", 25))           # and back again
    assert not t.allow(trend("pressure_spell", "har", 35))
    assert t.allow(trend("pressure_spell", "har", 41))           # 16 minutes after the last har card


def test_throttle_ignores_other_moments():
    t = TrendThrottle()
    goal = Moment(id="g", kind="goal", severity=1, event_id="e", period=1, clock_ms=0, elapsed_ms=0, team_id="har", facts=[])
    assert t.allow(goal) and t.allow(goal)


def _play(audiences, llm=None):
    league_match = generate_match("har", "ngc", 42)
    names = Names(home_id="har", away_id="ngc", clubs={"har": "Harbourside", "ngc": "Northgate"}, players={})
    critic = CriticAgent(set(), {"Harbourside", "Northgate"})

    async def go():
        orch = Orchestrator("har", "ngc", "m", names, audiences, llm=llm, critic=critic)
        for e in league_match.events:
            await orch.handle(e)
        await orch.drain()
        return orch
    return asyncio.run(go())


def test_fans_get_fewer_trend_cards_than_commentators():
    fan, analyst = Audience(mode="fan"), Audience(mode="analyst")
    orch = _play([fan, analyst])
    trends = {a.key: [o for o in orch.published if o.audience == a.key and o.kind in TREND_KINDS] for a in (fan, analyst)}
    assert len(trends[fan.key]) < len(trends[analyst.key])
    by_team: dict = {}
    for o in sorted(trends[fan.key], key=lambda o: o.elapsed_in_ms):
        last = by_team.get(o.team_id)
        others = [x for x in trends[fan.key] if x.team_id != o.team_id and last is not None
                  and last.elapsed_in_ms < x.elapsed_in_ms < o.elapsed_in_ms]
        assert last is None or o.elapsed_in_ms - last.elapsed_in_ms >= 15 * MIN or others
        by_team[o.team_id] = o


def test_late_joiner_sees_the_same_cards():
    with TestClient(create_app(llm=None, live_session=False)) as c:
        mid = start(c, autostart=False)
        with c.websocket_connect(f"/ws/matches/{mid}?mode=fan") as ws:
            ws.receive_json()
            c.post(f"/api/matches/{mid}/start")
            live = [m["overlay"]["moment_id"] for m in collect(ws) if m["type"] == "overlay"]
        with c.websocket_connect(f"/ws/matches/{mid}?mode=fan") as ws:
            ws.receive_json()
            backfill = [o["moment_id"] for o in ws.receive_json()["overlays"]]
    assert backfill == live[-len(backfill):]


# ---------- F-3 ----------

def _producer(llm):
    from premier_analytics.orchestrator import MatchState
    from premier_analytics.scout import MomentScout
    names = Names(home_id="har", away_id="ngc", clubs={"har": "Harbourside", "ngc": "Northgate"}, players={})
    state = MatchState(names=names, scout=MomentScout("har", "ngc", "m"))
    return RecapProducer(llm, CriticAgent(set(), {"Harbourside", "Northgate"}), state)


def test_fan_recap_is_written_separately_with_plain_instructions():
    seen = []

    def recap(prompt):
        seen.append(prompt)
        return RecapDraft(headline="All square", summary="Neither side could find a goal.", key_points=[])

    llm = FakeLLM({"recap": recap})
    p = _producer(llm)
    fan = asyncio.run(p.run("half_time", "en", mode="fan"))
    analyst = asyncio.run(p.run("half_time", "en", mode="analyst"))
    assert fan.mode == "fan" and analyst.mode == "analyst" and llm.count("recap") == 2
    fan_instr = [c.instructions for c in llm.calls][0]
    assert "whole numbers" in fan_instr and "xG" in fan_instr  # told not to use it


def test_fan_recap_with_decimals_or_jargon_is_rejected():
    p = _producer(FakeLLM({}))
    from premier_analytics.recap import Recap
    bad = Recap(headline="Northgate on top", summary="Northgate had 0.5 more xG.", key_points=[], mode="fan")
    problems = p.review(bad)
    assert any("jargon" in x for x in problems) and any("whole numbers" in x for x in problems)
    ok_for_analysts = bad.model_copy(update={"mode": "analyst"})
    assert not any("jargon" in x or "whole numbers" in x for x in p.review(ok_for_analysts))


def test_fans_and_commentators_receive_their_own_recaps():
    with TestClient(create_app(llm=scripted_llm(delay=0), live_session=False)) as c:
        mid = start(c, autostart=False)
        with c.websocket_connect(f"/ws/matches/{mid}?mode=fan") as fan, \
                c.websocket_connect(f"/ws/matches/{mid}?mode=analyst") as desk:
            fan.receive_json(), desk.receive_json()
            c.post(f"/api/matches/{mid}/start")
            fan_r = [m["recap"]["mode"] for m in collect(fan) if m["type"] == "recap"]
            desk_r = [m["recap"]["mode"] for m in collect(desk) if m["type"] == "recap"]
    assert fan_r and set(fan_r) == {"fan"}
    assert desk_r and set(desk_r) == {"analyst"}


# ---------- F-4 ----------

def test_changing_settings_keeps_fitting_ai_versions():
    with TestClient(create_app(llm=scripted_llm(delay=0), live_session=False)) as c:
        mid = start(c, autostart=False)
        with c.websocket_connect(f"/ws/matches/{mid}?mode=fan") as ws:
            ws.receive_json()
            c.post(f"/api/matches/{mid}/start")
            collect(ws)
        # Now following a club: neutral fan AI versions fit; a club-specific one for the other club would not.
        with c.websocket_connect(f"/ws/matches/{mid}?mode=fan&club_id=har") as ws:
            ws.receive_json()
            backfill = ws.receive_json()["overlays"]
    assert any(o["source"] == "ai" for o in backfill)
    assert all(o["audience"] == "fan.en.har.-" for o in backfill)


def test_ai_versions_for_another_club_are_never_reused():
    from premier_analytics.app import fitting_ai_version
    from premier_analytics.overlay import Overlay
    base = dict(match_id="m", moment_id="m1", kind="goal", team_id="har", priority=1, slot="lower_third",
                clock_in_ms=0, clock_out_ms=1, minute="5", elapsed_in_ms=0, headline="h", body="b", language="en",
                direction="ltr", source="ai", version=2, evidence=["f"], data={}, model="x")
    ngc_fan = Overlay(id="m1:fan.en.ngc.-", audience="fan.en.ngc.-", **base)
    neutral = Overlay(id="m1:fan.en.-.-", audience="fan.en.-.-", **base)
    want = Audience(mode="fan", club_id="har")
    assert fitting_ai_version([ngc_fan], want) is None
    assert fitting_ai_version([ngc_fan, neutral], want).audience == "fan.en.-.-"
    assert fitting_ai_version([neutral], Audience(mode="analyst")) is None
    assert fitting_ai_version([neutral], Audience(mode="fan", language="es")) is None
