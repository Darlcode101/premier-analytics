"""AM-1..AM-3: the desk's ask box answers questions about the live match from the match tools, grounded."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from premier_analytics.agents import CriticAgent, FakeLLM
from premier_analytics.app import create_app
from premier_analytics.context import ResearcherAgent
from premier_analytics.demo_llm import scripted_search
from premier_analytics.generator import generate_match
from premier_analytics.match_analyst import AskRoute, MatchAnalyst, MatchAnswer, MatchTools
from premier_analytics.mcp_server import MatchState
from premier_analytics.overlay import Names
from premier_analytics.scout import MomentScout

from test_app import start


@pytest.fixture(scope="module")
def demo(league):
    """Seed 292 played to full time: Kowalczyk on at 76', wins and scores a 90+9' penalty."""
    m = generate_match("har", "ngc", 292, league)
    names = Names.from_league(league, "har", "ngc")
    scout = MomentScout("har", "ngc", m.meta.match_id)
    state = MatchState(names=names, scout=scout)
    for e in m.events:
        state.record(e)  # snapshot before the event, as the orchestrator does
        state.add_moments(scout.observe(e))
    return m, names, state


def pid(names, name):
    return next(p for p, n in names.players.items() if n == name)


# ---------- the tools ----------

def test_player_stats_since_a_minute_match_the_events(demo):
    m, names, state = demo
    tools = MatchTools(state)
    for player in ("Reuben Northcott", "Zane Kowalczyk", "Ezra Jovanovic"):
        p = pid(names, player)
        for since in (1, 30, 46, 60, 80):
            period = 2 if since > 45 else 1
            after = [e for e in m.events if e.player_id == p and (e.period, e.clock_ms) >= (period, (since - 1) * 60_000)]
            got = tools.get_player_stats(player, since_minute=since)
            assert got["since_minute"] == since
            assert got["shots"] == sum(e.type == "shot" for e in after), (player, since)
            assert got["goals"] == sum(e.type == "goal" for e in after), (player, since)
            assert got["passes_completed"] == sum(e.type == "pass" and e.outcome == "complete" for e in after), (player, since)
    total = tools.get_player_stats("Zane Kowalczyk")
    assert total["goals"] == 1 and "since_minute" not in total
    assert tools.get_player_stats("Zane Kowalczyk", since_minute=76)["goals"] == 1  # on at 76'


def test_team_stats_since_a_minute_match_the_events(demo):
    """'Shots in the second half?' needs team counts from a minute on, not the match total."""
    m, names, state = demo
    tools = MatchTools(state)
    for team, tid in (("Northgate", "ngc"), ("Harbourside", "har")):
        after = [e for e in m.events if e.team_id == tid and (e.period, e.clock_ms) >= (2, 45 * 60_000)]
        got = tools.get_team_stats(team, since_minute=46)
        assert got["since_minute"] == 46 and got["team"] == team
        assert got["shots"] == sum(e.type == "shot" for e in after)
        assert got["goals"] == sum(e.type == "goal" for e in after)
    assert "possession_pct" in tools.get_team_stats("Northgate")  # without since_minute: the full picture


def test_player_stats_say_when_a_substitute_came_on_or_off(demo):
    """Live check 10-17: the model guessed a sub came on at 90'. The stats now say, so it never has to guess."""
    _, _, state = demo
    tools = MatchTools(state)
    assert tools.get_player_stats("Zane Kowalczyk")["came_on"] == "76"
    assert tools.get_player_stats("Zane Kowalczyk")["went_off"] is None
    assert tools.get_player_stats("Reuben Northcott")["went_off"] == "76"
    assert tools.get_player_stats("Reuben Northcott")["came_on"] is None


def test_repeated_tool_calls_show_once_as_evidence(demo, league):
    def respond(tools, prompt, n):
        for _ in range(3):
            stats = tools["get_team_stats"]("Northgate")
        return MatchAnswer(scope="match", answer=f"Northgate have had {stats['shots']} shots.")
    analyst, _ = analyst_with(demo, league, respond)
    assert len(ask(analyst, "Northgate shots?")["evidence"]) == 1


def test_evidence_lines_show_what_lists_contain():
    from premier_analytics.match_analyst import summary
    line = summary({"tool": "get_top_players", "args": {"metric": "xg", "limit": 1},
                    "result": {"players": [{"name": "Pablo Wakefield-Ames", "team": "Northgate", "xg": 0.05}]}})
    assert line == "get_top_players(metric=xg, limit=1) → players: Pablo Wakefield-Ames, Northgate, xg 0.05"
    many = summary({"tool": "get_cards_and_subs", "args": {}, "result": {"cards": [{"player": f"P{i}"} for i in range(5)], "subs": []}})
    assert "P0; P1; P2 (+2 more)" in many and "subs: none" in many


def test_cards_and_subs_say_who_when_and_why(demo):
    _, _, state = demo
    out = MatchTools(state).get_cards_and_subs()
    cards = {(c["player"], c["card"]): c for c in out["cards"]}
    assert cards[("Leandro Ashworth", "second_yellow")]["reason"] == "tactical foul"
    assert cards[("Leandro Ashworth", "second_yellow")]["minute"] == "67"
    assert cards[("Ezra Jovanovic", "yellow")]["reason"] == "dissent"
    assert {"minute": "76", "team": "Harbourside", "on": "Zane Kowalczyk", "off": "Obi Gilchrist"} in out["subs"]


