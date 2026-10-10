"""Orchestrator: R-6 two-path overlays, A-2/A-3 handoffs, A-5 recovery, N-1 latency, P-1..P-4."""
import asyncio
import re
import time

from fixtures import AWAY, HOME, Fx
from premier_analytics.agents import CriticAgent, Explanation, FakeLLM, Personalised
from premier_analytics.orchestrator import Orchestrator
from premier_analytics.overlay import Audience, Names

NAMES = Names(
    players={"h9": "Kai Greaves", "h8": "Elias Ekwueme", "a9": "Rory Coldwell", "a4": "Ivo Varga"},
    clubs={HOME: "Northgate", AWAY: "Harbourside"}, home_id=HOME, away_id=AWAY,
)
CRITIC = CriticAgent(set(NAMES.players.values()), {"Northgate", "Harbourside", "Ironmoor"})

FAN_EN = Audience(mode="fan", language="en")
ANALYST_EN = Audience(mode="analyst", language="en")
FAN_ES = Audience(mode="fan", language="es", club_id=HOME)


def first_fact_id(prompt: str) -> str:
    return re.search(r"\[([^\]]+-f\d+)\]", prompt).group(1)


def good_explainer(prompt):
    return Explanation(headline="Greaves breaks the deadlock", why="Northgate lead 1-0", evidence=[first_fact_id(prompt)])


def personaliser(prompt):
    if "casual fan" in prompt:
        return Personalised(headline="Northgate strike first!", body="Kai Greaves gives Northgate the lead")
    return Personalised(headline="Greaves 1-0", body="Northgate lead 1-0 from their first shot")


def translator(prompt):
    return Personalised(headline="¡Golpe de Northgate!", body="Kai Greaves adelanta al Northgate")


def fake(delay=0.0, **overrides):
    responders = {"explainer": good_explainer, "personaliser": personaliser, "translator": translator}
    responders.update(overrides)
    return FakeLLM(responders, delay=delay)


def goal_events():
    fx = Fx()
    fx.kickoff(0)
    fx.pass_(3, HOME, 80, 20, 92, 34, player="h8", receiver="h9")
    s = fx.shot(5, HOME, 95, 33, outcome="goal", player="h9")
    fx.goal(5, HOME, s, 1, 0, assist="h8")
    return fx.events


def make(llm, audiences=(FAN_EN, ANALYST_EN, FAN_ES), **kw):
    return Orchestrator(HOME, AWAY, "fx", NAMES, list(audiences), llm=llm, critic=CRITIC, **kw)


async def play(orch, events):
    fast = []
    for e in events:
        fast += await orch.handle(e)
    return fast


def goal_overlays(orch, source):
    return [o for o in orch.published if o.kind == "goal" and o.source == source]


# ---------- two paths ----------

def test_fast_overlay_is_immediate_and_ai_upgrades_it():
    async def go():
        orch = make(fake(delay=0.2))
        start = time.perf_counter()
        fast = await play(orch, goal_events())
        took = time.perf_counter() - start
        assert took < 0.1, "handle() must not wait for the AI path"
        goal_fast = [o for o in fast if o.kind == "goal"]
        assert {o.audience for o in goal_fast} == {FAN_EN.key, ANALYST_EN.key, FAN_ES.key}
        assert not goal_overlays(orch, "ai")
        await orch.drain()
        ai = goal_overlays(orch, "ai")
        assert {o.id for o in ai} == {o.id for o in goal_fast}, "upgrades keep the same overlay IDs"
        assert all(o.version == 2 for o in ai)
        by_aud = {o.audience: o for o in ai}
        assert by_aud[FAN_EN.key].headline == "Northgate strike first!"
        assert by_aud[ANALYST_EN.key].headline == "Greaves 1-0"
        assert by_aud[FAN_ES.key].language == "es" and by_aud[FAN_ES.key].headline.startswith("¡")

    asyncio.run(go())


def test_upgrade_appears_on_screen_in_place():
    async def go():
        orch = make(fake(), audiences=[FAN_EN])
        await play(orch, goal_events())
        before = orch.on_screen(FAN_EN.key)
        await orch.drain()
        after = orch.on_screen(FAN_EN.key)
        assert [o.id for o in before] == [o.id for o in after]
        assert after[0].source == "ai"

    asyncio.run(go())


def test_handoff_order_in_trace():
    async def go():
        orch = make(fake())
        await play(orch, goal_events())
        await orch.drain()
        goal_id = goal_overlays(orch, "ai")[0].moment_id

        def hops(aud):
            return [
                t.agent for t in orch.trace
                if t.moment_id == goal_id and t.audience in ("*", aud.key) and t.agent != "validator"
            ]

        assert hops(FAN_EN) == ["explainer", "critic", "personaliser", "critic"]
        assert hops(FAN_ES) == ["explainer", "critic", "personaliser", "critic", "translator", "critic"]

    asyncio.run(go())


def test_explanation_shared_and_translation_only_when_needed():
    async def go():
        llm = fake()
        orch = make(llm)
        await play(orch, goal_events())
        await orch.drain()
        assert llm.count("explainer") == 1          # one explanation per moment, shared
        assert llm.count("personaliser") == 3       # one per distinct audience persona
        assert llm.count("translator") == 1         # only the Spanish audience

    asyncio.run(go())


def test_minor_moments_skip_the_ai_path():
    async def go():
        fx = Fx()
        fx.kickoff(0)
        fx.foul(10, AWAY, 30, 30, player="a4")
        fx.card(10, AWAY, "a4", "yellow")
        llm = fake()
        orch = make(llm, audiences=[ANALYST_EN])
        fast = await play(orch, fx.events)
        await orch.drain()
        assert [o.kind for o in fast] == ["yellow_card"]
        assert llm.count("explainer") == 0

    asyncio.run(go())


