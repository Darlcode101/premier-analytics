"""Deterministic statistics engine.

Consumes events one at a time and keeps running match state: totals per team and player,
time-based possession, pass and shot metrics, and rolling-window indicators (momentum,
field tilt, PPDA, tempo, chaos). No randomness and no LLM: every number here is
reproducible and is what agents are allowed to cite.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from pydantic import BaseModel

from .schema import PITCH_LENGTH as L
from .schema import PITCH_WIDTH as W
from .schema import Event

MIN = 60_000
FINAL_THIRD_X = 70.0
OWN_60_X = 0.6 * L          # a team's own 60 % of the pitch: x < 63
OPP_60_X = 0.4 * L          # the opponent's 60 %: x >= 42 from the presser's perspective


# ---------- pure metrics ----------

def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def pass_difficulty(distance_m: float, progressive_m: float, end_x: float, under_pressure: bool) -> float:
    """0 = trivial, 1 = very hard. Monotonic in length, forward progress, how advanced the
    target is, and pressure."""
    z = (
        -3.6
        + 0.055 * distance_m
        + 0.035 * max(0.0, progressive_m)
        + 0.025 * max(0.0, end_x - 60.0)
        + (0.9 if under_pressure else 0.0)
    )
    return _sigmoid(z)


def shot_geometry(x: float, y: float) -> tuple[float, float]:
    """Distance to goal centre (m) and the angle the goal mouth subtends (radians)."""
    dx, dy = L - x, W / 2 - y
    distance = math.hypot(dx, dy)
    half = 7.32 / 2
    angle = math.atan2(7.32 * dx, dx * dx + dy * dy - half * half)
    if angle < 0:
        angle += math.pi
    return distance, angle


def xg(x: float, y: float, header: bool = False, under_pressure: bool = False) -> float:
    """Expected goals from shot location. A logistic model on distance and goal angle,
    with penalties for headers and pressure. Coefficients are fitted so that, over a
    simulated season, conversion inside and outside the box matches the real 2024/25
    league (14.7 % and 4.2 %, docs/REALISM.md)."""
    distance, angle = shot_geometry(x, y)
    z = -2.2 + 1.8 * angle - 0.06 * distance
    if header:
        z -= 0.75
    if under_pressure:
        z -= 0.25
    return _sigmoid(z)


@dataclass(frozen=True)
class PassMetrics:
    distance_m: float
    progressive_m: float
    difficulty: float
    final_third_entry: bool


@dataclass(frozen=True)
class ShotMetrics:
    distance_m: float
    angle_rad: float
    xg: float
    on_target: bool


# ---------- snapshot models ----------

class WindowStats(BaseModel):
    momentum: float      # -1..1, share of recent threat (xG + final-third passing)
    field_tilt: float    # 0..1, share of recent final-third passes
    ppda: float | None   # opponent passes allowed per defensive action; None if no actions
    tempo: float         # passes per minute
    shots: int           # shots in the window
    xg: float            # xG in the window


class TeamStats(BaseModel):
    goals: int = 0
    shots: int = 0
    shots_on_target: int = 0
    big_chances: int = 0
    xg: float = 0.0
    passes: int = 0
    passes_completed: int = 0
    final_third_passes: int = 0
    tackles: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    pressures: int = 0
    fouls: int = 0
    yellow_cards: int = 0
    red_cards: int = 0
    possession_pct: float = 0.0
    pass_accuracy: float = 0.0
    window: WindowStats | None = None


class PlayerStats(BaseModel):
    team_id: str
    passes: int = 0
    passes_completed: int = 0
    shots: int = 0
    goals: int = 0
    assists: int = 0
    xg: float = 0.0
    tackles_won: int = 0
    interceptions: int = 0
    fouls: int = 0
    yellow_cards: int = 0
    red_cards: int = 0


class Snapshot(BaseModel):
    elapsed_ms: int
    period: int
    clock_ms: int
    score: tuple[int, int]
    teams: dict[str, TeamStats]
    players: dict[str, PlayerStats]
    chaos: float  # 0..1, how often the ball changes hands in the window


BIG_CHANCE_XG = 0.3
ON_TARGET = frozenset({"goal", "saved"})


class MatchEngine:
    def __init__(self, home_id: str, away_id: str, window_ms: int = 10 * MIN):
        self.home_id, self.away_id = home_id, away_id
        self.window_ms = window_ms
        self.teams = {home_id: TeamStats(), away_id: TeamStats()}
        self.players: dict[str, PlayerStats] = {}
        self.score = [0, 0]
        self.possession: str | None = None
        self._possession_ms = {home_id: 0, away_id: 0}
        self._possession_since = 0
        self.elapsed_ms = 0
        self.period = 1
        self.clock_ms = 0
        # (elapsed_ms, team_id, kind, value) for rolling windows
        self._recent: deque[tuple[int, str, str, float]] = deque()
        self.metrics: dict[str, PassMetrics | ShotMetrics] = {}

    def other(self, team: str) -> str:
        return self.away_id if team == self.home_id else self.home_id

    def _player(self, pid: str, team: str) -> PlayerStats:
        p = self.players.get(pid)
        if p is None:
            p = self.players[pid] = PlayerStats(team_id=team)
        return p

    def _set_possession(self, team: str, at: int) -> None:
        if self.possession is not None:
            self._possession_ms[self.possession] += at - self._possession_since
        self.possession = team
        self._possession_since = at

    def _remember(self, at: int, team: str, kind: str, value: float = 1.0) -> None:
        self._recent.append((at, team, kind, value))

    def apply(self, e: Event) -> PassMetrics | ShotMetrics | None:
        self.elapsed_ms, self.period, self.clock_ms = e.elapsed_ms, e.period, e.clock_ms
        t = e.team_id
        team = self.teams.get(t) if t else None
        result: PassMetrics | ShotMetrics | None = None

        if e.type in ("kickoff", "possession_change"):
            self._set_possession(t, e.elapsed_ms)
            if e.type == "possession_change":
                self._remember(e.elapsed_ms, t, "turnover")

        elif e.type == "pass":
            p = self._player(e.player_id, t)
            team.passes += 1
            p.passes += 1
            dist = math.hypot(e.end_x - e.x, e.end_y - e.y)
            prog = e.end_x - e.x
            entry = e.x < FINAL_THIRD_X <= e.end_x
            result = PassMetrics(
                distance_m=dist, progressive_m=prog,
                difficulty=pass_difficulty(dist, prog, e.end_x, bool(e.under_pressure)),
                final_third_entry=entry,
            )
            self._remember(e.elapsed_ms, t, "pass")
            if e.x < OWN_60_X:
                self._remember(e.elapsed_ms, t, "pass_own60")
            if e.outcome == "complete":
                team.passes_completed += 1
                p.passes_completed += 1
                if e.end_x >= FINAL_THIRD_X:
                    team.final_third_passes += 1
                    self._remember(e.elapsed_ms, t, "final_third_pass")

        elif e.type == "shot":
            p = self._player(e.player_id, t)
            dist, angle = shot_geometry(e.x, e.y)
            value = xg(e.x, e.y, header=e.body_part == "head", under_pressure=bool(e.under_pressure))
            on_target = e.outcome in ON_TARGET
            result = ShotMetrics(distance_m=dist, angle_rad=angle, xg=value, on_target=on_target)
            team.shots += 1
            team.xg += value
            p.shots += 1
            p.xg += value
            if on_target:
                team.shots_on_target += 1
            if value >= BIG_CHANCE_XG:
                team.big_chances += 1
            self._remember(e.elapsed_ms, t, "xg", value)
            self._remember(e.elapsed_ms, t, "shot")

        elif e.type == "goal":
            team.goals += 1
            self._player(e.player_id, t).goals += 1
            if e.assist_id:
                self._player(e.assist_id, t).assists += 1
            self.score = [e.score_home, e.score_away]

        elif e.type == "tackle":
            team.tackles += 1
            if e.outcome == "won":
                team.tackles_won += 1
                self._player(e.player_id, t).tackles_won += 1
            if e.x >= OPP_60_X:
                self._remember(e.elapsed_ms, t, "def_action_high")

        elif e.type == "interception":
            team.interceptions += 1
            self._player(e.player_id, t).interceptions += 1
            if e.x >= OPP_60_X:
                self._remember(e.elapsed_ms, t, "def_action_high")

        elif e.type == "pressure":
            team.pressures += 1

        elif e.type == "foul":
            team.fouls += 1
            self._player(e.player_id, t).fouls += 1
            if e.x >= OPP_60_X:
                self._remember(e.elapsed_ms, t, "def_action_high")

        elif e.type == "card":
            p = self._player(e.player_id, t)
            if e.card == "yellow":
                team.yellow_cards += 1
                p.yellow_cards += 1
            else:
                team.red_cards += 1
                p.red_cards += 1

        if result is not None:
            self.metrics[e.id] = result
        return result

    # ---------- snapshots ----------

    def _window(self, now: int) -> tuple[dict[str, dict[str, float]], float]:
        start = now - self.window_ms
        # Only discard what is out of the window for the live clock, so a snapshot
        # taken at a hypothetical later time doesn't lose data for later live snapshots.
        prune_before = min(now, self.elapsed_ms) - self.window_ms
        while self._recent and self._recent[0][0] < prune_before:
            self._recent.popleft()
        sums = {self.home_id: {}, self.away_id: {}}
        for at, team, kind, value in self._recent:
            if start <= at <= now:
                sums[team][kind] = sums[team].get(kind, 0.0) + value
        minutes = max(min(self.window_ms, now) / MIN, 1e-9)
        return sums, minutes

    def snapshot(self, at_ms: int | None = None) -> Snapshot:
        now = self.elapsed_ms if at_ms is None else at_ms
        sums, minutes = self._window(now)

        held = dict(self._possession_ms)
        if self.possession is not None:
            held[self.possession] += max(0, now - self._possession_since)
        total_held = sum(held.values())

        def threat(team: str) -> float:
            s = sums[team]
            return s.get("xg", 0.0) + 0.012 * s.get("final_third_pass", 0.0)

        h_threat, a_threat = threat(self.home_id), threat(self.away_id)
        denom = h_threat + a_threat
        home_momentum = (h_threat - a_threat) / (denom + 0.1) if denom > 0 else 0.0

        teams = {}
        for tid in (self.home_id, self.away_id):
            opp = self.other(tid)
            stats = self.teams[tid].model_copy()
            stats.possession_pct = 100 * held[tid] / total_held if total_held else 50.0
            stats.pass_accuracy = stats.passes_completed / stats.passes if stats.passes else 0.0
            ft, ft_opp = sums[tid].get("final_third_pass", 0.0), sums[opp].get("final_third_pass", 0.0)
            actions = sums[tid].get("def_action_high", 0.0)
            stats.window = WindowStats(
                momentum=home_momentum if tid == self.home_id else -home_momentum,
                field_tilt=ft / (ft + ft_opp) if ft + ft_opp else 0.5,
                ppda=sums[opp].get("pass_own60", 0.0) / actions if actions else None,
                tempo=sums[tid].get("pass", 0.0) / minutes,
                shots=int(sums[tid].get("shot", 0)),
                xg=sums[tid].get("xg", 0.0),
            )
            teams[tid] = stats

        turnovers = sum(s.get("turnover", 0.0) for s in sums.values())
        # A typical match turns the ball over ~2.7 times a minute, which maps to ~0.5.
        chaos = min(1.0, max(0.0, (turnovers / minutes - 1.2) / 3.0))

        return Snapshot(
            elapsed_ms=now, period=self.period, clock_ms=self.clock_ms,
            score=(self.score[0], self.score[1]), teams=teams,
            players={k: v.model_copy() for k, v in self.players.items()}, chaos=chaos,
        )