def test_unknown_names_are_errors_the_agent_can_read(demo):
    _, _, state = demo
    analyst_tools = MatchTools(state).recorded(log := [])
    by_name = {t.__name__: t for t in analyst_tools}
    out = by_name["get_player_stats"]("Nobody Atall")
    assert "error" in out and log[-1]["tool"] == "get_player_stats" and "error" in log[-1]["result"]


# ---------- the Match Analyst ----------

def analyst_with(demo, league, respond, route="match"):
    """A scripted model that really calls the tools it is given, like the Agent Framework would."""
    _, names, state = demo
    llm = FakeLLM({"ask_router": lambda p: AskRoute(scope=route)})

    def responder(prompt):
        tools = {t.__name__: t for t in llm.calls[-1].tools}
        return respond(tools, prompt, len([c for c in llm.calls if c.role == "match_analyst"]))

    llm.responders["match_analyst"] = responder
    critic = CriticAgent({p.name for c in league.clubs for p in league.squad(c.id)}, {c.short_name for c in league.clubs})
    return MatchAnalyst(llm, critic, state), llm


def ask(analyst, question="How has Kowalczyk done since he came on?", language="en"):
    return asyncio.run(analyst.ask(question, language, "90+9"))


def test_grounded_answers_show_their_evidence_and_time(demo, league):
    def respond(tools, prompt, n):
        s = tools["get_player_stats"]("Zane Kowalczyk", since_minute=76)
        return MatchAnswer(scope="match", answer=f"Zane Kowalczyk has {s['goals']} goal from {s['shots']} shots since coming on.")
    analyst, _ = analyst_with(demo, league, respond)
    res = ask(analyst)
    assert res["status"] == "ok" and res["as_of"] == "90+9"
    assert res["text"].startswith("Zane Kowalczyk has 1 goal")
    assert res["evidence"][0]["tool"] == "get_player_stats" and "Zane Kowalczyk" in res["evidence"][0]["summary"]


def test_invented_numbers_get_one_retry_then_facts_only(demo, league):
    def liar(tools, prompt, n):
        tools["get_score"]()
        return MatchAnswer(scope="match", answer="Harbourside have had 99 shots.")
    analyst, llm = analyst_with(demo, league, liar)
    res = ask(analyst, "How many shots have Harbourside had?")
    assert llm.count("match_analyst") == 2  # one retry, told what was wrong
    assert "99" in llm.calls[-1].prompt and res["status"] == "facts_only" and res["text"] == ""
    assert res["evidence"] and res["evidence"][0]["tool"] == "get_score"

    def fixes_it(tools, prompt, n):
        stats = tools["get_team_stats"]("Harbourside")
        return MatchAnswer(scope="match", answer=f"Harbourside have had {stats['shots'] if n > 1 else 99} shots.")
    analyst, llm = analyst_with(demo, league, fixes_it)
    res = ask(analyst, "How many shots have Harbourside had?")
    assert llm.count("match_analyst") == 2 and res["status"] == "ok" and "99" not in res["text"]


def test_players_not_in_the_tool_results_are_rejected(demo, league):
    def name_drop(tools, prompt, n):
        tools["get_score"]()
        return MatchAnswer(scope="match", answer="Kai Greaves is the reason.")
    analyst, _ = analyst_with(demo, league, name_drop)
    assert ask(analyst)["status"] == "facts_only"


def test_the_router_sends_real_world_questions_away_without_touching_the_tools(demo, league):
    """Live check 10-17: one agent doing both routing and answering answered a records question with the
    score. A separate Ask Router classifies first; only match questions reach the Match Analyst."""
    analyst, llm = analyst_with(demo, league, lambda t, p, n: MatchAnswer(scope="match", answer="2-1"), route="real_world")
    assert ask(analyst, "What's the Premier League record for goals in a season?")["status"] == "real_world"
    assert llm.count("match_analyst") == 0


def test_the_analyst_says_when_the_data_does_not_hold_it(demo, league):
    analyst, _ = analyst_with(demo, league, lambda t, p, n: MatchAnswer(
        scope="not_in_data", answer="Distance run isn't in this data feed."))
    assert ask(analyst, "How far has Kowalczyk run?")["status"] == "not_in_data"


def test_a_router_failure_falls_back_to_the_analyst(demo, league):
    analyst, llm = analyst_with(demo, league, lambda t, p, n: MatchAnswer(scope="match", answer="Northgate lead."))
    llm.responders["ask_router"] = lambda p: RuntimeError("router down")
    assert ask(analyst, "Who is winning?")["status"] == "ok"


# ---------- through the app ----------

def test_the_ask_box_routes_match_and_real_world_questions(league):
    llm = FakeLLM({
        "ask_router": lambda p: AskRoute(scope="real_world" if "record" in p else "match"),
        "match_analyst": lambda p: MatchAnswer(scope="match", answer="Northgate lead."),
    })
    with TestClient(create_app(llm=llm, live_session=False, researcher=ResearcherAgent(scripted_search()))) as c:
        mid = start(c, home="har", away="ngc", seed=292)
        match = c.post(f"/api/matches/{mid}/ask", json={"question": "Who is winning?"}).json()
        assert match["status"] == "ok" and match["text"] == "Northgate lead." and match["as_of"]
        web = c.post(f"/api/matches/{mid}/ask", json={"question": "What is the scoring record?"}).json()
        assert web["status"] == "ok" and web["sources"]  # answered by the Researcher, with a source


def test_without_models_the_ask_box_says_so(league):
    with TestClient(create_app(llm=None, live_session=False, researcher=None)) as c:
        mid = start(c, home="har", away="ngc", seed=292)
        assert c.post(f"/api/matches/{mid}/ask", json={"question": "Who is winning?"}).json()["status"] == "unavailable"
