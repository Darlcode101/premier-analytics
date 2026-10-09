"""MCP server exposing the live, verified match state as tools (A-4).

Agents (the Recap Producer) and any external MCP client query the same state the overlays
are built from, so every number they quote comes from the statistics engine. Mounted into
the web app over Streamable HTTP; tests connect in-process.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .overlay import Names, display_minute
from .scout import Moment, MomentScout

PLAYER_METRICS = ("goals", "assists", "shots", "xg", "passes_completed", "tackles_won", "interceptions")


@dataclass
class MatchState:
    names: Names
    scout: MomentScout
    moments: list[Moment] = field(default_factory=list)

    def add_moments(self, moments: list[Moment]) -> None:
        self.moments.extend(moments)

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
        raise ToolError(f"Unknown player {player!r} in this match")


def _round(v):
    return round(v, 2) if isinstance(v, float) else v


def build_server(state: MatchState) -> MCPServer:
    server = MCPServer(
        name="premier-analytics-match",
        instructions="Live, verified statistics for the match in progress. Every number comes from the "
                     "deterministic statistics engine; quote them exactly.",
    )
    engine = state.scout.engine

    @server.tool(description="Current score, minute and teams.")
    def get_score() -> dict:
        snap = engine.snapshot()
        return {
            "home": state.names.club(state.names.home_id), "away": state.names.club(state.names.away_id),
            "score_home": snap.score[0], "score_away": snap.score[1],
            "period": snap.period, "minute": snap.clock_ms // 60_000 + 1,
        }

    @server.tool(description="Match totals and last-10-minute indicators for one team ('home', 'away' or club name).")
    def get_team_stats(team: str) -> dict:
        tid = state.team_id(team)
        stats = engine.snapshot().teams[tid].model_dump()
        stats = {k: _round(v) for k, v in stats.items() if k != "window"} | {
            "team": state.names.club(tid),
            "window": {k: _round(v) for k, v in engine.snapshot().teams[tid].window.model_dump().items()},
        }
        return stats

    @server.tool(description="Match statistics for one player, by name.")
    def get_player_stats(player: str) -> dict:
        pid = state.player_id(player)
        stats = engine.snapshot().players.get(pid)
        data = {k: _round(v) for k, v in stats.model_dump().items()} if stats else {}
        team = data.pop("team_id", None) or next(
            (c for c in state.names.clubs if pid.startswith(c)), None,
        )
        return {"name": state.names.player(pid), "team": state.names.club(team), **{m: data.get(m, 0) for m in PLAYER_METRICS}}

    @server.tool(description=f"Top players by a metric: one of {', '.join(PLAYER_METRICS)}.")
    def get_top_players(metric: str, limit: int = 3) -> dict:
        if metric not in PLAYER_METRICS:
            raise ToolError(f"metric must be one of {PLAYER_METRICS}")
        players = engine.snapshot().players
        ranked = sorted(players.items(), key=lambda kv: getattr(kv[1], metric), reverse=True)[:limit]
        return {"players": [
            {"name": state.names.player(pid), "team": state.names.club(p.team_id), metric: _round(getattr(p, metric))}
            for pid, p in ranked
        ]}

    @server.tool(description="Key moments so far, most recent last, filtered by minimum severity (0-1).")
    def get_key_moments(min_severity: float = 0.5, limit: int = 20) -> dict:
        chosen = [m for m in state.moments if m.severity >= min_severity][-limit:]
        out = []
        for m in chosen:
            facts = []
            for f in m.facts:
                value = f.value
                if isinstance(value, str):
                    value = state.names.players.get(value) or state.names.clubs.get(value) or value
                facts.append({"label": f.label, "value": _round(value)})
            out.append({
                "kind": m.kind, "minute": display_minute(m), "severity": m.severity,
                "team": state.names.club(m.team_id) if m.team_id else None,
                "player": state.names.player(m.player_id) if m.player_id else None,
                "facts": facts,
            })
        return {"moments": out}

    return server
