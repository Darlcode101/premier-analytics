"""Web backend: match sessions streamed to viewers over WebSocket.

A MatchSession replays a generated match at a chosen speed through the Orchestrator.
Each WebSocket viewer declares a profile (mode, language, club, player); viewers with the
same profile share one audience, and the AI path only runs for audiences someone is
watching. Messages per viewer: hello, backfill, event, incident, stats, overlay, screen,
trace, recap, end.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from .agents import LLM, AgentFrameworkLLM, CriticAgent, ResilientLLM
from .context import AgentFrameworkWebSearch, AskDesk, ContextEntry, ResearcherAgent, load_library
from .desk import SUBS_ALLOWED, Incidents, last_window
from .generator import generate_match
from .league import League, load_league
from .momentum import AttackMomentum
from .orchestrator import Orchestrator, TraceEvent
from .overlay import Audience, Names, Overlay, display_minute, fast_overlay, overlay_id
from .recap import Recap
from .schema import PITCH_LENGTH, PITCH_WIDTH, Event
from .season import Season, season_summary, simulate_season

MIN = 60_000
BACKFILL = 30
TRACE_HISTORY = 200
STATS_FIELDS = (
    "goals", "shots", "shots_on_target", "big_chances", "xg", "passes", "passes_completed", "final_third_passes",
    "pass_accuracy", "possession_pct", "tackles_won", "interceptions", "fouls", "yellow_cards", "red_cards",
)
PLAYER_FIELDS = ("passes", "passes_completed", "shots", "goals", "assists", "xg", "tackles_won", "interceptions",
                 "fouls", "yellow_cards", "red_cards")
LAST_WINDOW_MIN = 10


@functools.cache
def default_season() -> Season:
    """The simulated season behind the desk's context (CD-14); the same on every start, so build it once."""
    return simulate_season(load_league())


def build_researcher_from_env() -> ResearcherAgent | None:
    """The ask box's Researcher (CX-3): Foundry web search on the live model, keyless."""
    endpoint, live = os.environ.get("AZURE_OPENAI_ENDPOINT"), os.environ.get("LIVE_MODEL_DEPLOYMENT")
    return ResearcherAgent(AgentFrameworkWebSearch(live, endpoint)) if endpoint and live else None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    language: Literal["en", "es", "ar"] = "en"


def build_llm_from_env() -> LLM | None:
    """Foundry models from the environment. AZURE_OPENAI_API_KEY is optional: without it the app
    uses Entra ID (managed identity in Azure, `az login` locally)."""
    endpoint, key = os.environ.get("AZURE_OPENAI_ENDPOINT"), os.environ.get("AZURE_OPENAI_API_KEY") or None
    live, recap = os.environ.get("LIVE_MODEL_DEPLOYMENT"), os.environ.get("RECAP_MODEL_DEPLOYMENT")
    if not (endpoint and live):
        return None
    fallback = AgentFrameworkLLM(recap, endpoint, key) if recap else None
    return ResilientLLM(AgentFrameworkLLM(live, endpoint, key), fallback, timeout_s=4.0, retries=1)


class MatchRequest(BaseModel):
    home: str
    away: str
    seed: int = 0
    speed: float = Field(1.0, ge=0, le=600, description="match seconds per real second; 0 = as fast as possible")
    autostart: bool = True


def _abs_coords(e: Event, home_id: str) -> dict[str, float | None]:
    """Event coordinates on one shared pitch: home attack left-to-right in the first half."""
    if e.team_id is None or e.x is None:
        return {"x": None, "y": None, "end_x": None, "end_y": None}
    flip = (e.team_id == home_id) != (e.period == 1)

    def fx(v):
        return None if v is None else round(PITCH_LENGTH - v if flip else v, 1)

    def fy(v):
        return None if v is None else round(PITCH_WIDTH - v if flip else v, 1)

    return {"x": fx(e.x), "y": fy(e.y), "end_x": fx(e.end_x), "end_y": fy(e.end_y)}


