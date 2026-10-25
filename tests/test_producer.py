"""GP-1..GP-6: the Producer picks what the commentator should say next, and when."""
import asyncio
from collections import defaultdict
from statistics import median

import pytest
from fastapi.testclient import TestClient

from premier_analytics.agents import CriticAgent, FakeLLM
from premier_analytics.app import create_app
from premier_analytics.generator import generate_match
from premier_analytics.overlay import Names
from premier_analytics.producer import BREAK_WINDOWS_S, Candidate, Producer, ProducerAgent, ProducerNote, break_of
from premier_analytics.schema import Event

from premier_analytics.orchestrator import Orchestrator

from test_app import collect, fake_llm, start

MIN = 60_000


def ev(kind: str, at_ms: int, seq: int = 0, **fields) -> Event:
    return Event(id=f"m-{seq:05d}", match_id="m", seq=seq, period=fields.pop("period", 1), clock_ms=at_ms,
                 elapsed_ms=at_ms, type=kind, **fields)


def cand(ref, importance=0.6, at_min=10.0, kind="moment", **extra) -> Candidate:
    return Candidate(ref=ref, kind=kind, label=extra.pop("label", "momentum_shift"), source=extra.pop("source", "explainer"),
                     importance=importance, elapsed_ms=int(at_min * MIN), team_id="har", **extra)


FOUL = dict(team_id="har", player_id="har-04", x=40.0, y=30.0, fouled_player_id="ngc-09")
PASS = dict(team_id="har", player_id="har-08", x=40.0, y=30.0, end_x=50.0, end_y=30.0, outcome="complete",
            receiver_id="har-10", under_pressure=False)


# ---------- GP-2: breaks ----------

def test_stoppages_are_breaks_and_play_resuming_ends_them():
    assert break_of(ev("foul", 0, **FOUL)) == "free_kick"
    assert break_of(ev("substitution", 0, team_id="har", player_out_id="har-04", player_in_id="har-14")) == "substitution"
    assert break_of(ev("possession_change", 0, team_id="ngc", cause="goal_kick", x=6.0, y=34.0)) == "goal_kick"
    assert break_of(ev("possession_change", 0, team_id="ngc", cause="out_of_play", x=50.0, y=0.0)) is None  # throw-in
    assert break_of(ev("period_end", 45 * MIN, score_home=0, score_away=0)) == "half_time"
    p = Producer()
    p.offer(cand("m1"))
    cue = p.observe(ev("foul", 10 * MIN, **FOUL))
    assert cue.state == "on_air" and cue.break_kind == "free_kick" and cue.window_s == BREAK_WINDOWS_S["free_kick"]
    cue = p.observe(ev("pass", 10 * MIN + 40_000, 1, **PASS))
    assert cue.state == "up_next" and cue.break_kind is None and cue.ref == "m1"


def test_break_windows_match_the_simulation(league):
    """GP-2: the '~N s' a commentator is told is the simulation's typical stoppage length (±35 %)."""
    gaps = defaultdict(list)
    ids = [c.id for c in league.clubs]
    for seed in range(40):
        events = generate_match(ids[seed % 8], ids[(seed + 3) % 8], seed, league).events
        for i, e in enumerate(events):
            kind = break_of(e)
            if kind in (None, "half_time", "full_time"):
                continue
            nxt = next((x for x in events[i + 1:] if x.type in ("pass", "shot", "kickoff", "period_end")), None)
            if nxt is not None and nxt.type != "period_end" and nxt.period == e.period:
                gaps[kind].append((nxt.elapsed_ms - e.elapsed_ms) / 1000)
    for kind, values in gaps.items():
        if len(values) >= 8:
            assert 0.65 * median(values) <= BREAK_WINDOWS_S[kind] <= 1.35 * median(values), (kind, median(values))
    assert {"free_kick", "substitution", "goal", "goal_kick", "card"} <= set(gaps)


# ---------- GP-1: ranking ----------

def pick(p: Producer, at_min: float):
    return p.observe(ev("foul", int(at_min * MIN), **FOUL)) or p.current


