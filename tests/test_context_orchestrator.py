"""CX-2, CX-4, CX-5, CX-6: context cards produced alongside the AI path, for the desk only."""
import asyncio
import re

from premier_analytics.agents import Personalised
from premier_analytics.context import ContextCard, ContextEntry, Source
from premier_analytics.overlay import Audience

from test_orchestrator import ANALYST_EN, FAN_EN, fake, goal_events, make, play

LIB = [ContextEntry(id="goals-per-match", kind="benchmark", topic="Goals per match",
                    text="The 2024/25 Premier League averaged 2.93 goals per match.", numbers=[2.93],
                    sources=[Source(url="https://example.org/pl", title="PL in numbers")], retrieved="2026-10-11",
                    tags=["goal"], translations={"es": "La Premier League 2024/25 promedió 2,93 goles por partido."})]
ANALYST_ES = Audience(mode="analyst", language="es")


def card(prompt):
    return ContextCard(entry_id="goals-per-match", text="Real PL matches averaged 2.93 goals in 2024/25.")


def run(llm, audiences, library=LIB):
    cards = []

    async def go():
        orch = make(llm, audiences, context_library=library, on_context=cards.append)
        await play(orch, goal_events())
        await orch.drain()
        return orch
    return asyncio.run(go()), cards


def test_a_goal_gets_one_context_card_for_the_desk_with_its_source():
    orch, cards = run(fake(context=card), [FAN_EN, ANALYST_EN])
    assert len(cards) == 1
    c = cards[0]
    assert c["language"] == "en" and c["entry_id"] == "goals-per-match" and "2.93" in c["text"]
    assert c["sources"][0]["url"] == "https://example.org/pl"
    assert c["moment_id"] and c["kind"] == "benchmark" and c["topic"] == "Goals per match"
    assert orch.contexts == cards


def test_fans_alone_get_no_context_cards():
    llm = fake(context=card)
    _, cards = run(llm, [FAN_EN])
    assert cards == [] and llm.count("context") == 0


def test_context_is_translated_for_spanish_analysts_and_rechecked():
    llm = fake(context=card, translator=lambda p: Personalised(headline="-", body="Los partidos reales promediaron 2,93 goles."))
    _, cards = run(llm, [ANALYST_EN, ANALYST_ES])
    by_lang = {c["language"]: c for c in cards}
    assert set(by_lang) == {"en", "es"} and "2,93" in by_lang["es"]["text"]
    assert llm.count("context") == 1  # one card per moment, shared across languages


def test_a_card_with_an_invented_number_is_retried_then_dropped():
    calls = []

    def liar(prompt):
        calls.append(prompt)
        return ContextCard(entry_id="goals-per-match", text="Real PL matches average 3.4 goals.")

    orch, cards = run(fake(context=liar), [ANALYST_EN])
    assert cards == [] and len(calls) == 2
    assert "rejected" in calls[1]
    assert any(t.agent == "critic" and t.outcome == "rejected" and "3.4" in t.detail for t in orch.trace)


def test_no_relevant_entry_means_no_model_call():
    llm = fake(context=card)
    _, cards = run(llm, [ANALYST_EN], library=[LIB[0].model_copy(update={"tags": ["red_card"]})])
    assert cards == [] and llm.count("context") == 0


def test_each_entry_is_used_once_per_match():
    from fixtures import Fx
    from test_orchestrator import HOME

    fx = Fx()
    fx.kickoff(0)
    for minute, score in ((5, (1, 0)), (30, (2, 0))):
        s = fx.shot(minute, HOME, 95, 33, outcome="goal", player="h9")
        fx.goal(minute, HOME, s, *score)
    llm = fake(context=card)
    cards = []

    async def go():
        orch = make(llm, [ANALYST_EN], context_library=LIB, on_context=cards.append)
        await play(orch, fx.events)
        await orch.drain()
    asyncio.run(go())
    assert len(cards) == 1 and llm.count("context") == 1


def test_model_failure_only_loses_the_card():
    orch, cards = run(fake(context=lambda p: RuntimeError("down")), [ANALYST_EN])
    assert cards == []
    assert any(o.source == "ai" for o in orch.published)  # the explanation still went out
    assert any(t.agent == "context" and t.outcome == "error" for t in orch.trace)


def test_context_agent_is_told_to_keep_real_and_fictional_apart():
    llm = fake(context=card)
    run(llm, [ANALYST_EN])
    instructions = next(c.instructions for c in llm.calls if c.role == "context")
    assert "never name real clubs" in instructions and "fictional" in instructions