def fitting_ai_version(overlays: list[Overlay], a: Audience) -> Overlay | None:
    """F-4: an AI version written for another audience that still fits this one: same mode and language,
    and not written for a different club or player. Prefers the closest (same club, then neutral)."""
    def parts(key: str) -> tuple[str, str, str | None, str | None]:
        mode, language, club, player = key.split(".")
        return mode, language, None if club == "-" else club, None if player == "-" else player

    fits = []
    for o in overlays:
        mode, language, club, player = parts(o.audience)
        if (o.source == "ai" and mode == a.mode and language == a.language
                and club in (None, a.club_id) and player in (None, a.player_id)):
            closeness = (club == a.club_id and club is not None) * 2 + (player == a.player_id and player is not None)
            fits.append((closeness, o.version, o))
    return max(fits, key=lambda f: (f[0], f[1]))[2] if fits else None


@dataclass
class Viewer:
    audience: Audience
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    last_screen: tuple = ()


class MatchSession:
    def __init__(self, match_id: str, req: MatchRequest, league: League, llm: LLM | None, critic: CriticAgent,
                 max_ai_audiences: int, season: Season | None = None, library: list[ContextEntry] | None = None,
                 researcher: ResearcherAgent | None = None, profiles: dict | None = None):
        self.id = match_id
        self.req = req
        self.league = league
        self.match = generate_match(req.home, req.away, req.seed, league)
        self.names = Names.from_league(league, req.home, req.away)
        self.viewers: list[Viewer] = []
        self.status = "waiting"  # waiting | live | finished
        self.task: asyncio.Task | None = None
        self.score = (0, 0)
        self.period, self.clock_ms = 1, 0
        self.momentum: list[dict] = []  # one point per elapsed minute, for late joiners
        self.attack = AttackMomentum(req.home, req.away)
        self.incident_feed = Incidents()
        self.incidents: list[dict] = []
        self.totals: dict[int, tuple[int, dict]] = {}  # elapsed minute -> (elapsed_ms, team totals), for "last 10'"
        self.season = season_summary(season, league, req.home, req.away) if season else None
        self.orch = Orchestrator(
            req.home, req.away, self.match.meta.match_id, self.names, [], llm=llm, critic=critic,
            on_overlay=self._on_overlay, recaps=llm is not None, on_recap=self._on_recap,
            on_trace=self._on_trace, max_ai_audiences=max_ai_audiences,
            context_library=library, on_context=self._on_context,
            season_profiles=profiles, on_patterns=self._on_patterns,
        )
        self.library = library or []
        self.ask_desk = AskDesk(researcher) if researcher else None

    # ---------- viewers ----------

    def hello(self, a: Audience) -> dict:
        def club(cid: str) -> dict:
            c = self.league.club(cid)
            lineup = self.match.meta.lineups[cid]

            def player(pid: str) -> dict:
                p = self.league.player(pid)
                return {"id": p.id, "name": p.name, "number": p.number, "position": p.position}

            return {"id": c.id, "name": c.name, "short_name": c.short_name, "colors": list(c.colors),
                    "lineup": [player(p) for p in lineup.starting], "bench": [player(p) for p in lineup.bench]}

        meta = self.match.meta
        return {
            "type": "hello", "match_id": self.id, "status": self.status, "speed": self.req.speed,
            "audience": a.key, "home": club(meta.home_id), "away": club(meta.away_id), "venue": meta.venue,
            "referee": meta.referee, "kickoff": meta.kickoff_local, "weather": meta.weather.model_dump(),
            "score_home": self.score[0], "score_away": self.score[1], "momentum": list(self.momentum),
            "attack": self.attack.series(),
            "incidents": list(self.incidents), "subs_allowed": SUBS_ALLOWED, "season": self.season,
            "context": [c for c in self.orch.contexts if a.mode == "analyst" and c["language"] == a.language],
            "explainers": self._explainers(a.language),
            "patterns": self.orch.latest_patterns.get(a.language),
            **self._history(a),
        }

    def _history(self, a: Audience) -> dict:
        """What a late joiner missed: recaps and the agent activity so far."""
        recaps = {}
        for r in self.orch.recaps:  # their own mode first; otherwise the other mode's recap in their language
            if r.language == a.language and (r.kind not in recaps or r.mode == a.mode):
                recaps[r.kind] = r
        # The desk's Production tab shows the whole system; other viewers only what concerns them.
        mine = [t for t in self.orch.trace if a.mode == "analyst" or t.audience in ("*", a.key, a.language)]
        counts = {k: sum(t.outcome == k for t in mine) for k in ("published", "rejected", "stale", "error")}
        return {
            "recaps": [r.model_dump(mode="json") for r in recaps.values()],
            "trace": [self._trace_json(t) for t in mine[-TRACE_HISTORY:]][::-1],
            "trace_counts": counts,
        }

    @staticmethod
    def _trace_json(t: TraceEvent) -> dict:
        return {"moment_id": t.moment_id, "audience": t.audience, "agent": t.agent, "outcome": t.outcome,
                "model": t.model, "ms": round(t.ms), "detail": t.detail}

    def _explainers(self, language: str) -> dict:
        """Tactics explainers keyed by the stat they explain (CX-8)."""
        out = {}
        for e in self.library:
            for tag in e.tags:
                if tag.startswith("stat:"):
                    out[tag[5:]] = {"topic": e.topic, "text": e.text_in(language),
                                    "sources": [s.model_dump() for s in e.sources]}
        return out

    def join(self, a: Audience) -> Viewer:
        v = Viewer(audience=a)
        self.viewers.append(v)
        self.orch.add_audience(a)
        v.queue.put_nowait(self.hello(a))
        wanted = self.orch.visible(a)[-BACKFILL:]
        # Latest version of each overlay already produced for this audience (AI upgrades included).
        latest: dict[str, Overlay] = {}
        ai_by_moment: dict[str, list[Overlay]] = {}
        for o in self.orch.published:
            if o.audience == a.key and (o.id not in latest or o.version > latest[o.id].version):
                latest[o.id] = o
            if o.source == "ai":
                ai_by_moment.setdefault(o.moment_id, []).append(o)

        def best(m) -> Overlay:
            own = latest.get(overlay_id(m, a))
            if own is not None and own.source == "ai":
                return own
            # F-4: after a settings change, reuse an AI version written for a compatible audience.
            borrowed = fitting_ai_version(ai_by_moment.get(m.id, []), a)
            if borrowed is not None:
                return borrowed.model_copy(update={"id": overlay_id(m, a), "audience": a.key})
            return own or fast_overlay(m, a, self.names)

        v.queue.put_nowait({
            "type": "backfill",
            "overlays": [best(m).model_dump(mode="json") for m in wanted],
        })
        if self.status != "waiting":
            v.queue.put_nowait(self._stats())
        if self.status == "finished":
            v.queue.put_nowait(self._end())
        elif self.req.autostart:
            self.start()
        return v

    def leave(self, v: Viewer) -> None:
        self.viewers.remove(v)
        if not any(x.audience.key == v.audience.key for x in self.viewers):
            self.orch.remove_audience(v.audience.key)

    def _send(self, msg: dict, audience: str | None = None, language: str | None = None) -> None:
        for v in self.viewers:
            if audience is not None and v.audience.key != audience:
                continue
            if language is not None and v.audience.language != language:
                continue
            v.queue.put_nowait(msg)

    # ---------- orchestrator callbacks ----------

    def _on_overlay(self, o: Overlay) -> None:
        self._send({"type": "overlay", "overlay": o.model_dump(mode="json")}, audience=o.audience)
        self._push_screens()

    def _on_patterns(self, payload: dict) -> None:
        self._send(payload, language=payload["language"])

    def _on_context(self, card: dict) -> None:
        for v in self.viewers:
            if v.audience.mode == "analyst" and v.audience.language == card["language"]:
                v.queue.put_nowait({"type": "context", "context": card})

    def _on_recap(self, r: Recap) -> None:
        for v in self.viewers:
            if v.audience.language == r.language and v.audience.mode == r.mode:
                v.queue.put_nowait({"type": "recap", "recap": r.model_dump(mode="json")})

    def _on_trace(self, t: TraceEvent) -> None:
        msg = {"type": "trace", "trace": self._trace_json(t)}
        for v in self.viewers:
            if v.audience.mode == "analyst" or t.audience in ("*", v.audience.key, v.audience.language):
                v.queue.put_nowait(msg)

    def _push_screens(self) -> None:
        for v in self.viewers:
            shown = self.orch.on_screen(v.audience.key)
            signature = tuple((o.id, o.version) for o in shown)
            if signature != v.last_screen:
                v.last_screen = signature
                v.queue.put_nowait({"type": "screen", "overlays": [o.model_dump(mode="json") for o in shown]})

    # ---------- playback ----------

    def _stats(self) -> dict:
        snap = self.orch.scout.engine.snapshot()

        def team(tid: str) -> dict:
            t = snap.teams[tid]
            data = {k: round(getattr(t, k), 3) if isinstance(getattr(t, k), float) else getattr(t, k)
                    for k in STATS_FIELDS}
            data["window"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in t.window.model_dump().items()}
            return data

        minute = snap.elapsed_ms // MIN
        home, away = team(self.names.home_id), team(self.names.away_id)
        self.totals[minute] = (snap.elapsed_ms, {"home": home, "away": away})
        then_ms, then = self.totals.get(minute - LAST_WINDOW_MIN, (0, None))
        for side, data in (("home", home), ("away", away)):
            data["last10"] = last_window(data, then[side] if then else None, snap.elapsed_ms, then_ms)
        players = {pid: {k: round(getattr(p, k), 3) if isinstance(getattr(p, k), float) else getattr(p, k)
                         for k in PLAYER_FIELDS} for pid, p in snap.players.items()}
        tracker = self.orch.pattern_tracker
        shape = {"home": tracker.summary(self.names.home_id), "away": tracker.summary(self.names.away_id)}
        return {"type": "stats", "home": home, "away": away, "players": players, "shape": shape,
                "chaos": round(snap.chaos, 3), "clock_ms": self.clock_ms, "period": self.period,
                "elapsed_ms": snap.elapsed_ms, "attack": self.attack.point(minute)}

    def _end(self) -> dict:
        return {"type": "end", "score_home": self.score[0], "score_away": self.score[1]}

    def start(self) -> None:
        if self.status == "waiting":
            self.status = "live"
            self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        begin = loop.time()
        speed = self.req.speed
        last_minute = -1
        for e in self.match.events:
            if speed > 0:
                delay = e.elapsed_ms / 1000 / speed - (loop.time() - begin)
                if delay > 0:
                    await asyncio.sleep(delay)
            else:
                await asyncio.sleep(0)
            self.period, self.clock_ms = e.period, e.clock_ms
            if e.type in ("goal", "period_end"):
                self.score = (e.score_home, e.score_away)
            await self.orch.handle(e)
            metric = self.orch.scout.engine.metrics.get(e.id)
            self.attack.observe(e, metric)
            incident = self.incident_feed.observe(e, metric)
            if incident:
                self.incidents.append(incident)
                self._send({"type": "incident", "incident": incident})
            self._send({
                "type": "event", "kind": e.type, "seq": e.seq, "period": e.period, "clock_ms": e.clock_ms,
                "display_minute": display_minute(e), "team_id": e.team_id, "player_id": e.player_id,
                "player": self.names.player(e.player_id) if e.player_id else None,
                "outcome": e.outcome, "score_home": self.score[0], "score_away": self.score[1],
                **_abs_coords(e, self.names.home_id),
            })
            minute = e.elapsed_ms // MIN  # elapsed, so first-half stoppage never collides with the second half
            if minute != last_minute:
                last_minute = minute
                stats = self._stats()
                self.momentum.append({"minute": minute, "value": stats["home"]["window"]["momentum"]})
                self._send(stats)
            self._push_screens()
        await self.orch.drain()
        self.status = "finished"
        self._send(self._stats())
        self._send(self._end())


