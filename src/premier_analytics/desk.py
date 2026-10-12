"""Deterministic data for the commentator desk (CD-5..CD-8, CD-11): the incident feed and
"last 10 minutes" figures. Built from match events only, never from AI, so the desk keeps
working when the models are off or down.
"""
from __future__ import annotations

from .engine import BIG_CHANCE_XG, ShotMetrics
from .overlay import display_minute
from .schema import Event

SUBS_ALLOWED = 5
ADDITIVE = ("goals", "shots", "shots_on_target", "big_chances", "xg", "passes", "passes_completed",
            "final_third_passes", "tackles_won", "interceptions", "fouls", "yellow_cards", "red_cards", "corners")


class Incidents:
    """Turns events into one-line incidents: goals, cards, substitutions, penalties, big chances, woodwork."""

    def __init__(self):
        self._set_piece: dict[str, str | None] = {}

    def observe(self, e: Event, metric=None) -> dict | None:
        base = {"id": f"inc-{e.id}", "event_id": e.id, "minute": display_minute(e), "elapsed_ms": e.elapsed_ms,
                "period": e.period, "team_id": e.team_id, "player_id": e.player_id}
        if e.type == "shot":
            self._set_piece[e.id] = e.set_piece
        if e.type == "goal":
            return {**base, "kind": "goal", "assist_id": e.assist_id, "set_piece": self._set_piece.get(e.related_event_id),
                    "score_home": e.score_home, "score_away": e.score_away}
        if e.type == "penalty":
            return {**base, "kind": "penalty"}
        if e.type == "card":
            return {**base, "kind": e.card}
        if e.type == "substitution":
            return {**base, "kind": "sub", "player_id": e.player_in_id,
                    "player_in_id": e.player_in_id, "player_out_id": e.player_out_id}
        if e.type == "shot" and isinstance(metric, ShotMetrics):
            if e.outcome == "woodwork":
                return {**base, "kind": "woodwork", "xg": round(metric.xg, 2)}
            if e.outcome != "goal" and metric.xg >= BIG_CHANCE_XG:
                return {**base, "kind": "big_chance", "xg": round(metric.xg, 2), "outcome": e.outcome,
                        "set_piece": e.set_piece}
        return None


def last_window(now: dict, then: dict | None, now_ms: int, then_ms: int) -> dict:
    """Team figures between two snapshots of running totals (then=None: since kick-off)."""
    then = then or {}
    out = {k: now.get(k, 0) - then.get(k, 0) for k in ADDITIVE if k in now}
    if "xg" in out:
        out["xg"] = round(out["xg"], 3)
    passes = out.get("passes", 0)
    out["pass_accuracy"] = out.get("passes_completed", 0) / passes if passes else 0.0
    span = now_ms - then_ms
    if span > 0 and then:
        held = now["possession_pct"] * now_ms - then["possession_pct"] * then_ms
        out["possession_pct"] = max(0.0, min(100.0, held / span))
    else:
        out["possession_pct"] = now.get("possession_pct", 50.0)
    return out
