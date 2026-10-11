"""Attack momentum: one bar per elapsed minute, explainable by construction.

Each bar compares the two teams' attacking threat over a rolling three-minute window:
shots (weighted by xG), completed passes into the final third, and ball regains in the
opponent's half. Every point carries those raw counts, so the UI can say exactly why a bar
leans one way, and the numbers are the same ones the statistics engine reports.
"""
from __future__ import annotations

from .engine import FINAL_THIRD_X, MIN, ShotMetrics
from .overlay import display_minute
from .schema import PITCH_LENGTH, Event

WINDOW_MINUTES = 3
HALFWAY = PITCH_LENGTH / 2
# Threat weights: xG dominates; territory and pressing tip quiet minutes.
W_PASS = 0.012
W_REGAIN = 0.02
DAMPING = 0.15


def _empty() -> dict:
    return {"shots": 0, "xg": 0.0, "final_third_passes": 0, "high_regains": 0}


class AttackMomentum:
    def __init__(self, home_id: str, away_id: str):
        self.home_id, self.away_id = home_id, away_id
        self._minutes: list[dict[str, dict]] = []  # index = elapsed minute
        self._labels: list[str] = []                 # broadcast clock label per elapsed minute, e.g. "45+2"

    def _bucket(self, minute: int) -> dict[str, dict]:
        while len(self._minutes) <= minute:
            self._minutes.append({self.home_id: _empty(), self.away_id: _empty()})
        return self._minutes[minute]

    def observe(self, e: Event, metrics=None) -> None:
        minute = e.elapsed_ms // MIN
        bucket = self._bucket(minute)
        while len(self._labels) <= minute:
            self._labels.append(self._labels[-1] if self._labels else "1")
        self._labels[minute] = display_minute(e)
        if e.team_id not in (self.home_id, self.away_id):
            return
        side = bucket[e.team_id]
        if e.type == "shot":
            side["shots"] += 1
            if isinstance(metrics, ShotMetrics):
                side["xg"] = round(side["xg"] + metrics.xg, 3)
        elif e.type == "pass" and e.outcome == "complete" and e.end_x is not None and e.end_x >= FINAL_THIRD_X:
            side["final_third_passes"] += 1
        elif (e.type == "interception" or (e.type == "tackle" and e.outcome == "won")) and e.x is not None and e.x >= HALFWAY:
            side["high_regains"] += 1

    @staticmethod
    def _threat(c: dict) -> float:
        return c["xg"] + W_PASS * c["final_third_passes"] + W_REGAIN * c["high_regains"]

    def point(self, minute: int) -> dict:
        start = max(0, minute - WINDOW_MINUTES + 1)
        totals = {self.home_id: _empty(), self.away_id: _empty()}
        for m in range(start, minute + 1):
            for team in totals:
                for k, v in self._bucket(m)[team].items():
                    totals[team][k] += v
        for team in totals:
            totals[team]["xg"] = round(totals[team]["xg"], 2)
        h, a = self._threat(totals[self.home_id]), self._threat(totals[self.away_id])
        value = (h - a) / (h + a + DAMPING) if h + a > 0 else 0.0
        return {
            "minute": minute, "value": round(value, 3), "window": [start, minute],
            "label": self._labels[minute] if minute < len(self._labels) else str(minute + 1),
            "home": totals[self.home_id], "away": totals[self.away_id],
        }

    def per_minute(self) -> list[dict[str, dict]]:
        """Raw counts for each elapsed minute (not windowed)."""
        return [{team: dict(c) for team, c in m.items()} for m in self._minutes]

    def series(self) -> list[dict]:
        return [self.point(m) for m in range(len(self._minutes))]