def create_app(llm: LLM | None | str = "env", live_session: bool = True, max_sessions: int = 4,
               max_ai_audiences: int = 8, static_dir: Path | str | None = None,
               season: Season | None | str = "default", context_library: list[ContextEntry] | None | str = "default",
               researcher: ResearcherAgent | None | str = "env") -> FastAPI:
    if llm == "env":
        llm = build_llm_from_env()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        if llm is not None and hasattr(llm, "warm"):
            # Get the first Entra ID token now, so the first live call isn't the one that pays for it.
            async def warm() -> None:
                try:
                    await llm.warm()
                except Exception as err:  # the fast path works regardless; just report it
                    print(f"model warm-up failed: {err!r}")
            asyncio.get_running_loop().create_task(warm())
        yield

    app = FastAPI(title="Premier Analytics", lifespan=lifespan)
    league = load_league()
    if season == "default":
        season = default_season()
    profiles = season.profiles() if season else None
    if context_library == "default":
        context_library = load_library()
    if researcher == "env":
        researcher = build_researcher_from_env() if llm is not None else None
    critic = CriticAgent({p.name for c in league.clubs for p in league.squad(c.id)},
                         {c.short_name for c in league.clubs})
    sessions: dict[str, MatchSession] = {}
    app.state.sessions = sessions

    def new_session(req: MatchRequest) -> MatchSession:
        try:
            league.club(req.home)
            league.club(req.away)
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
        if req.home == req.away:
            raise HTTPException(422, "a club cannot play itself")
        for sid in [k for k, v in sessions.items() if v.status == "finished" and not v.viewers]:
            del sessions[sid]
        if len(sessions) >= max_sessions:
            raise HTTPException(429, "too many matches running; try again shortly")
        sid = uuid.uuid4().hex[:8]
        sessions[sid] = MatchSession(sid, req, league, llm, critic, max_ai_audiences, season, context_library, researcher,
                                     profiles)
        return sessions[sid]

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "ai": llm is not None, "sessions": len(sessions),
                "version": os.environ.get("PA_VERSION", "dev")}

    @app.get("/api/clubs")
    def clubs() -> list[dict]:
        return [
            {"id": c.id, "name": c.name, "short_name": c.short_name, "colors": list(c.colors),
             "players": [{"id": p.id, "name": p.name, "number": p.number, "position": p.position}
                         for p in league.squad(c.id)]}
            for c in league.clubs
        ]

    @app.post("/api/matches", status_code=201)
    def create_match(req: MatchRequest) -> dict:
        s = new_session(req)
        return {"match_id": s.id, "status": s.status}

    @app.post("/api/matches/{match_id}/start")
    async def start_match(match_id: str) -> dict:
        s = sessions.get(match_id)
        if s is None:
            raise HTTPException(404, "no such match")
        s.start()
        return {"match_id": s.id, "status": s.status}

    @app.post("/api/matches/{match_id}/ask")
    async def ask(match_id: str, req: AskRequest) -> dict:
        """The desk's ask box (CX-3): a live, sourced web answer, capped per match."""
        s = sessions.get(match_id)
        if s is None:
            raise HTTPException(404, "no such match")
        if s.ask_desk is None:
            return {"status": "unavailable", "text": "", "sources": [], "remaining": 0}
        return await s.ask_desk.ask(req.question, req.language)

    @app.websocket("/ws/matches/{match_id}")
    async def watch(ws: WebSocket, match_id: str):
        s = sessions.get(match_id)
        try:
            params: dict[str, Any] = {k: v for k, v in ws.query_params.items() if v not in ("", "-")}
            audience = Audience(**params)
        except ValidationError:
            await ws.close(code=4400)
            return
        if s is None:
            await ws.close(code=4404)
            return
        await ws.accept()
        viewer = s.join(audience)

        async def pump() -> None:
            while True:
                await ws.send_json(await viewer.queue.get())

        async def listen() -> None:
            # Notice a departed viewer even when there is nothing to send.
            while (await ws.receive())["type"] != "websocket.disconnect":
                pass

        tasks = {asyncio.create_task(pump()), asyncio.create_task(listen())}
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for t in tasks:
                t.cancel()
            s.leave(viewer)
            with contextlib.suppress(Exception):
                await ws.close()

    if static_dir is not None:
        root = Path(static_dir).resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            """Serve the built React app; unknown paths fall back to index.html (client-side routes)."""
            target = (root / path).resolve()
            if path and target.is_file() and target.is_relative_to(root):
                # Vite puts a content hash in asset names, so they can be cached for good.
                immutable = path.startswith("assets/")
                return FileResponse(target, headers={
                    "Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache",
                })
            # Always revalidate the page itself, or browsers keep running the previous deploy.
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app
