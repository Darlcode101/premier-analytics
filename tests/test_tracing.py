"""A-7: every AI moment is one trace, with a span per agent step (OpenTelemetry, GenAI conventions)."""
import asyncio

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from test_orchestrator import CRITIC, FAN_EN, FAN_ES, NAMES, fake, goal_events, play
from fixtures import AWAY, HOME
from premier_analytics.agents import Explanation
from premier_analytics.orchestrator import Orchestrator

_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)


@pytest.fixture(autouse=True)
def spans():
    _exporter.clear()
    yield _exporter
    _exporter.clear()


def run(llm, audiences):
    async def go():
        orch = Orchestrator(HOME, AWAY, "fx", NAMES, audiences, llm=llm, critic=CRITIC)
        await play(orch, goal_events())
        await orch.drain()
    asyncio.run(go())


def by_name(spans, prefix):
    return [s for s in spans.get_finished_spans() if s.name.startswith(prefix)]


def test_each_moment_is_one_trace_with_agent_steps(spans):
    run(fake(), [FAN_ES])
    roots = by_name(spans, "moment goal")
    assert len(roots) == 1
    root = roots[0]
    assert root.attributes["pa.moment.kind"] == "goal"
    assert root.attributes["pa.audience"] == FAN_ES.key
    assert root.attributes["pa.outcome"] == "published"
    steps = [s for s in spans.get_finished_spans() if s.parent and s.context.trace_id == root.context.trace_id]
    agents = [s.attributes.get("gen_ai.agent.name") for s in steps if s.name.startswith("invoke_agent")]
    assert agents == ["explainer", "personaliser", "translator"]
    critics = [s for s in steps if s.name == "critic"]
    assert len(critics) == 3 and all(s.attributes["pa.critic.verdict"] == "ok" for s in critics)


def test_agent_spans_follow_genai_conventions(spans):
    run(fake(), [FAN_EN])
    span = by_name(spans, "invoke_agent explainer")[0]
    assert span.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert span.attributes["gen_ai.request.model"] == "fake"
    assert span.attributes["pa.outcome"] == "ok"


def test_rejections_and_errors_are_visible_in_the_trace(spans):
    def liar(prompt):
        import re
        fid = re.search(r"\[([^\]]+-f\d+)\]", prompt).group(1)
        return Explanation(headline="Rout", why="27 shots", evidence=[fid])

    run(fake(explainer=liar), [FAN_EN])
    critic = [s for s in by_name(spans, "critic") if s.attributes["pa.critic.verdict"] == "rejected"]
    assert critic and "27" in critic[0].attributes["pa.critic.problems"]
    root = by_name(spans, "moment goal")[0]
    assert root.attributes["pa.outcome"] == "rejected"


def test_model_outage_marks_the_span_as_error(spans):
    run(fake(explainer=lambda p: RuntimeError("down")), [FAN_EN])
    span = by_name(spans, "invoke_agent explainer")[0]
    assert span.status.status_code == trace.StatusCode.ERROR
    assert by_name(spans, "moment goal")[0].attributes["pa.outcome"] == "error"


def test_tracing_is_harmless_without_a_configured_exporter():
    from premier_analytics import telemetry

    assert telemetry.configure(None) is False  # no connection string: nothing configured, nothing raised


def test_recaps_are_traced(spans):
    from fixtures import Fx
    from premier_analytics.recap import RecapDraft

    async def go():
        llm = fake(recap=lambda p: RecapDraft(headline="Northgate 1-0 Harbourside", summary="One goal.", key_points=[]))
        orch = Orchestrator(HOME, AWAY, "fx", NAMES, [FAN_EN], llm=llm, critic=CRITIC, recaps=True)
        fx = Fx()
        fx.events = list(goal_events())
        fx.add("period_end", 46 * 60, score_home=1, score_away=0)
        await play(orch, fx.events)
        await orch.drain()
    asyncio.run(go())
    recap = by_name(spans, "recap half_time")[0]
    assert recap.attributes["gen_ai.agent.name"] == "recap" and recap.attributes["pa.outcome"] == "published"
