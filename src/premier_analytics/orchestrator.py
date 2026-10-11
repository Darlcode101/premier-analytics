"""Orchestrator: routes each moment to the fast path and, for big moments, the AI path.

    event -> Moment Scout -> for each audience that wants the moment:
        fast path: template overlay, validated and scheduled immediately
        AI path (background): Explainer -> Critic -> Personaliser -> Critic
                              [-> Translator -> Critic] -> Validator -> upgrade in place

Work is shared where audiences overlap: one explanation per moment, one personalisation
per persona (mode, club, player), one translation per persona and language. Any failure
on the AI path leaves the fast overlay on screen; the event stream never waits (A-5).
"""
from __future__ import annotations

import asyncio
import time

from opentelemetry.trace import StatusCode
from collections.abc import Callable
from dataclasses import dataclass

from .agents import (
    AllModelsFailed, CriticAgent, ExplainerAgent, Explanation, LLM, Personalised, PersonaliserAgent,
    TranslatorAgent,
)
from .mcp_server import MatchState
from .context import ContextAgent, ContextCard, ContextEntry, check_card
from .overlay import (
    STALE_MS, Audience, Names, Overlay, Scheduler, ValidationError, display_minute, fast_overlay, validate,
)
from .recap import Recap, RecapProducer
from .telemetry import tracer
from .schema import Event
from .scout import Moment, MomentScout

AI_KINDS = frozenset({
    "goal", "milestone", "big_chance", "woodwork", "red_card", "rocket_shot", "momentum_shift",
    "pressure_spell", "half_time", "full_time",
})

TREND_KINDS = frozenset({"momentum_shift", "pressure_spell"})
TREND_GAP_MS = 15 * 60_000


class TrendThrottle:
    """F-1: fans get at most one momentum/pressure card per team every 15 minutes, unless the other team
    has had one since (the story changed). Other moments pass straight through."""

    def __init__(self):
        self.last: tuple[str | None, int] | None = None  # (team, elapsed_ms) of the last trend card shown
        self.by_team: dict[str | None, int] = {}

    def allow(self, m: Moment) -> bool:
        if m.kind not in TREND_KINDS:
            return True
        took_over = self.last is not None and self.last[0] != m.team_id
        previous = self.by_team.get(m.team_id)
        if previous is not None and not took_over and m.elapsed_ms - previous < TREND_GAP_MS:
            return False
        self.last = (m.team_id, m.elapsed_ms)
        self.by_team[m.team_id] = m.elapsed_ms
        return True


@dataclass
class TraceEvent:
    moment_id: str
    audience: str  # "*" for work shared by every audience
    agent: str
    outcome: str   # ok | rejected | error | stale | published
    model: str | None
    ms: float
    detail: str = ""


class _Stop(Exception):
    """The AI path gave up for this moment/audience; the fast overlay stays."""

    def __init__(self, reason: str = "rejected"):
        super().__init__(reason)
        self.reason = reason  # rejected | error


