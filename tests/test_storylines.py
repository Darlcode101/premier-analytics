"""PS-1..PS-3: the pre-match brief, storylines and the Storyline Watcher."""
import asyncio
import re

import pytest
from fastapi.testclient import TestClient

from premier_analytics.agents import CriticAgent, FakeLLM
from premier_analytics.app import create_app
from premier_analytics.overlay import Names
from premier_analytics.scout import Fact, Moment
from premier_analytics.season import HISTORY_SEASONS, simulate_season
from premier_analytics.storylines import (
    MAX_STORYLINES, StorylineAgent, StorylineIdeas, Storylines, StorylineUpdate, WatcherAgent, build_brief, seeds,
)
from premier_analytics.languages import LANGS

from test_app import collect, start



@pytest.fixture(scope="module")
def season(league):
    return simulate_season(league, history=HISTORY_SEASONS)


@pytest.fixture(scope="module")
def names(league):
    return Names.from_league(league, "har", "ngc")


@pytest.fixture(scope="module")
def critic(league):
    return CriticAgent({p.name for c in league.clubs for p in league.squad(c.id)}, {c.short_name for c in league.clubs})


# ---------- PS-1: the brief ----------

def test_brief_facts_come_from_the_season(season, league, names):
    brief = build_brief(season, league, season.profiles(), names)
    meetings = [r for r in season.results if {r.home, r.away} == {"har", "ngc"}]
    assert [(m["home"], m["away"], m["home_goals"], m["away_goals"]) for m in brief["meetings"]] == \
        [(r.home, r.away, r.home_goals, r.away_goals) for r in meetings]
    for side, cid in (("home", "har"), ("away", "ngc")):
        watch = {w["why"]: w for w in brief[side]["players_to_watch"]}
        top = max((p for p in league.squad(cid)), key=lambda p: (season.goals[p.id], p.id))
        assert watch["top_scorer"]["player_id"] == top.id and watch["top_scorer"]["value"] == season.goals[top.id]
        assert watch["playmaker"]["player_id"] == season.profiles()[cid]["playmaker"]
        assert brief[side]["styles"] == [s for s in season.profiles()[cid]["styles"] if s["kind"] != "playmaker"]


@pytest.mark.parametrize("language", LANGS)
def test_seeds_only_use_their_own_numbers(season, league, names, language):
    out = seeds(season, league, season.profiles(), names)
    assert len(out) >= 5 and len({s.id for s in out}) == len(out)
    for s in out:
        text = s.text[language]
        assert text and "{" not in text, (s.id, text)
        assert set(re.findall(r"\d+", text)) <= s.numbers, (s.id, text, s.numbers)
        assert s.players or s.clubs


# ---------- PS-1: AI-suggested storylines ----------

def suggest(season, league, names, critic, ideas):
    agent = StorylineAgent(FakeLLM({"storylines": lambda p: ideas}), critic)
    return asyncio.run(agent.suggest(seeds(season, league, season.profiles(), names), names))


def test_grounded_suggestions_are_kept_and_others_fall_back(season, league, names, critic):
    pool = seeds(season, league, season.profiles(), names)
    scorer = next(s for s in pool if s.kind == "top_scorer")
    player = names.player(scorer.players[0])
    goals = next(iter(scorer.numbers))
    got = suggest(season, league, names, critic, StorylineIdeas(ideas=[
        {"seed_id": scorer.id, "text": f"Can {player} add to {goals} goals this season?"},
        {"seed_id": pool[0].id, "text": "A 99-point gap at the top."},      # invented number: plain seed instead
        {"seed_id": "made-up", "text": "Anything."},                          # unknown seed: dropped
    ]))
    by_seed = {s["seed_id"]: s for s in got}
    assert by_seed[scorer.id]["text"]["en"] == f"Can {player} add to {goals} goals this season?"
    assert by_seed[scorer.id]["source"] == "ai"
    assert by_seed[pool[0].id]["text"]["en"] == pool[0].text["en"] and by_seed[pool[0].id]["source"] == "plain"
    assert "made-up" not in by_seed and 3 <= len(got) <= 5


def test_gendered_pronouns_fall_back_to_the_plain_seed(season, league, names, critic):
    """Live check 10-17: 'Can Cian Wetherby extend his 11-goal tally?' Players are fictional; use names."""
    pool = seeds(season, league, season.profiles(), names)
    scorer = next(s for s in pool if s.kind == "top_scorer")
    player, goals = names.player(scorer.players[0]), next(iter(scorer.numbers))
    for text in (f"Can {player} extend his {goals}-goal tally?", f"Will {player} find her shooting boots?",
                 f"Can he add to {goals} goals?"):
        got = suggest(season, league, names, critic, StorylineIdeas(ideas=[{"seed_id": scorer.id, "text": text}]))
        assert got[0]["source"] == "plain", text
    ok = suggest(season, league, names, critic, StorylineIdeas(ideas=[
        {"seed_id": scorer.id, "text": f"Can {player} add to {goals} goals? Shepherd the theme."}]))
    assert ok[0]["source"] == "ai"  # 'he' inside other words is fine


# ---------- PS-2: picking and typing storylines ----------

