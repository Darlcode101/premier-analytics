"""MCP server exposing the live, verified match state as tools (A-4).

Agents (the Recap Producer) and any external MCP client query the same state the overlays
are built from, so every number they quote comes from the statistics engine. Mounted into
the web app over Streamable HTTP; tests connect in-process.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import wraps

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from .overlay import Names, display_minute
from .schema import Event
from .scout import Moment, MomentScout

PLAYER_METRICS = ("goals", "assists", "shots", "xg", "passes_completed", "tackles_won", "interceptions")


@dataclass
class MatchState:
    names: Names
    scout: MomentScout
    moments: list[Moment] = field(default_factory=list)
    # AM-1: players' running totals at the start of each match minute, for "since minute X" questions.
    history: list[tuple[int, int, dict]] = field(default_factory=list)  # (period, clock_ms, player -> stats)
    _minute: tuple[int, int] | None = None

    def add_moments(self, moments: list[Moment]) -> None:
        self.moments.extend(moments)

    def record(self, e: Event) -> None:
        """Call before the engine sees the event: snapshot the totals when a new minute starts."""
        key = (e.period, e.clock_ms // 60_000)
        if key != self._minute:
            self._minute = key
            self.history.append((e.period, e.clock_ms,
                                 {pid: p.model_dump() for pid, p in self.scout.engine.players.items()}))

    def players_at(self, minute: int) -> dict | None:
        """Totals as minute `minute` began (minutes over 45 are second-half minutes); None if not reached."""
        period, start = (2 if minute > 45 else 1), (minute - 1) * 60_000
        return next((players for p, clock, players in self.history if p == period and clock >= start), None)

    def team_id(self, team: str) -> str:
        key = team.strip().lower()
        if key == "home":
            return self.names.home_id
        if key == "away":
            return self.names.away_id
        for cid, name in self.names.clubs.items():
            if key in (cid.lower(), name.lower()):
                return cid
        raise ToolError(f"Unknown team {team!r}. Use 'home', 'away', or one of: {', '.join(self.names.clubs.values())}")

    def player_id(self, player: str) -> str:
        key = player.strip().lower()
        for pid, name in self.names.players.items():
            if key in (pid.lower(), name.lower()):
                return pid
        surname = [pid for pid, name in self.names.players.items() if name.lower().split(" ")[-1] == key]
        if len(surname) == 1:
            return surname[0]
        raise ToolError(f"Unknown player {player!r} in this match")


def _round(v):
    return round(v, 2) if isinstance(v, float) else v


def _name(state: MatchState, value):
    return state.names.players.get(value) or state.names.clubs.get(value) or value if isinstance(value, str) else value


class MatchTools:
    """Read-only tools over the live match (A-4, AM-1). The MCP server and the Match Analyst share them, so
    every agent quotes the same numbers. Docstrings are the tool descriptions the models see."""

    def __init__(self, state: MatchState):
        self.state = state
        self.engine = state.scout.engine

    def all(self) -> list[Callable]:
        return [self.get_score, self.get_team_stats, self.get_player_stats, self.get_top_players,
                self.get_key_moments, self.get_cards_and_subs]

    def get_score(self) -> dict:
        """Current score, minute and teams."""
        snap = self.engine.snapshot()
        names = self.state.names
        return {
            "home": names.club(names.home_id), "away": names.club(names.away_id),
            "score_home": snap.score[0], "score_away": snap.score[1],
            "period": snap.period, "minute": snap.clock_ms // 60_000 + 1,
        }

    def get_team_stats(self, team: str, since_minute: int | None = None) -> dict:
        """Match totals and last-10-minute indicators for one team ('home', 'away' or club name); with
        since_minute, the counts (goals, shots, xg, passes, ball wins) from that match minute on (second half = 46)."""
        tid = self.state.team_id(team)
        if since_minute is not None:
            then = self.state.players_at(since_minute)
            if then is None:
                raise ToolError(f"Minute {since_minute} has not been played yet")
            now = {pid: p.model_dump() for pid, p in self.engine.players.items() if p.team_id == tid}
            return {"team": self.state.names.club(tid), "since_minute": since_minute} | {
                m: _round(sum(p[m] - then.get(pid, {}).get(m, 0) for pid, p in now.items())) for m in PLAYER_METRICS
            }
        snap = self.engine.snapshot().teams[tid]
        stats = {k: _round(v) for k, v in snap.model_dump().items() if k != "window"}
        return stats | {"team": self.state.names.club(tid), "window": {k: _round(v) for k, v in snap.window.model_dump().items()}}

    def get_player_stats(self, player: str, since_minute: int | None = None) -> dict:
        """Match statistics for one player, by name, with the minute a substitute came on or a player went off
        (a substitute's totals already start when they came on); with since_minute, only from that match
        minute on (second half = 46)."""
        pid = self.state.player_id(player)
        now = self.engine.snapshot().players.get(pid)
        data = {k: _round(v) for k, v in now.model_dump().items()} if now else {}
        team = data.get("team_id") or next((c for c in self.state.names.clubs if pid.startswith(c)), None)
        on = next((display_minute(m) for m in self.state.moments if m.kind == "substitution"
                   and any(f.label == "player_in" and f.value == pid for f in m.facts)), None)
        off = next((display_minute(m) for m in self.state.moments if m.kind == "substitution"
                    and any(f.label == "player_out" and f.value == pid for f in m.facts)), None)
        out = {"name": self.state.names.player(pid), "team": self.state.names.club(team), "came_on": on, "went_off": off}
        if since_minute is None:
            return out | {m: data.get(m, 0) for m in PLAYER_METRICS}
        then = self.state.players_at(since_minute)
        if then is None:
            raise ToolError(f"Minute {since_minute} has not been played yet")
        before = then.get(pid, {})
        return out | {"since_minute": since_minute} | {m: _round(data.get(m, 0) - before.get(m, 0)) for m in PLAYER_METRICS}

    def get_top_players(self, metric: str, limit: int = 3) -> dict:
        """Top players by a metric: one of goals, assists, shots, xg, passes_completed, tackles_won, interceptions."""
        if metric not in PLAYER_METRICS:
            raise ToolError(f"metric must be one of {PLAYER_METRICS}")
        players = self.engine.snapshot().players
        ranked = sorted(players.items(), key=lambda kv: getattr(kv[1], metric), reverse=True)[:limit]
        return {"players": [
            {"name": self.state.names.player(pid), "team": self.state.names.club(p.team_id), metric: _round(getattr(p, metric))}
            for pid, p in ranked
        ]}

    def get_key_moments(self, min_severity: float = 0.5, limit: int = 20) -> dict:
        """Key moments so far, most recent last, filtered by minimum severity (0-1)."""
        chosen = [m for m in self.state.moments if m.severity >= min_severity][-limit:]
        return {"moments": [{
            "kind": m.kind, "minute": display_minute(m), "severity": m.severity,
            "team": self.state.names.club(m.team_id) if m.team_id else None,
            "player": self.state.names.player(m.player_id) if m.player_id else None,
            "facts": [{"label": f.label, "value": _round(_name(self.state, f.value))} for f in m.facts],
        } for m in chosen]}

    def get_cards_and_subs(self) -> dict:
        """Every card so far (who, when, colour and why) and every substitution (who came on for whom, when)."""
        cards, subs = [], []
        for m in self.state.moments:
            f = {x.label: x.value for x in m.facts}
            if m.kind in ("yellow_card", "red_card"):
                cards.append({"minute": display_minute(m), "player": self.state.names.player(m.player_id),
                              "team": self.state.names.club(m.team_id), "card": f.get("card"),
                              "reason": str(f.get("card_reason") or "").replace("_", " ")})
            elif m.kind == "substitution":
                subs.append({"minute": display_minute(m), "team": self.state.names.club(m.team_id),
                             "on": self.state.names.player(f.get("player_in")), "off": self.state.names.player(f.get("player_out"))})
        return {"cards": cards, "subs": subs}

    def recorded(self, log: list) -> list[Callable]:
        """The tools, each call appended to `log` as {tool, args, result}. Tool errors come back as
        {"error": ...} so a model can correct itself (AM-2 checks answers against these results)."""
        def wrap(fn):
            sig = inspect.signature(fn)

            @wraps(fn)
            def call(*args, **kwargs):
                try:
                    result = fn(*args, **kwargs)
                except ToolError as err:
                    result = {"error": str(err)}
                log.append({"tool": fn.__name__, "args": dict(sig.bind(*args, **kwargs).arguments), "result": result})
                return result
            return call
        return [wrap(fn) for fn in self.all()]


def build_server(state: MatchState, on_call: Callable[[str, dict], None] | None = None) -> FastMCP:
    """on_call(tool_name, arguments) is invoked for every tool call, e.g. to show agent activity."""
    server = FastMCP(
        name="premier-analytics-match",
        instructions="Live, verified statistics for the match in progress. Every number comes from the "
                     "deterministic statistics engine; quote them exactly.",
    )
    for fn in MatchTools(state).all():
        def logged(*args, __fn=fn, **kwargs):
            if on_call:  # the arguments actually given (the framework fills unset optional ones with None)
                on_call(__fn.__name__, {k: v for k, v in kwargs.items() if v is not None})
            return __fn(*args, **kwargs)
        server.tool(name=fn.__name__, description=inspect.getdoc(fn))(wraps(fn)(logged))
    return server
