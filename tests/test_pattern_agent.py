"""PA-4, PA-6, PA-7, PA-8: Pattern Analyst wording, the agent, and how notes reach the desk and the fan app."""
import asyncio
import re

import pytest
from fastapi.testclient import TestClient

from premier_analytics.agents import CriticAgent, FakeLLM
from premier_analytics.app import create_app
from premier_analytics.overlay import Names
from premier_analytics.pattern_agent import (
    AlertGate, PatternAnalystAgent, PatternNote, PatternNotes, fan_line, pattern_text,
)
from premier_analytics.patterns import Pattern
from premier_analytics.languages import LANGS

from test_app import collect, start

NAMES = Names(home_id="har", away_id="ngc", clubs={"har": "Hyperion", "ngc": "Selene"},
              players={"har-08": "Ezra Jovanovic"})
CRITIC = CriticAgent({"Ezra Jovanovic", "Kai Greaves"}, {"Hyperion", "Selene"})


def pat(kind, scope="match", value="left", team="har", **numbers):
    base = {"count": 9, "total": 14, "share_pct": 64}
    if scope == "season":
        base = {"season_share_pct": 57, "today_count": 9, "today_total": 14, "league_share_pct": 33}
    base.update(numbers)
    return Pattern(id=f"{team}:{kind}:{scope}:{value}", team_id=team, kind=kind, scope=scope, value=value,
                   count=9, total=14, share=9 / 14, p_value=0.001, numbers=base)


ALL = [
    pat("flank", opponent_side="right"), pat("switch", "second_half", value="right", first_half_channel="left"),
    pat("high_regains", value="attacking"), pat("long_shots", value="outside_box"), pat("hub", value="har-08"),
    pat("counters", value="counter", seconds=15), pat("unusual", season_share_pct=57),
    pat("flank", "season"), pat("high_regains", "season", "attacking"), pat("long_shots", "season", "outside_box"),
    pat("playmaker", "season", "har-08"),
]


@pytest.mark.parametrize("language", LANGS)
def test_every_pattern_has_wording_in_every_language(language):
    for p in ALL:
        text = pattern_text(p, NAMES, language)
        assert text and "{" not in text and "_" not in text, (p.kind, p.scope, text)
        numbers = {str(v) for v in p.numbers.values() if isinstance(v, int)}
        assert set(re.findall(r"\d+", text)) <= numbers, (p.kind, text)
        if p.value == "har-08":
            assert "Ezra Jovanovic" in text


@pytest.mark.parametrize("language", LANGS)
def test_fan_lines_are_plain(language):
    for p in ALL:
        line = fan_line(p, NAMES, language)
        if line is not None:
            assert not re.search(r"\d", line) and "{" not in line, line
            assert not re.search(r"\b(xG|PPDA|tilt)\b", line, re.I)


def test_agent_writes_notes_and_the_critic_checks_them():
    def write(prompt):
        assert "[har:flank:match:left]" in prompt
        return PatternNotes(notes=[PatternNote(pattern_id="har:flank:match:left",
                                               text="Hyperion keep attacking down the left: 9 of 14 attacks.")])
    agent = PatternAnalystAgent(FakeLLM({"pattern_analyst": write}), CRITIC)
    notes = asyncio.run(agent.run([ALL[0], ALL[2]], NAMES))
    assert [n.pattern_id for n in notes] == ["har:flank:match:left"]


def test_invented_numbers_fall_back_to_the_plain_wording():
    def liar(prompt):
        return PatternNotes(notes=[PatternNote(pattern_id="har:flank:match:left", text="Hyperion: 12 of 13 down the left.")])
    agent = PatternAnalystAgent(FakeLLM({"pattern_analyst": liar}), CRITIC)
    notes = asyncio.run(agent.run([ALL[0]], NAMES))
    assert notes[0].text == pattern_text(ALL[0], NAMES, "en")


def test_unknown_pattern_ids_are_dropped():
    def wrong(prompt):
        return PatternNotes(notes=[PatternNote(pattern_id="made-up", text="Something.")])
    agent = PatternAnalystAgent(FakeLLM({"pattern_analyst": wrong}), CRITIC)
    notes = asyncio.run(agent.run([ALL[0]], NAMES))
    assert [n.pattern_id for n in notes] == ["har:flank:match:left"]  # plain wording for the patterns it skipped


def test_alerts_need_two_checks_in_a_row_and_fire_once():
    gate = AlertGate()
    assert gate.update({"a"}) == set()          # first sighting: not yet
    assert gate.update({"a", "b"}) == {"a"}     # held at two checks: alert
    assert gate.update({"a", "b"}) == {"b"}     # b now held twice; a already alerted
    assert gate.update({"a"}) == set()
    assert gate.update(set()) == set()
    assert gate.update({"b"}) == set() and gate.update({"b"}) == set()  # never twice for the same pattern


# ---------- through the app (AI off: PA-8) ----------

@pytest.fixture
def client():
    with TestClient(create_app(llm=None, live_session=False)) as c:
        yield c


def test_desk_and_fan_receive_patterns_with_the_ai_off(client):
    mid = start(client, home="har", away="sil", seed=42, autostart=False)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as desk, \
            client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=es") as fan:
        desk.receive_json(), fan.receive_json()
        client.post(f"/api/matches/{mid}/start")
        d, f = collect(desk), collect(fan)
    desk_msgs = [m for m in d if m["type"] == "patterns"]
    assert desk_msgs and all(m["language"] == "en" for m in desk_msgs)
    final = desk_msgs[-1]
    assert final["notes"] and all(n["text"] and n["team_id"] in ("har", "sil") for n in final["notes"])
    assert any(n["scope"] == "season" for n in final["notes"])  # known styles always available
    fan_msgs = [m for m in f if m["type"] == "patterns"]
    assert fan_msgs and fan_msgs[-1]["language"] == "es" and fan_msgs[-1]["fan_lines"]
    stats = [m for m in d if m["type"] == "stats"][-1]
    assert set(stats["shape"]) == {"home", "away"} and set(stats["shape"]["home"]["entries"]) == {"left", "centre", "right"}


def test_late_joiner_gets_the_latest_patterns(client):
    mid = start(client, home="har", away="sil", seed=42)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst") as ws:
        collect(ws)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst") as ws:
        hello = ws.receive_json()
    assert hello["patterns"] and hello["patterns"]["notes"]


def test_a_known_style_that_today_contradicts_cannot_be_called_confirmed():
    agent = PatternAnalystAgent(FakeLLM({}), CRITIC)
    quiet = pat("playmaker", "season", "har-08", season_share_pct=28, today_count=2, today_total=12)
    bad = "Ezra Jovanovic remains Hyperion's key playmaker this season, directing 2 of 12 passes today."
    assert any("today" in p for p in agent.problems(bad, quiet, NAMES))
    good = "Ezra Jovanovic, usually Hyperion's playmaker this season, is quiet today: 2 of 12."
    assert agent.problems(good, quiet, NAMES) == []
    busy = pat("playmaker", "season", "har-08", season_share_pct=28, today_count=5, today_total=12)
    assert agent.problems("Ezra Jovanovic remains Hyperion's playmaker this season: 5 of 12 today.", busy, NAMES) == []
