"""Agents: E-1/E-2 (grounded explanations), A-5 (failure recovery), A-6 (critic), P-1/P-4."""
import asyncio

import pytest

from fixtures import AWAY, HOME, Fx
from premier_analytics.agents import (
    AllModelsFailed, CriticAgent, Explanation, ExplainerAgent, FakeLLM, PersonaliserAgent, Personalised,
    ResilientLLM, TranslatorAgent, describe_facts,
)
from premier_analytics.overlay import Audience, Names
from premier_analytics.scout import MomentScout

NAMES = Names(
    players={"h9": "Kai Greaves", "h8": "Elias Ekwueme", "a9": "Rory Coldwell", "a4": "Ivo Varga"},
    clubs={HOME: "Northgate", AWAY: "Harbourside"}, home_id=HOME, away_id=AWAY,
)
LEAGUE_PLAYERS = set(NAMES.players.values()) | {"Hugo Marchetti"}  # someone not in this moment


def goal_moment():
    fx = Fx()
    fx.kickoff(0)
    fx.pass_(3, HOME, 80, 20, 92, 34, player="h8", receiver="h9")
    s = fx.shot(5, HOME, 95, 33, outcome="goal", player="h9")
    fx.goal(5, HOME, s, 1, 0, assist="h8")
    scout = MomentScout(HOME, AWAY, match_id="fx")
    return next(m for e in fx.events for m in scout.observe(e) if m.kind == "goal")


def facts(m):
    return {f.label: f for f in m.facts}


# ---------- prompt context ----------

def test_describe_facts_resolves_names_and_keeps_ids():
    m = goal_moment()
    text = describe_facts(m, NAMES)
    for f in m.facts:
        assert f"[{f.id}]" in text
    assert "Kai Greaves" in text and "h9" not in text.replace("[", " ").split()


# ---------- critic (A-6, E-2) ----------

critic = CriticAgent(league_player_names=LEAGUE_PLAYERS, league_club_names={"Northgate", "Harbourside", "Ironmoor"})


def test_critic_accepts_grounded_text():
    m = goal_moment()
    xg = facts(m)["shot_xg"].value
    ok = critic.review(f"Greaves makes it 1-0", f"Kai Greaves finishes a {xg} xG chance for Northgate", m, NAMES,
                       evidence=[facts(m)["shot_xg"].id])
    assert ok.ok, ok.problems


def test_critic_accepts_number_variants():
    m = goal_moment()
    xg = facts(m)["shot_xg"].value
    pct = round(xg * 100)
    ok = critic.review("Goal", f"A {pct}% chance, taken in minute 1", m, NAMES, evidence=[m.facts[0].id])
    assert ok.ok, ok.problems


def test_critic_rejects_invented_number():
    m = goal_moment()
    v = critic.review("Goal", "Northgate have had 27 shots", m, NAMES, evidence=[m.facts[0].id])
    assert not v.ok and any("27" in p for p in v.problems)


def test_critic_rejects_player_not_in_moment():
    m = goal_moment()
    v = critic.review("Goal", "Hugo Marchetti will be furious", m, NAMES, evidence=[m.facts[0].id])
    assert not v.ok and any("Hugo Marchetti" in p for p in v.problems)


def test_critic_rejects_club_not_in_match():
    m = goal_moment()
    v = critic.review("Goal", "Ironmoor fans will enjoy this", m, NAMES, evidence=[m.facts[0].id])
    assert not v.ok


def test_critic_requires_valid_evidence():
    m = goal_moment()
    assert not critic.review("Goal", "Greaves scores", m, NAMES, evidence=[]).ok
    assert not critic.review("Goal", "Greaves scores", m, NAMES, evidence=["fx-mo9999-f0"]).ok


def test_critic_normalises_arabic_and_spanish_digits():
    m = goal_moment()
    xg = facts(m)["shot_xg"].value
    arabic = str(xg).translate(str.maketrans("0123456789.", "٠١٢٣٤٥٦٧٨٩٫"))
    assert critic.review("هدف", f"فرصة {arabic}", m, NAMES, evidence=[m.facts[0].id]).ok
    assert critic.review("Gol", f"ocasión de {str(xg).replace('.', ',')} xG", m, NAMES, evidence=[m.facts[0].id]).ok
    assert not critic.review("هدف", "٢٧ تسديدة", m, NAMES, evidence=[m.facts[0].id]).ok


