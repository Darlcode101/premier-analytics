"""Web backend: match sessions streamed to viewers over WebSocket.

A MatchSession replays a generated match at a chosen speed through the Orchestrator.
Each WebSocket viewer declares a profile (mode, language, club, player); viewers with the
same profile share one audience, and the AI path only runs for audiences someone is
watching. Messages per viewer: hello, backfill, event, stats, overlay, screen, trace,
recap, end.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from .agents import LLM, AgentFrameworkLLM, CriticAgent, ResilientLLM
from .generator import generate_match
from .league import League, load_league
from .orchestrator import Orchestrator, TraceEvent
from .overlay import Audience, Names, Overlay, display_minute, fast_overlay
from .recap import Recap
from .schema import PITCH_LENGTH, PITCH_WIDTH, Event

MIN = 60_000
BACKFILL = 30
STATS_FIELDS = (
    "goals", "shots", "shots_on_target", "big_chances", "xg", "passes", "passes_completed", "pass_accuracy",
    "possession_pct", "tackles_won", "interceptions", "fouls", "yellow_cards", "red_cards",
)


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


@dataclass
class Viewer:
    audience: Audience
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    last_screen: tuple = ()


class MatchSession:
    def __init__(self, match_id: str, req: MatchRequest, league: League, llm: LLM | None, critic: CriticAgent,
                 max_ai_audiences: int):
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
        self.orch = Orchestrator(
            req.home, req.away, self.match.meta.match_id, self.names, [], llm=llm, critic=critic,
            on_overlay=self._on_overlay, recaps=llm is not None, on_recap=self._on_recap,
            on_trace=self._on_trace, max_ai_audiences=max_ai_audiences,
        )

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
        }

    def join(self, a: Audience) -> Viewer:
        v = Viewer(audience=a)
        self.viewers.append(v)
        self.orch.add_audience(a)
        v.queue.put_nowait(self.hello(a))
        wanted = [m for m in self.orch.state.moments if a.wants(m)][-BACKFILL:]
        v.queue.put_nowait({
            "type": "backfill",
            "overlays": [fast_overlay(m, a, self.names).model_dump(mode="json") for m in wanted],
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

    def _on_recap(self, r: Recap) -> None:
        self._send({"type": "recap", "recap": r.model_dump(mode="json")}, language=r.language)

    def _on_trace(self, t: TraceEvent) -> None:
        msg = {"type": "trace", "trace": {
            "moment_id": t.moment_id, "audience": t.audience, "agent": t.agent, "outcome": t.outcome,
            "model": t.model, "ms": round(t.ms), "detail": t.detail,
        }}
        for v in self.viewers:
            if t.audience in ("*", v.audience.key, v.audience.language):
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

        return {"type": "stats", "home": team(self.names.home_id), "away": team(self.names.away_id),
                "chaos": round(snap.chaos, 3), "clock_ms": self.clock_ms, "period": self.period,
                "elapsed_ms": snap.elapsed_ms}

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
               max_ai_audiences: int = 8, static_dir: Path | str | None = None) -> FastAPI:
    app = FastAPI(title="Premier Analytics")
    league = load_league()
    if llm == "env":
        llm = build_llm_from_env()
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
        sessions[sid] = MatchSession(sid, req, league, llm, critic, max_ai_audiences)
        return sessions[sid]

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "ai": llm is not None, "sessions": len(sessions)}

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
                return FileResponse(target)
            return FileResponse(root / "index.html")

    return app
