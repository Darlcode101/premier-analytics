"""R-3: half-time and full-time recaps, grounded in the live match state."""
import asyncio

import pytest

from premier_analytics.agents import CriticAgent, FakeLLM, Personalised
from premier_analytics.mcp_server import MatchState
from premier_analytics.overlay import Names
from premier_analytics.recap import Recap, RecapProducer
from premier_analytics.scout import MomentScout


@pytest.fixture(scope="module")
def state(match, league):
    names = Names.from_league(league, match.meta.home_id, match.meta.away_id)
    scout = MomentScout(match.meta.home_id, match.meta.away_id, match.meta.match_id)
    st = MatchState(names=names, scout=scout)
    for e in match.events:
        st.add_moments(scout.observe(e))
    return st


@pytest.fixture(scope="module")
def critic(league):
    return CriticAgent({p.name for c in league.clubs for p in league.squad(c.id)}, {c.short_name for c in league.clubs})


def grounded_recap(state):
    snap = state.scout.engine.snapshot()
    h, a = state.names.home_id, state.names.away_id
    th, ta = snap.teams[h], snap.teams[a]
    home, away = state.names.club(h), state.names.club(a)
    return Recap(
        headline=f"{home} {snap.score[0]}-{snap.score[1]} {away}",
        summary=f"{home} had {th.shots} shots to {away}'s {ta.shots}, with {round(th.possession_pct)}% of the ball.",
        key_points=[f"{home} xG {th.xg:.2f}", f"{away} xG {ta.xg:.2f}"],
    )


def test_grounded_recap_is_accepted(state, critic):
    fake = FakeLLM({"recap": lambda p: grounded_recap(state)})
    out = asyncio.run(RecapProducer(fake, critic, state).run("full_time"))
    assert out is not None and out.headline == grounded_recap(state).headline
    assert fake.count("recap") == 1


def test_invented_numbers_trigger_one_regeneration(state, critic):
    calls = {"n": 0}

    def flaky(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return Recap(headline="Thriller", summary="An incredible 987 passes were played.", key_points=[])
        assert "rejected" in prompt and "987" in prompt
        return grounded_recap(state)

    out = asyncio.run(RecapProducer(FakeLLM({"recap": flaky}), critic, state).run("full_time"))
    assert out is not None and calls["n"] == 2


def test_gives_up_after_two_rejections(state, critic):
    bad = Recap(headline="Thriller", summary="An incredible 987 passes were played.", key_points=[])
    out = asyncio.run(RecapProducer(FakeLLM({"recap": lambda p: bad}), critic, state).run("full_time"))
    assert out is None  # the template full-time overlay stays on screen


def test_tools_are_passed_and_prompt_stays_lean(state, critic):
    sentinel = object()
    fake = FakeLLM({"recap": lambda p: grounded_recap(state)})
    asyncio.run(RecapProducer(fake, critic, state, tools=[sentinel]).run("half_time"))
    call = fake.calls[0]
    assert call.tools == [sentinel]
    assert "half-time" in call.prompt and "get_team_stats" in call.instructions


def test_without_tools_the_state_is_in_the_prompt(state, critic):
    fake = FakeLLM({"recap": lambda p: grounded_recap(state)})
    asyncio.run(RecapProducer(fake, critic, state).run("full_time"))
    prompt = fake.calls[0].prompt
    snap = state.scout.engine.snapshot()
    assert f"{snap.teams[state.names.home_id].shots}" in prompt and "key moments" in prompt.lower()


def test_recap_translation_masks_names(state, critic):
    seen = {}

    def tr(prompt):
        seen["prompt"] = prompt
        body = prompt.split("Body: ", 1)[1]
        return Personalised(headline="Resumen", body=body)

    fake = FakeLLM({"recap": lambda p: grounded_recap(state), "translator": tr})
    out = asyncio.run(RecapProducer(fake, critic, state).run("full_time", language="es"))
    home = state.names.club(state.names.home_id)
    assert home not in seen["prompt"]
    assert out.language == "es" and home in out.summary
    assert len(out.key_points) == 2