def test_critic_blocks_jargon_for_fans_only():
    m = goal_moment()
    fan = Audience(mode="fan")
    analyst = Audience(mode="analyst")
    text = "Northgate's xG keeps climbing"
    assert not critic.review("Goal", text, m, NAMES, evidence=[m.facts[0].id], audience=fan).ok
    assert critic.review("Goal", text, m, NAMES, evidence=[m.facts[0].id], audience=analyst).ok


def test_critic_enforces_lengths():
    m = goal_moment()
    assert not critic.review("x" * 61, "ok", m, NAMES, evidence=[m.facts[0].id]).ok
    assert not critic.review("ok", "x" * 181, m, NAMES, evidence=[m.facts[0].id]).ok


# ---------- explainer / personaliser / translator against a fake model ----------

def test_explainer_sends_facts_and_returns_structured_output():
    m = goal_moment()
    fake = FakeLLM({"explainer": lambda p: Explanation(headline="Greaves breaks the deadlock",
                                                       why="First goal of the game", evidence=[m.facts[0].id])})
    out = asyncio.run(ExplainerAgent(fake).run(m, NAMES))
    assert out.headline == "Greaves breaks the deadlock"
    prompt = fake.calls[0].prompt
    assert "Kai Greaves" in prompt and m.facts[0].id in prompt


def test_personaliser_prompt_reflects_audience():
    m = goal_moment()
    fake = FakeLLM({"personaliser": lambda p: Personalised(headline="h", body="b")})
    agent = PersonaliserAgent(fake)
    exp = Explanation(headline="Greaves scores", why="First goal", evidence=[m.facts[0].id])
    asyncio.run(agent.run(exp, m, NAMES, Audience(mode="fan", club_id=AWAY, player_id="h9")))
    asyncio.run(agent.run(exp, m, NAMES, Audience(mode="analyst")))
    fan_prompt, analyst_prompt = fake.calls[0].prompt, fake.calls[1].prompt
    assert "casual fan" in fan_prompt and "Harbourside" in fan_prompt and "Kai Greaves" in fan_prompt
    assert "analyst" in analyst_prompt


def test_translator_targets_requested_language():
    fake = FakeLLM({"translator": lambda p: Personalised(headline="¡Gol!", body="Greaves marca")})
    out = asyncio.run(TranslatorAgent(fake).run(Personalised(headline="Goal!", body="Greaves scores"), "es"))
    assert out.headline == "¡Gol!"
    assert "Spanish" in fake.calls[0].prompt


# ---------- resilience (A-5) ----------

class Boom(Exception):
    pass


def test_resilient_uses_fallback_after_timeout():
    slow = FakeLLM({"explainer": lambda p: Personalised(headline="slow", body="")}, delay=1.0, name="primary")
    fast = FakeLLM({"explainer": lambda p: Personalised(headline="fallback", body="")}, name="fallback")
    llm = ResilientLLM(slow, fast, timeout_s=0.05, retries=0)
    res = asyncio.run(llm.generate("explainer", "i", "p", Personalised))
    assert res.value.headline == "fallback" and res.model == "fallback"
    assert [a.outcome for a in res.attempts] == ["timeout", "ok"]


def test_resilient_retries_primary_once():
    calls = {"n": 0}

    def flaky(p):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Boom("429")
        return Personalised(headline="second try", body="")

    primary = FakeLLM({"explainer": flaky}, name="primary")
    fallback = FakeLLM({"explainer": lambda p: Personalised(headline="fallback", body="")}, name="fallback")
    llm = ResilientLLM(primary, fallback, timeout_s=1, retries=1)
    res = asyncio.run(llm.generate("explainer", "i", "p", Personalised))
    assert res.value.headline == "second try" and res.model == "primary"


def test_resilient_raises_when_everything_fails():
    def down(p):
        raise Boom("down")

    llm = ResilientLLM(FakeLLM({"explainer": down}), FakeLLM({"explainer": down}), timeout_s=1, retries=1)
    with pytest.raises(AllModelsFailed) as failed:
        asyncio.run(llm.generate("explainer", "i", "p", Personalised))
    assert len(failed.value.attempts) == 3  # primary, primary retry, fallback


# ---------- fixes from the first live run ----------