def test_importance_wins_when_equally_fresh():
    p = Producer()
    p.offer(cand("small", 0.4, 10))
    p.offer(cand("big", 0.9, 10))
    assert pick(p, 10.5).ref == "big"


def test_a_fresh_medium_moment_beats_an_old_big_one():
    p = Producer()
    p.offer(cand("old_goal", 0.95, 1, label="goal"))
    p.offer(cand("fresh", 0.6, 19.5))
    assert pick(p, 20).ref == "fresh"


def test_patterns_age_more_slowly_than_moments():
    p = Producer()
    p.offer(cand("moment", 0.7, 10))
    p.offer(cand("pattern", 0.7, 10, kind="pattern", label="flank", source="pattern_analyst"))
    assert pick(p, 20).ref == "pattern"


def test_context_and_storyline_boost_and_say_why():
    p = Producer()
    p.offer(cand("plain", 0.6, 10))
    p.offer(cand("with_context", 0.5, 10))
    p.mark_context("with_context")
    cue = pick(p, 10.5)
    assert cue.ref == "with_context" and "context" in cue.reasons
    p.offer(cand("story", 0.4, 10, storyline="Can Kowalczyk prove himself?"))
    cue = pick(p, 10.6)
    assert cue.ref == "story" and "storyline" in cue.reasons


def test_used_items_are_never_cued_and_stale_ones_drop_out():
    p = Producer()
    p.offer(cand("a", 0.9, 10))
    p.offer(cand("b", 0.5, 10))
    assert pick(p, 10.5).ref == "a"
    cue = p.mark_used("a", True)
    assert cue.ref == "b" and p.used == {"a"}
    p.mark_used("b", True)
    assert pick(p, 11) is None or p.current is None
    q = Producer()
    q.offer(cand("ancient", 0.95, 1))
    assert pick(q, 40) is None and q.current is None


def test_cues_are_only_published_when_they_change():
    p = Producer()
    p.offer(cand("a", 0.9, 10))
    assert p.observe(ev("foul", 10 * MIN, **FOUL)) is not None
    assert p.observe(ev("foul", 10 * MIN + 1000, 1, **FOUL)) is None  # same item, still on air
    first = p.current
    assert first.source == "explainer" and first.reasons and first.id


# ---------- GP-5: the AI note ----------

NAMES = Names(home_id="har", away_id="ngc", clubs={"har": "Hyperion", "ngc": "Selene"},
              players={"har-14": "Zane Kowalczyk", "har-04": "Leandro Ashworth"})
CRITIC = CriticAgent({"Zane Kowalczyk", "Leandro Ashworth", "Kai Greaves"}, {"Hyperion", "Selene"})
ITEMS = [
    cand("m9", 0.9, 76, text="Zane Kowalczyk wins a penalty for Hyperion (90+7')", numbers={"90", "7"},
         players={"Zane Kowalczyk"}),
    cand("p1", 0.7, 45, kind="pattern", text="Hyperion attack down the left: 31 of 52 entries",
         numbers={"31", "52"}, players=set(), source="pattern_analyst"),
]


def note_with(text):
    agent = ProducerAgent(FakeLLM({"producer": lambda prompt: ProducerNote(text=text)}), CRITIC)
    return asyncio.run(agent.note(ITEMS[0], ITEMS[1:], NAMES))


def test_a_grounded_note_is_kept():
    assert note_with("Hyperion's 31 entries down the left made this.") == "Hyperion's 31 entries down the left made this."


def test_nothing_useful_means_no_note():
    assert note_with("NONE") is None
    assert note_with("") is None


def test_invented_numbers_or_players_are_dropped():
    assert note_with("Kowalczyk has 4 goals in 3 games.") is None
    assert note_with("Kai Greaves set it up.") is None


# ---------- through the app (AI off: GP-4, GP-6) ----------

@pytest.fixture
def client():
    with TestClient(create_app(llm=None, live_session=False)) as c:
        yield c