def test_storylines_from_suggestions_or_typed_and_at_most_four(names):
    st = Storylines(names)
    suggestion = {"seed_id": "s1", "text": {"en": "Harbourside attack down the left"}, "players": [], "clubs": ["har"]}
    a = st.add_suggestion(suggestion)
    assert a["clubs"] == ["har"] and a["source"] == "suggested"
    b = st.add_custom("Can Kowalczyk make a difference off the bench?")
    assert [names.player(p) for p in b["players"]] == ["Zane Kowalczyk"]
    with pytest.raises(ValueError, match="player or club"):
        st.add_custom("Will it rain later?")
    st.add_custom("Northgate's defence")
    st.add_custom("Can Ashworth keep his discipline?")
    with pytest.raises(ValueError, match="4"):
        st.add_custom("Pablo Wakefield-Ames on target again?")
    assert len(st.active) == MAX_STORYLINES
    st.remove(a["id"])
    assert len(st.active) == 3


def moment(kind, severity, team="har", player=None, facts=()):
    return Moment(id=f"m-{kind}-{player}", kind=kind, severity=severity, event_id="e", clock_ms=60 * 60_000,
                  elapsed_ms=60 * 60_000, period=2, team_id=team, player_id=player,
                  facts=[Fact(id=f"f{i}", label=label, value=value, subject=None, source_event_ids=["e"])
                         for i, (label, value) in enumerate(facts)])


def test_which_moments_belong_to_which_storyline(names):
    st = Storylines(names)
    kowalczyk = next(p for p, n in names.players.items() if n == "Zane Kowalczyk")
    player_story = st.add_custom("Can Zane Kowalczyk make a difference?")
    club_story = st.add_custom("Northgate's defence")
    goal = moment("goal", 0.95, player=kowalczyk)
    sub = moment("substitution", 0.3, player=None, facts=[("player_in", kowalczyk), ("player_out", "har-06")])
    pressure = moment("pressure_spell", 0.5, team="ngc")
    small = moment("shot_on_target", 0.4, team="ngc", player="ngc-09")
    assert [s["id"] for s in st.relevant(goal)] == [player_story["id"]]
    assert [s["id"] for s in st.relevant(sub)] == [player_story["id"]]  # coming on counts
    assert [s["id"] for s in st.relevant(pressure)] == [club_story["id"]]
    assert st.relevant(small) == []  # club storylines only hear about moments that matter


# ---------- PS-3: the Watcher ----------

def watch(names, critic, text, story, m):
    agent = WatcherAgent(FakeLLM({"storyline_watcher": lambda p: StorylineUpdate(text=text)}), critic)
    return asyncio.run(agent.update(story, m, names))


def test_watcher_writes_grounded_updates_or_nothing(names, critic):
    kowalczyk = next(p for p, n in names.players.items() if n == "Zane Kowalczyk")
    story = {"id": "s1", "text": {"en": "Can Zane Kowalczyk make a difference?"}, "players": [kowalczyk], "clubs": []}
    goal = moment("goal", 0.95, player=kowalczyk, facts=[("score_home", 2), ("score_away", 1), ("minute", 100)])
    assert watch(names, critic, "Zane Kowalczyk wins it 2-1 in stoppage time.", story, goal) == \
        "Zane Kowalczyk wins it 2-1 in stoppage time."
    assert watch(names, critic, "NONE", story, goal) is None
    assert watch(names, critic, "Zane Kowalczyk's 7th goal of the season.", story, goal) is None  # invented
    assert watch(names, critic, "Kai Greaves set it up.", story, goal) is None                      # not in the facts
    assert watch(names, critic, "Zane Kowalczyk gets his goal.", story, goal) is None              # pronoun


# ---------- through the app (AI off) ----------

@pytest.fixture
def client():
    with TestClient(create_app(llm=None, live_session=False)) as c:
        yield c


def test_desk_gets_a_brief_picks_storylines_and_sees_updates(client):
    mid = start(client, home="har", away="ngc", seed=292, autostart=False)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as desk:
        hello = desk.receive_json()
        brief = hello["brief"]
        assert brief["meetings"] and brief["home"]["players_to_watch"] and 3 <= len(brief["suggestions"]) <= 5
        assert hello["storylines"] == []
        desk.send_json({"type": "storyline_add", "suggestion_id": brief["suggestions"][0]["seed_id"]})
        desk.send_json({"type": "storyline_add", "text": "Can Zane Kowalczyk make a difference off the bench?"})
        desk.send_json({"type": "storyline_add", "text": "Will it rain?"})
        client.post(f"/api/matches/{mid}/start")
        msgs = collect(desk)
    errors = [m for m in msgs if m["type"] == "storyline_error"]
    assert errors and "player or club" in errors[0]["error"]
    final = [m for m in msgs if m["type"] == "storylines"][-1]["storylines"]
    story = next(s for s in final if "Kowalczyk" in s["text"]["en"])
    assert story["updates"], story  # he comes on, wins and scores a penalty
    assert all(u["text"]["en"] and u["minute"] for u in story["updates"])
    cues = [m["cue"] for m in msgs if m["type"] == "cue" and m["cue"]]
    assert any("storyline" in c["reasons"] for c in cues)  # the Producer boosts storyline moments

    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=es") as late:
        hello = late.receive_json()
    assert len(hello["storylines"]) == 2  # shared match state


def test_fans_get_no_brief_or_storylines(client):
    mid = start(client, home="har", away="ngc", seed=292, autostart=False)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as fan:
        hello = fan.receive_json()
        assert "brief" not in hello and "storylines" not in hello
        fan.send_json({"type": "storyline_add", "text": "Can Zane Kowalczyk make a difference?"})
        client.post(f"/api/matches/{mid}/start")
        msgs = collect(fan)
    assert not [m for m in msgs if m["type"].startswith("storyline")]