def test_translator_never_sees_names():
    """Names are masked before translation and restored after, so they can't be transliterated."""
    seen = {}

    def tr(prompt):
        seen["prompt"] = prompt
        return Personalised(headline="⟦A⟧ marca", body="⟦A⟧ adelanta al ⟦B⟧")

    fake = FakeLLM({"translator": tr})
    out = asyncio.run(TranslatorAgent(fake, names=["Kai Greaves", "Northgate"]).run(
        Personalised(headline="Kai Greaves scores", body="Kai Greaves puts Northgate ahead"), "es"))
    assert "Kai Greaves" not in seen["prompt"] and "Northgate" not in seen["prompt"]
    assert out.headline == "Kai Greaves marca"
    assert out.body == "Kai Greaves adelanta al Northgate"


def test_critic_rejects_leftover_name_tokens():
    m = goal_moment()
    v = critic.review("⟦C⟧ marca", "gol", m, NAMES, evidence=[m.facts[0].id])
    assert not v.ok


def test_focus_player_only_allowed_when_involved():
    m = goal_moment()  # involves h9 (scorer) and h8 (assist), not a4
    follower = Audience(mode="fan", player_id="a4")
    v = critic.review("Goal", "Ivo Varga watches on as Northgate score", m, NAMES, audience=follower)
    assert not v.ok


def test_critic_rejects_truncated_rounding():
    m = goal_moment()
    xg = facts(m)["team_xg"].value
    if xg >= 1 and round(xg) != int(xg):
        assert not critic.review("Goal", f"{int(xg)} xG so far", m, NAMES, evidence=[m.facts[0].id]).ok
    pct_fact = 40.6
    from premier_analytics.agents import _number_forms
    assert "41" in _number_forms(pct_fact) and "40" not in _number_forms(pct_fact)


def equaliser_moment():
    fx = Fx()
    fx.kickoff(0, AWAY, player="a9")
    s1 = fx.shot(60, AWAY, 96, 34, outcome="goal", player="a9")
    fx.goal(60, AWAY, s1, 0, 1)
    fx.kickoff(120, HOME)
    s2 = fx.shot(200, HOME, 96, 34, outcome="goal", player="h9")
    fx.goal(200, HOME, s2, 1, 1)
    scout = MomentScout(HOME, AWAY, match_id="fx")
    return [m for e in fx.events for m in scout.observe(e) if m.kind == "goal"][1]


@pytest.mark.parametrize("text", ["Greaves gives Northgate the lead", "Greaves breaks the deadlock",
                                  "Northgate go ahead through Greaves", "Greaves puts Northgate in front"])
def test_critic_rejects_text_contradicting_goal_context(text):
    m = equaliser_moment()
    assert not critic.review("Goal", text, m, NAMES, evidence=[m.facts[0].id]).ok


def test_critic_accepts_correct_goal_context():
    m = equaliser_moment()
    assert critic.review("Greaves levels it", "Kai Greaves equalises for Northgate", m, NAMES,
                         evidence=[m.facts[0].id]).ok


def test_facts_are_described_with_their_time_window():
    m = goal_moment()
    text = describe_facts(m, NAMES)
    assert "in the match so far" in text
    assert "goal context" in text.lower()


def test_translator_masks_surnames_too():
    seen = {}

    def tr(prompt):
        seen["prompt"] = prompt
        return Personalised(headline="⟦A⟧ marca", body="gol")

    fake = FakeLLM({"translator": tr})
    out = asyncio.run(TranslatorAgent(fake, names=["Kai Greaves", "Northgate"]).run(
        Personalised(headline="Greaves scores", body="gol"), "ar"))
    assert "Greaves" not in seen["prompt"]
    assert out.headline == "Greaves marca"


def test_translator_masks_first_names_too():
    seen = {}

    def tr(prompt):
        seen["prompt"] = prompt
        return Personalised(headline="⟦A⟧", body="")

    fake = FakeLLM({"translator": tr})
    asyncio.run(TranslatorAgent(fake, names=["Felix Achterberg"]).run(Personalised(headline="Felix!", body=""), "ar"))
    assert "Felix" not in seen["prompt"]


def test_agent_framework_llm_builds_agents_without_network():
    """Regression: a refactor once moved the agent cache out of __init__, breaking every live call.
    Builds the real class and its agents (no request is sent)."""
    from premier_analytics.agents import AgentFrameworkLLM

    llm = AgentFrameworkLLM("gpt-4.1-mini", "https://example.services.ai.azure.com/api/projects/p", api_key="k")
    first = llm._agent("explainer", "instructions")
    assert llm._agent("explainer", "instructions") is first
