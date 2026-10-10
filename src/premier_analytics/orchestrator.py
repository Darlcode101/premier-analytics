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
from collections.abc import Callable
from dataclasses import dataclass

from .agents import (
    AllModelsFailed, CriticAgent, ExplainerAgent, Explanation, LLM, Personalised, PersonaliserAgent,
    TranslatorAgent,
)
from .mcp_server import MatchState
from .overlay import STALE_MS, Audience, Names, Overlay, Scheduler, ValidationError, fast_overlay, validate
from .recap import Recap, RecapProducer
from .schema import Event
from .scout import Moment, MomentScout

AI_KINDS = frozenset({
    "goal", "milestone", "big_chance", "woodwork", "red_card", "rocket_shot", "momentum_shift",
    "pressure_spell", "half_time", "full_time",
})


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


class Orchestrator:
    def __init__(self, home_id: str, away_id: str, match_id: str, names: Names, audiences: list[Audience],
                 llm: LLM | None, critic: CriticAgent, stale_ms: int = STALE_MS,
                 on_overlay: Callable[[Overlay], None] | None = None, max_on_screen: int = 2,
                 recaps: bool = False, recap_tools: list | None = None, recap_llm: LLM | None = None,
                 on_recap: Callable[[Recap], None] | None = None, max_ai_audiences: int | None = None,
                 on_trace: Callable[[TraceEvent], None] | None = None):
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
        for a in audiences:
            self.add_audience(a)
        self.published: list[Overlay] = []
        self.trace: list[TraceEvent] = []
        self.match_now = 0
        self._tasks: set[asyncio.Task] = set()
        self._explanations: dict[str, asyncio.Task] = {}
        self._personas: dict[tuple, asyncio.Task] = {}
        self._translations: dict[tuple, asyncio.Task] = {}
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
                if not a.wants(m):
                    continue
                o = validate(fast_overlay(m, a, self.names), m, now_elapsed_ms=e.elapsed_ms)
                self._publish(o)
                fast.append(o)
                if m.kind in AI_KINDS and self.ai_enabled_for(a):
                    self._spawn(self._enrich(m, a, o, time.perf_counter()))
        await asyncio.sleep(0)  # let background work start
        return fast

    def add_audience(self, a: Audience) -> None:
        if a.key not in self.schedulers:
            self.audiences.append(a)
            self.schedulers[a.key] = Scheduler(max_on_screen=self.max_on_screen)

    def remove_audience(self, key: str) -> None:
        self.audiences = [a for a in self.audiences if a.key != key]
        self.schedulers.pop(key, None)

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
        for language in sorted({a.language for a in self.audiences}):
            start = time.perf_counter()
            try:
                recap = await self.recap_producer.run(m.kind, language)
            except Exception as err:  # recaps are best-effort; the template overlay already covers HT/FT
                self._record(m, language, "recap", "error", detail=repr(err)[:200])
                continue
            ms = (time.perf_counter() - start) * 1000
            if recap is None:
                self._record(m, language, "recap", "rejected", ms=ms)
                continue
            self._record(m, language, "recap", "ok", recap.model, ms)
            self.recaps.append(recap)
            if self.on_recap:
                self.on_recap(recap)

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
        try:
            res = await coro
        except AllModelsFailed as err:
            self._record(m, audience, agent, "error", detail=str(err))
            raise _Stop() from err
        self._record(m, audience, agent, "ok", res.model, res.ms)
        return res.value

    def _check(self, m: Moment, audience: str, headline: str, body: str, evidence=None, viewer=None) -> str:
        """Run the Critic; returns '' if approved, else the feedback text."""
        start = time.perf_counter()
        verdict = self.critic.review(headline, body, m, self.names, evidence=evidence, audience=viewer)
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
        try:
            exp = await self._shared(self._explanations, m.id, lambda: self._explain(m))
            persona = (m.id, a.mode, a.club_id, a.player_id)
            text = await self._shared(self._personas, persona, lambda: self._personalise(m, exp, a))
            if a.language != "en":
                text = await self._shared(
                    self._translations, persona + (a.language,), lambda: self._translate(m, text, a),
                )
        except _Stop:
            return
        except Exception as err:  # never let the AI path take the stream down
            self._record(m, a.key, "orchestrator", "error", detail=repr(err)[:200])
            return

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
            return
        self._record(m, a.key, "validator", "published", ms=age_ms)
        self._publish(upgraded)
