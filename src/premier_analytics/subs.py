"""Substitution cards (SB-1..SB-7): what the player going off did, who is coming on, and what kind of change it is.

Built only from match facts and the simulated season, never from AI, so the cards are instant and can't
invent anything. Why the manager made the change is not known and is never stated.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .desk import SUBS_ALLOWED
from .overlay import display_minute
from .schema import Event

if TYPE_CHECKING:
    from .engine import MatchEngine
    from .league import League
    from .overlay import Names

# How far up the pitch each position plays: a change to a higher rank is a more attacking one.
RANK = {"GK": 0, "CB": 1, "FB": 1, "DM": 2, "CM": 3, "AM": 4, "W": 4, "ST": 5}
OFF_STATS = ("goals", "assists", "passes", "shots", "ball_wins")  # facts on a substitution moment (SB-7)
LINE_FIELDS = ("passes", "passes_completed", "shots", "xg", "goals", "assists", "tackles_won", "interceptions", "fouls")


def change_type(out_position: str, in_position: str) -> str:
    d = RANK[in_position] - RANK[out_position]
    return "like_for_like" if d == 0 else "more_attacking" if d > 0 else "more_defensive"


# (singular, plural) per stat; Arabic uses "label: n" to avoid number agreement.
_STAT_WORDS = {
    "en": {"goals": ("goal", "goals"), "assists": ("assist", "assists"), "shots": ("shot", "shots"),
           "ball_wins": ("ball win", "ball wins"), "passes": ("pass", "passes")},
    "es": {"goals": ("gol", "goles"), "assists": ("asistencia", "asistencias"), "shots": ("tiro", "tiros"),
           "ball_wins": ("recuperación", "recuperaciones"), "passes": ("pase", "pases")},
    "ar": {"goals": "الأهداف", "assists": "صناعة الأهداف", "shots": "التسديدات", "ball_wins": "استعادة الكرة",
           "passes": "التمريرات"},
}


def key_stat(n: dict, language: str) -> str:
    """The one or two numbers that sum up a player's match, e.g. "1 goal, 34 passes" (SB-7, SB-4).
    n: goals, assists, passes, shots, ball_wins (tackles won + interceptions)."""
    keys = [k for k in ("goals", "assists") if n[k] > 0]
    if n["shots"] >= 3:
        keys.append("shots")
    elif n["ball_wins"] >= 5:
        keys.append("ball_wins")
    elif not keys or n["passes"] > 0:
        keys.append("passes")
    words = _STAT_WORDS[language]
    if language == "ar":
        return "، ".join(f"{words[k]}: {n[k]}" for k in keys)
    return ", ".join(f"{n[k]} {words[k][0] if n[k] == 1 else words[k][1]}" for k in keys)


_FAN = {
    "en": {"swap": "{on} comes on for {off}", "today": "{off}: {stat} in {minutes} minutes",
           "goals": ("{on} has {n} goal this season", "{on} has {n} goals this season"),
           "assists": ("{on} has {n} assist this season", "{on} has {n} assists this season"),
           "more_attacking": "A more attacking change", "more_defensive": "A more defensive change"},
    "es": {"swap": "Entra {on} por {off}", "today": "{off}: {stat} en {minutes} minutos",
           "goals": ("{on} lleva {n} gol esta temporada", "{on} lleva {n} goles esta temporada"),
           "assists": ("{on} lleva {n} asistencia esta temporada", "{on} lleva {n} asistencias esta temporada"),
           "more_attacking": "Un cambio más ofensivo", "more_defensive": "Un cambio más defensivo"},
    "ar": {"swap": "{on} يدخل بدلاً من {off}", "today": "{off}: {stat} في {minutes} دقيقة",
           "goals": ("أهداف {on} هذا الموسم: {n}",) * 2,
           "assists": ("صناعة {on} للأهداف هذا الموسم: {n}",) * 2,
           "more_attacking": "تبديل هجومي", "more_defensive": "تبديل دفاعي"},
}


def ball_wins(line: dict) -> int:
    return line["tackles_won"] + line["interceptions"]


def fan_lines(card: dict, names: Names, language: str) -> list[str]:
    """Plain words for the fan feed (SB-4): no xG, no percentages, numbers only from the card."""
    w = _FAN[language]
    off_name, on_name = names.player(card["off"]["player_id"]), names.player(card["on"]["player_id"])
    line = card["off"]["line"]
    stat = key_stat({**line, "ball_wins": ball_wins(line)}, language)
    out = [w["swap"].format(on=on_name, off=off_name),
           w["today"].format(off=off_name, stat=stat, minutes=card["off"]["minutes"])]
    season = card["on"]["season"]
    for k in ("goals", "assists"):
        if season and season[k] > 0:
            out.append(w[k][season[k] != 1].format(on=on_name, n=season[k]))
            break
    if card["change"] in w:
        out.append(w[card["change"]])
    return out


class SubCards:
    """Follows the match and returns a card for each substitution (call after the engine has seen the event)."""

    def __init__(self, league: League, names: Names, season: dict | None = None):
        self.league = league
        self.names = names
        self.season = season
        self.came_on: dict[str, int] = {}  # player -> match clock (ms) when they came on
        self.booked: set[str] = set()
        self.used: dict[str, int] = {}

    def _season(self, team_id: str, player_id: str) -> dict | None:
        if not self.season:
            return None
        side = "home" if team_id == self.names.home_id else "away"
        return self.season[side]["players"].get(player_id)

    def observe(self, e: Event, engine: MatchEngine) -> dict | None:
        if e.type == "card":
            (self.booked.add if e.card == "yellow" else self.booked.discard)(e.player_id)
            return None
        if e.type != "substitution":
            return None
        team = e.team_id
        self.used[team] = self.used.get(team, 0) + 1
        p_off, p_on = self.league.player(e.player_out_id), self.league.player(e.player_in_id)
        stats = engine.players.get(e.player_out_id)
        line = {k: (round(getattr(stats, k), 2) if k == "xg" else getattr(stats, k)) if stats else 0 for k in LINE_FIELDS}
        if not stats:
            line["xg"] = 0.0
        card = {
            "event_id": e.id, "team_id": team, "minute": display_minute(e), "elapsed_ms": e.elapsed_ms,
            "score_home": engine.score[0], "score_away": engine.score[1],
            "subs_used": self.used[team], "subs_allowed": SUBS_ALLOWED,
            "change": change_type(p_off.position, p_on.position),
            "off": {"player_id": p_off.id, "number": p_off.number, "position": p_off.position,
                    "minutes": (e.clock_ms - self.came_on.get(p_off.id, 0)) // 60_000, "line": line,  # minutes by match clock
                    "booked": p_off.id in self.booked, "season": self._season(team, p_off.id)},
            "on": {"player_id": p_on.id, "number": p_on.number, "position": p_on.position,
                   "season": self._season(team, p_on.id)},
        }
        self.came_on[p_on.id] = e.clock_ms
        card["fan"] = {lang: fan_lines(card, self.names, lang) for lang in ("en", "es", "ar")}
        return card