class Orchestrator:
    def __init__(self, home_id: str, away_id: str, match_id: str, names: Names, audiences: list[Audience],
                 llm: LLM | None, critic: CriticAgent, stale_ms: int = STALE_MS,
                 on_overlay: Callable[[Overlay], None] | None = None, max_on_screen: int = 2,
                 recaps: bool = False, recap_tools: list | None = None, recap_llm: LLM | None = None,
                 on_recap: Callable[[Recap], None] | None = None, max_ai_audiences: int | None = None,
                 on_trace: Callable[[TraceEvent], None] | None = None,
                 context_library: list[ContextEntry] | None = None, on_context: Callable[[dict], None] | None = None):
        self.names = names
        self.audiences: list[Audience] = []
        self.max_ai_audiences = max_ai_audiences
        self.max_on_screen = max_on_screen
        self.llm = llm
        self.critic = critic
        self.stale_ms = stale_ms
        self.on_overlay = on_overlay
        self.scout = MomentScout(home_id, away_id, match_id)
        self.state = MatchState(names=names, scout=self.scout)
        self.on_recap = on_recap
        self.on_trace = on_trace
        self.recaps: list[Recap] = []
        self.recap_producer = None
        if recaps and llm is not None:
            # Recaps may use a slower, stronger model; translation stays on the fast live model.
            self.recap_producer = RecapProducer(
                recap_llm or llm, critic, self.state, tools=recap_tools,
                translator=TranslatorAgent(llm, names=list(names.players.values()) + list(names.clubs.values())),
            )
        self.schedulers: dict[str, Scheduler] = {}
        self._throttles: dict[str, TrendThrottle] = {}
        self._visible: dict[str, set[str]] = {}
        for a in audiences:
            self.add_audience(a)
        self.published: list[Overlay] = []
        self.trace: list[TraceEvent] = []
        self.match_now = 0
        self._tasks: set[asyncio.Task] = set()
        self._explanations: dict[str, asyncio.Task] = {}
        self._personas: dict[tuple, asyncio.Task] = {}
        self._translations: dict[tuple, asyncio.Task] = {}
        # Real-world context cards for analyst audiences (CX-2): one card per moment, each entry once per match.
        self.context_agent = ContextAgent(llm, context_library) if llm is not None and context_library else None
        self.on_context = on_context
        self.contexts: list[dict] = []
        self._context_cards: dict[str, asyncio.Task] = {}
        self._context_used: set[str] = set()
        if llm is not None:
            self.explainer = ExplainerAgent(llm)
            self.personaliser = PersonaliserAgent(llm)
            self.translator = TranslatorAgent(llm, names=list(names.players.values()) + list(names.clubs.values()))

    # ---------- public ----------

    async def handle(self, e: Event) -> list[Overlay]:
        """Process one event. Returns fast-path overlays at once; AI work continues in the background."""
        self.match_now = e.elapsed_ms
        fast: list[Overlay] = []
        moments = self.scout.observe(e)
        self.state.add_moments(moments)
        for m in moments:
            if self.recap_producer is not None and m.kind in ("half_time", "full_time"):
                self._spawn(self._recap(m))
            for a in self.audiences:
                if not self._decide(a, m):
                    continue
                o = validate(fast_overlay(m, a, self.names), m, now_elapsed_ms=e.elapsed_ms)
                self._publish(o)
                fast.append(o)
                if m.kind in AI_KINDS and self.ai_enabled_for(a):
                    self._spawn(self._enrich(m, a, o, time.perf_counter()))
            if self.context_agent is not None and m.kind in AI_KINDS:
                languages = {a.language for a in self.audiences
                             if a.mode == "analyst" and m.id in self._visible.get(a.key, ()) and self.ai_enabled_for(a)}
                if languages and self.context_agent.candidates(m, self._context_used):
                    for language in sorted(languages):
                        self._spawn(self._context(m, language))
        await asyncio.sleep(0)  # let background work start
        return fast

    def add_audience(self, a: Audience) -> None:
        if a.key not in self.schedulers:
            self.audiences.append(a)
            self.schedulers[a.key] = Scheduler(max_on_screen=self.max_on_screen)
            self._throttles[a.key] = TrendThrottle()
            self._visible[a.key] = set()
            for m in self.state.moments:  # a late joiner sees what it would have seen from kick-off
                self._decide(a, m)

    def remove_audience(self, key: str) -> None:
        self.audiences = [a for a in self.audiences if a.key != key]
        self.schedulers.pop(key, None)
        self._throttles.pop(key, None)
        self._visible.pop(key, None)

    def _decide(self, a: Audience, m: Moment) -> bool:
        """Does this audience get this moment? Decided once per moment, so live and backfill agree."""
        show = a.wants(m) and (a.mode != "fan" or self._throttles[a.key].allow(m))
        if show:
            self._visible[a.key].add(m.id)
        return show

    def visible(self, a: Audience) -> list[Moment]:
        """The moments this audience has been shown, in order (for backfill)."""
        shown = self._visible.get(a.key, set())
        return [m for m in self.state.moments if m.id in shown]

    def ai_enabled_for(self, a: Audience) -> bool:
        if self.llm is None:
            return False
        if self.max_ai_audiences is None:
            return True
        return [x.key for x in self.audiences].index(a.key) < self.max_ai_audiences

    async def drain(self) -> None:
        """Wait for all in-flight AI work (used at full time and in tests)."""
        # Only wait on unfinished tasks: awaiting already-finished ones never yields to the event
        # loop, so the callbacks that remove them would never run and this would spin forever.
        while pending := [t for t in self._tasks if not t.done()]:
            await asyncio.gather(*pending, return_exceptions=True)

    def on_screen(self, audience_key: str) -> list[Overlay]:
        scheduler = self.schedulers.get(audience_key)
        return scheduler.on_screen(self.match_now) if scheduler else []

    # ---------- internals ----------

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _recap(self, m: Moment) -> None:
        for mode, language in sorted({(a.mode, a.language) for a in self.audiences}):
            start = time.perf_counter()
            with tracer.start_as_current_span(f"recap {m.kind}", attributes={
                "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "recap", "pa.language": language, "pa.mode": mode,
            }) as span:
                try:
                    recap = await self.recap_producer.run(m.kind, language, mode=mode)
                except Exception as err:  # recaps are best-effort; the template overlay already covers HT/FT
                    span.set_status(StatusCode.ERROR, repr(err)[:200])
                    span.set_attribute("pa.outcome", "error")
                    self._record(m, language, "recap", "error", detail=repr(err)[:200])
                    continue
                span.set_attribute("pa.outcome", "rejected" if recap is None else "published")
            ms = (time.perf_counter() - start) * 1000
            if recap is None:
                self._record(m, language, "recap", "rejected", ms=ms)
                continue
            self._record(m, language, "recap", "ok", recap.model, ms)
            self.recaps.append(recap)
            if self.on_recap:
                self.on_recap(recap)

    async def _context_card(self, m: Moment) -> tuple[ContextCard, ContextEntry]:
        feedback = ""
        for _ in range(2):
            card = await self._call(m, "*", "context",
                                    self.context_agent.run_full(m, self.names, self._context_used, feedback))
            entry = self.context_agent.by_id.get(card.entry_id)
            start = time.perf_counter()
            problems = check_card(card, entry, m, self.names)
            if entry is not None and entry.id in self._context_used:  # another moment took it meanwhile
                problems.append(f"entry {entry.id} already used in this match")
            self._record(m, "*", "critic", "rejected" if problems else "ok", None,
                         (time.perf_counter() - start) * 1000, "; ".join(problems))
            if not problems:
                self._context_used.add(entry.id)
                return card, entry
            feedback = "; ".join(problems)
        raise _Stop()

    async def _context(self, m: Moment, language: str) -> None:
        """One context card for this moment in one language (CX-2, CX-5). Failures only lose the card."""
        try:
            card, entry = await self._shared(self._context_cards, m.id, lambda: self._context_card(m))
            text = card.text
            if language != "en":
                out = await self._call(m, language, "translator",
                                       self.translator.run_full(Personalised(headline="-", body=text), language))
                text = out.body
                problems = check_card(ContextCard(entry_id=entry.id, text=text), entry, m, self.names)
                self._record(m, language, "critic", "rejected" if problems else "ok", detail="; ".join(problems))
                if problems:
                    return
        except _Stop:
            return
        except Exception as err:  # never let context take anything else down
            self._record(m, language, "context", "error", detail=repr(err)[:200])
            return
        card_out = {
            "moment_id": m.id, "minute": display_minute(m), "language": language, "text": text,
            "entry_id": entry.id, "topic": entry.topic, "kind": entry.kind,
            "sources": [src.model_dump() for src in entry.sources], "origin": entry.origin,
        }
        self.contexts.append(card_out)
        if self.on_context:
            self.on_context(card_out)

    def _publish(self, o: Overlay) -> None:
        self.published.append(o)
        scheduler = self.schedulers.get(o.audience)
        if scheduler is None:  # every viewer of this audience has left
            return
        scheduler.offer(o, now=self.match_now)
        if self.on_overlay:
            self.on_overlay(o)

    def _record(self, m: Moment, audience: str, agent: str, outcome: str, model=None, ms=0.0, detail=""):
        event = TraceEvent(m.id, audience, agent, outcome, model, ms, detail)
        self.trace.append(event)
        if self.on_trace:
            self.on_trace(event)

    async def _call(self, m: Moment, audience: str, agent: str, coro):
        with tracer.start_as_current_span(f"invoke_agent {agent}", attributes={
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": agent,
            "pa.moment.id": m.id, "pa.audience": audience,
        }) as span:
            try:
                res = await coro
            except AllModelsFailed as err:
                span.set_status(StatusCode.ERROR, str(err)[:200])
                span.set_attribute("pa.outcome", "error")
                self._record(m, audience, agent, "error", detail=str(err))
                raise _Stop("error") from err
            span.set_attributes({"gen_ai.request.model": res.model, "pa.outcome": "ok", "pa.latency_ms": round(res.ms)})
            self._record(m, audience, agent, "ok", res.model, res.ms)
            return res.value

    def _check(self, m: Moment, audience: str, headline: str, body: str, evidence=None, viewer=None) -> str:
        """Run the Critic; returns '' if approved, else the feedback text."""
        start = time.perf_counter()
        with tracer.start_as_current_span("critic") as span:
            verdict = self.critic.review(headline, body, m, self.names, evidence=evidence, audience=viewer)
            span.set_attribute("pa.critic.verdict", "ok" if verdict.ok else "rejected")
            if verdict.problems:
                span.set_attribute("pa.critic.problems", "; ".join(verdict.problems)[:500])
        ms = (time.perf_counter() - start) * 1000
        outcome = "ok" if verdict.ok else "rejected"
        self._record(m, audience, "critic", outcome, None, ms, "; ".join(verdict.problems))
        return "" if verdict.ok else "; ".join(verdict.problems)

    async def _explain(self, m: Moment) -> Explanation:
        feedback = ""
        for _ in range(2):
            exp = await self._call(m, "*", "explainer", self.explainer.run_full(m, self.names, feedback))
            feedback = self._check(m, "*", exp.headline, exp.why, evidence=exp.evidence)
            if not feedback:
                return exp
        raise _Stop()

    async def _personalise(self, m: Moment, exp: Explanation, a: Audience) -> Personalised:
        feedback = ""
        for _ in range(2):
            text = await self._call(
                m, a.key, "personaliser", self.personaliser.run_full(exp, m, self.names, a, feedback),
            )
            feedback = self._check(m, a.key, text.headline, text.body, viewer=a)
            if not feedback:
                return text
        raise _Stop()

    async def _translate(self, m: Moment, text: Personalised, a: Audience) -> Personalised:
        out = await self._call(m, a.key, "translator", self.translator.run_full(text, a.language))
        if self._check(m, a.key, out.headline, out.body, viewer=a):
            raise _Stop()
        return out

    def _shared(self, cache: dict, key, factory) -> asyncio.Task:
        if key not in cache:
            cache[key] = asyncio.create_task(factory())
        return cache[key]

    async def _enrich(self, m: Moment, a: Audience, fast: Overlay, started: float) -> None:
        with tracer.start_as_current_span(f"moment {m.kind}", attributes={
            "pa.moment.id": m.id, "pa.moment.kind": m.kind, "pa.moment.severity": m.severity,
            "pa.audience": a.key, "pa.language": a.language, "pa.mode": a.mode,
        }) as span:
            outcome = await self._enrich_traced(m, a, fast, started)
            span.set_attribute("pa.outcome", outcome)
            if outcome == "error":
                span.set_status(StatusCode.ERROR)

    async def _enrich_traced(self, m: Moment, a: Audience, fast: Overlay, started: float) -> str:
        try:
            exp = await self._shared(self._explanations, m.id, lambda: self._explain(m))
            persona = (m.id, a.mode, a.club_id, a.player_id)
            text = await self._shared(self._personas, persona, lambda: self._personalise(m, exp, a))
            if a.language != "en":
                text = await self._shared(
                    self._translations, persona + (a.language,), lambda: self._translate(m, text, a),
                )
        except _Stop as stop:
            return stop.reason
        except Exception as err:  # never let the AI path take the stream down
            self._record(m, a.key, "orchestrator", "error", detail=repr(err)[:200])
            return "error"

        age_ms = (time.perf_counter() - started) * 1000
        upgraded = fast.model_copy(update={
            "headline": text.headline, "body": text.body, "source": "ai", "version": 2,
            "evidence": [x for x in exp.evidence if x in {f.id for f in m.facts}] or fast.evidence,
            "model": getattr(self.llm, "name", None),
        })
        try:
            validate(upgraded, m, now_elapsed_ms=m.elapsed_ms + int(age_ms), stale_ms=self.stale_ms)
        except ValidationError as err:
            outcome = "stale" if "stale" in str(err) else "rejected"
            self._record(m, a.key, "validator", outcome, ms=age_ms, detail=str(err))
            return outcome
        self._record(m, a.key, "validator", "published", ms=age_ms)
        self._publish(upgraded)
        return "published"
