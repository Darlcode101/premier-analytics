"""A-4: verified match state exposed to agents as MCP tools."""
import asyncio
import json

import pytest
from mcp.client.client import Client

from premier_analytics.mcp_server import MatchState, build_server
from premier_analytics.overlay import Names
from premier_analytics.scout import MomentScout

TOOLS = {"get_score", "get_team_stats", "get_player_stats", "get_top_players", "get_key_moments"}


@pytest.fixture(scope="module")
def state(match, league):
    names = Names.from_league(league, match.meta.home_id, match.meta.away_id)
    scout = MomentScout(match.meta.home_id, match.meta.away_id, match.meta.match_id)
    st = MatchState(names=names, scout=scout)
    for e in match.events:
        st.add_moments(scout.observe(e))
    return st


def call(server, tool, args=None):
    async def go():
        async with Client(server) as client:
            res = await client.call_tool(tool, args or {})
            assert not res.is_error, res
            return json.loads(res.content[0].text)
    return asyncio.run(go())


def test_lists_all_tools(state):
    async def go():
        async with Client(build_server(state)) as client:
            return {t.name for t in (await client.list_tools()).tools}
    assert TOOLS <= asyncio.run(go())


def test_get_score_matches_engine(state, match):
    out = call(build_server(state), "get_score")
    final = match.events[-1]
    assert (out["score_home"], out["score_away"]) == (final.score_home, final.score_away)
    assert out["home"] == state.names.club(match.meta.home_id)


def test_team_stats_accept_side_or_name(state, match):
    server = build_server(state)
    by_side = call(server, "get_team_stats", {"team": "home"})
    by_name = call(server, "get_team_stats", {"team": state.names.club(match.meta.home_id)})
    assert by_side == by_name
    assert by_side["passes"] == sum(e.type == "pass" and e.team_id == match.meta.home_id for e in match.events)
    assert "window" in by_side and "momentum" in by_side["window"]


def test_player_stats_by_name(state, match):
    scorer = next(e for e in match.events if e.type == "goal")
    name = state.names.player(scorer.player_id)
    out = call(build_server(state), "get_player_stats", {"player": name})
    assert out["name"] == name and out["goals"] >= 1 and out["team"] in state.names.clubs.values()


def test_unknown_player_is_a_clear_error(state):
    async def go():
        async with Client(build_server(state)) as client:
            return await client.call_tool("get_player_stats", {"player": "Nobody Atall"})
    res = asyncio.run(go())
    assert res.is_error and "Nobody Atall" in res.content[0].text


def test_top_players(state):
    out = call(build_server(state), "get_top_players", {"metric": "passes_completed", "limit": 3})["players"]
    values = [p["passes_completed"] for p in out]
    assert len(out) == 3 and values == sorted(values, reverse=True)


def test_key_moments_filtered_and_named(state):
    out = call(build_server(state), "get_key_moments", {"min_severity": 0.9, "limit": 50})["moments"]
    assert out and all(m["severity"] >= 0.9 for m in out)
    goal = next(m for m in out if m["kind"] == "goal")
    assert goal["player"] in state.names.players.values()
    assert all(isinstance(f["value"], (int, float, str)) for f in goal["facts"])