def test_desk_gets_cues_and_used_is_shared(client):
    mid = start(client, home="har", away="ngc", seed=292, autostart=False)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as desk:
        hello = desk.receive_json()
        assert hello["used"] == [] and hello["cue"] is None
        client.post(f"/api/matches/{mid}/start")
        msgs = collect(desk)
    cues = [m["cue"] for m in msgs if m["type"] == "cue"]
    assert cues and any(c["state"] == "on_air" and c["break_kind"] == "substitution" for c in cues)
    assert any(c["state"] == "on_air" and c["break_kind"] == "goal" for c in cues)
    assert all(c["source"] and c["reasons"] is not None for c in cues)
    trace = [m["trace"] for m in msgs if m["type"] == "trace" and m["trace"]["agent"] == "producer"]
    assert trace  # GP-3: decisions are in the agent trace

    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as a, \
            client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=es") as b:
        cue = a.receive_json()["cue"]
        b.receive_json()
        a.send_json({"type": "used", "ref": cue["ref"], "used": True})
        for ws in (a, b):  # both desks hear about it
            got = ws.receive_json()
            while got["type"] != "used":
                got = ws.receive_json()
            assert got == {"type": "used", "ref": cue["ref"], "used": True}
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as late:
        hello = late.receive_json()
    assert cue["ref"] in hello["used"] and hello["cue"]["ref"] != cue["ref"]


def test_fans_never_get_cues_or_can_mark_used(client):
    mid = start(client, home="har", away="ngc", seed=292, autostart=False)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as fan:
        hello = fan.receive_json()
        assert "cue" not in hello
        fan.send_json({"type": "used", "ref": "anything", "used": True})
        client.post(f"/api/matches/{mid}/start")
        msgs = collect(fan)
    assert not [m for m in msgs if m["type"] in ("cue", "used")]


def test_ai_note_reaches_each_desk_in_its_language():
    """GP-5 through the live pipeline: English desk gets the note, the Spanish desk the checked translation."""
    llm = fake_llm()
    llm.responders["producer"] = lambda p: ProducerNote(text="Hyperion need a response here.")
    with TestClient(create_app(llm=llm, live_session=False)) as c:
        mid = start(c, home="har", away="ngc", seed=292, autostart=False)
        with c.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as en, \
                c.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=es") as es:
            en.receive_json(), es.receive_json()
            c.post(f"/api/matches/{mid}/start")
            got_en, got_es = collect(en), collect(es)
    on_air = {m["cue"]["ref"] for m in got_en if m["type"] == "cue" and m["cue"] and m["cue"]["state"] == "on_air"}
    notes_en = [m for m in got_en if m["type"] == "cue_note"]
    notes_es = [m for m in got_es if m["type"] == "cue_note"]
    assert notes_en and all(n["text"] == "Hyperion need a response here." and n["ref"] in on_air for n in notes_en)
    assert len({n["ref"] for n in notes_en}) == len(notes_en)  # one note per talking point, not per break
    assert notes_es and all(n["language"] == "es" and n["text"] == "Cuerpo IA" for n in notes_es)


def test_a_note_for_a_cue_that_moved_on_is_dropped():
    notes = []
    llm = FakeLLM({"producer": lambda p: ProducerNote(text="Hyperion need a response.")}, delay={"producer": 0.05})
    orch = Orchestrator("har", "ngc", "m", NAMES, [], llm=llm, critic=CRITIC, on_cue_note=lambda *a: notes.append(a))

    async def run():
        orch.offer(cand("a", 0.9, 10))
        orch.after_event(ev("foul", 10 * MIN, **FOUL))
        first = orch.producer.current.ref
        orch.offer(cand("b", 0.95, 10.1))
        orch.after_event(ev("foul", int(10.1 * MIN), 1, **FOUL))  # a better point arrives before the note does
        await orch.drain()
        return first

    first = asyncio.run(run())
    assert notes and all(ref != first for ref, _, _ in notes)
    assert any(t.agent == "producer_ai" and t.outcome == "stale" for t in orch.trace)