# ---------- failure recovery ----------

def test_late_ai_is_discarded():
    async def go():
        orch = make(fake(delay=0.3), audiences=[FAN_EN], stale_ms=100)
        await play(orch, goal_events())
        await orch.drain()
        assert not goal_overlays(orch, "ai")
        assert any(t.outcome == "stale" for t in orch.trace)
        assert orch.on_screen(FAN_EN.key)[0].source == "template"

    asyncio.run(go())


def test_critic_rejects_twice_keeps_fast_overlay():
    async def go():
        def liar(prompt):
            return Explanation(headline="Rout", why="Northgate have had 27 shots", evidence=[first_fact_id(prompt)])

        llm = fake(explainer=liar)
        orch = make(llm, audiences=[FAN_EN])
        await play(orch, goal_events())
        await orch.drain()
        assert llm.count("explainer") == 2
        assert not goal_overlays(orch, "ai")
        assert any(t.agent == "critic" and t.outcome == "rejected" for t in orch.trace)

    asyncio.run(go())


def test_critic_feedback_lets_explainer_fix_itself():
    async def go():
        calls = {"n": 0}

        def learns(prompt):
            calls["n"] += 1
            if calls["n"] == 1:
                return Explanation(headline="Rout", why="27 shots", evidence=[first_fact_id(prompt)])
            assert "rejected" in prompt and "27" in prompt
            return good_explainer(prompt)

        orch = make(fake(explainer=learns), audiences=[FAN_EN])
        await play(orch, goal_events())
        await orch.drain()
        assert goal_overlays(orch, "ai")

    asyncio.run(go())


def test_model_outage_never_blocks_the_stream():
    async def go():
        def down(prompt):
            return RuntimeError("model unavailable")

        llm = fake(explainer=down)
        orch = make(llm)
        fast = await play(orch, goal_events())
        await orch.drain()  # must not raise
        assert [o for o in fast if o.kind == "goal"]
        assert not goal_overlays(orch, "ai")
        assert any(t.outcome == "error" for t in orch.trace)

    asyncio.run(go())


def test_runs_without_any_model():
    async def go():
        orch = make(None)
        fast = await play(orch, goal_events())
        await orch.drain()
        assert [o for o in fast if o.kind == "goal"]
        assert orch.trace == []

    asyncio.run(go())


def test_fan_output_with_jargon_is_rejected():
    async def go():
        def nerdy(prompt):
            return Personalised(headline="Greaves 1-0", body="Northgate's xG climbs")

        orch = make(fake(personaliser=nerdy), audiences=[FAN_EN])
        await play(orch, goal_events())
        await orch.drain()
        assert not goal_overlays(orch, "ai")

    asyncio.run(go())


def test_recaps_at_half_time_once_per_language():
    from premier_analytics.recap import Recap

    async def go():
        def recap(prompt):
            return Recap(headline="Northgate 1-0 Harbourside", summary="Kai Greaves scored the only goal.", key_points=[])

        llm = fake(recap=recap)
        orch = make(llm, recaps=True)
        events = goal_events()
        fx = Fx()
        fx.events = list(events)
        fx.add("period_end", 46 * 60, score_home=1, score_away=0)
        await play(orch, fx.events)
        await orch.drain()
        assert llm.count("recap") == 1                       # written once in English...
        assert sorted(r.language for r in orch.recaps) == ["en", "es"]  # ...then localised
        assert all(r.kind == "half_time" for r in orch.recaps)
        assert any(t.agent == "recap" and t.outcome == "ok" for t in orch.trace)

    asyncio.run(go())


def test_match_state_tracks_moments_for_mcp():
    async def go():
        orch = make(None)
        await play(orch, goal_events())
        assert any(m.kind == "goal" for m in orch.state.moments)

    asyncio.run(go())


def test_audiences_can_join_and_leave():
    async def go():
        llm = fake()
        orch = make(llm, audiences=[])
        orch.add_audience(FAN_EN)
        orch.add_audience(FAN_EN)  # idempotent
        assert [a.key for a in orch.audiences] == [FAN_EN.key]
        await play(orch, goal_events())
        await orch.drain()
        assert goal_overlays(orch, "ai")
        orch.remove_audience(FAN_EN.key)
        assert orch.audiences == []
        assert FAN_EN.key not in orch.schedulers

    asyncio.run(go())


def test_ai_budget_caps_distinct_personas():
    """Beyond max_ai_audiences, new audiences still get fast overlays but no AI work (N-2)."""
    async def go():
        llm = fake()
        extra = Audience(mode="fan", language="en", club_id=AWAY)
        orch = make(llm, audiences=[FAN_EN, ANALYST_EN, extra], max_ai_audiences=2)
        fast = await play(orch, goal_events())
        await orch.drain()
        assert {o.audience for o in fast if o.kind == "goal"} == {FAN_EN.key, ANALYST_EN.key, extra.key}
        assert {o.audience for o in goal_overlays(orch, "ai")} == {FAN_EN.key, ANALYST_EN.key}

    asyncio.run(go())


def test_drain_does_not_spin_on_finished_tasks():
    """Regression: drain() used to busy-loop forever when every task had finished but the
    done-callbacks that remove them had not run yet, freezing the whole server at full time."""
    async def go():
        orch = make(None)

        async def noop():
            return None

        done = asyncio.ensure_future(noop())
        await done
        orch._tasks.add(done)  # finished, but nothing will remove it
        await asyncio.wait_for(orch.drain(), timeout=1)

    asyncio.run(go())
