"""Live fact-check (FC-1..FC-3): what the commentator says, checked against the match.

Code computes, the model explains: the **Claim agent** (AI) only turns a spoken or typed line into structured
claims (who, which stat, what number, from which minute). The **Fact-checker** is plain code: it looks each claim
up with the same match tools the Match Analyst and the MCP server use and compares exactly (small tolerances for
xG and possession). Only clear errors become flags; claims the data can't settle are left alone. Nothing said is
stored or logged: each line is checked and dropped.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from .agents import _DIGIT_MAP, LLM
from .match_analyst import summary
from .mcp_server import PLAYER_METRICS, MatchTools
from mcp.server.fastmcp.exceptions import ToolError

Metric = Literal["goals", "assists", "shots", "shots_on_target", "xg", "passes", "passes_completed", "tackles_won",
                 "interceptions", "fouls", "corners", "yellow_cards", "red_cards", "possession_pct"]
TOLERANCE = {"xg": 0.05, "possession_pct": 2.0}
# What a player's match line holds (beyond the tools' PLAYER_METRICS: passes, fouls, cards; 10-25)
PLAYER_LINE = ("goals", "assists", "shots", "xg", "passes", "passes_completed", "tackles_won", "interceptions", "fouls",
               "yellow_cards", "red_cards")
MAX_LINE = 500

_NUMBER_WORDS = re.compile(
    r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred|percent|per cent|half|dozen|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|"
    r"tenth|twice|brace|hat-trick|"
    r"uno|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|veinte|treinta|cuarenta|cincuenta|sesenta|setenta|"
    r"ochenta|noventa|cien|ciento|mitad|primer|primero|segundo|tercer|tercero)\b", re.IGNORECASE)  # 10-25: + sixty… percent


def worth_checking(line: str) -> bool:
    """Only lines with a number in them can hold a checkable stat (most commentary costs nothing)."""
    text = line.translate(_DIGIT_MAP)
    return bool(re.search(r"\d", text) or _NUMBER_WORDS.search(text))


class Claim(BaseModel):
    quote: str = Field(description="The words that make the claim, as said.")
    subject: str = Field(description="The player or club the claim is about, as named.")
    metric: Metric
    value: float
    since_minute: int | None = Field(None, description="Only if a starting minute was said (second half = 46).")


class Claims(BaseModel):
    claims: list[Claim] = Field(default_factory=list)


CLAIM_INSTRUCTIONS = (
    "You listen to a TV commentator during a live match and pick out each checkable statistical claim about this "
    "match: a player or club, one of the listed stats, and the number claimed. 'Third shot' means 3 shots; 'a "
    "brace' means 2 goals; a scoreline gives each club's goals. Only set since_minute if the commentator said "
    "from when (second half = 46); 'since he came on' needs none, because a substitute's figures already start "
    "then. Cards: 'booked' or 'a yellow' counts yellow_cards ('booked twice' = 2), 'sent off' is red_cards 1. "
    "Always give the player or club by name, never 'the opponents' (in a scoreline, each club is named in "
    "the match). Ignore opinions, history, other matches, and anything without a number. Return an empty list when "
    "there is nothing to check."
)


class ClaimAgent:
    role = "claims"

    def __init__(self, llm: LLM):
        self.llm = llm
        self.model: str | None = None

    async def extract(self, line: str, language: str) -> list[Claim]:
        res = await self.llm.generate(self.role, CLAIM_INSTRUCTIONS, f"Commentator ({language}): {line[:MAX_LINE]}", Claims)
        self.model = res.model
        return res.value.claims


class FactChecker:
    """Deterministic: looks claims up with the match tools and compares."""

    def __init__(self, tools: MatchTools):
        self.tools = tools
        self.state = tools.state

    def check(self, c: Claim) -> dict | None:
        """{verdict: correct|wrong, actual, subject, ...}, or None when the data can't settle it."""
        args: dict = {}
        try:
            try:
                pid = self.state.player_id(c.subject)
            except ToolError:
                pid = None
            if pid is not None:
                if c.metric not in PLAYER_LINE:
                    return None
                name = self.state.names.player(pid)
                args = {"player": name, **({"since_minute": c.since_minute} if c.since_minute else {})}
                if c.metric in PLAYER_METRICS:
                    tool, result = "get_player_stats", self.tools.get_player_stats(name, c.since_minute)
                else:
                    tool, result = "player_line", self._player_line(pid, name, c.metric, c.since_minute)
                    if result is None:
                        return None
            else:
                tid = self.state.team_id(c.subject)
                if c.since_minute is not None and c.metric not in PLAYER_METRICS:
                    return None
                name = self.state.names.club(tid)
                tool, args = "get_team_stats", {"team": name, **({"since_minute": c.since_minute} if c.since_minute else {})}
                result = self.tools.get_team_stats(name, c.since_minute)
        except ToolError:
            return None
        actual = result.get(c.metric)
        if not isinstance(actual, (int, float)):
            return None
        ok = abs(actual - c.value) <= TOLERANCE.get(c.metric, 0) + 1e-9
        return {"verdict": "correct" if ok else "wrong", "subject": name, "metric": c.metric, "claimed": c.value,
                "actual": actual, "since_minute": c.since_minute, "quote": c.quote,
                "evidence": summary({"tool": tool, "args": args, "result": result})}


    def _player_line(self, pid: str, name: str, metric: str, since: int | None) -> dict | None:
        """Passes, fouls and cards straight from the player's line. A second yellow is recorded as a red card,
        so bookings count the yellow plus any second yellow ('booked twice')."""
        now = self.tools.engine.players.get(pid)
        data = now.model_dump() if now else {}
        before: dict = {}
        if since is not None:
            then = self.state.players_at(since)
            if then is None:
                return None
            before = then.get(pid, {})
        value = data.get(metric, 0) - before.get(metric, 0)
        if metric == "yellow_cards":
            start = (2 if since and since > 45 else 1, ((since or 1) - 1) * 60_000)
            value += sum(1 for m in self.state.moments if m.kind == "red_card" and m.player_id == pid
                         and any(f.label == "card" and f.value == "second_yellow" for f in m.facts)
                         and (m.period, m.clock_ms) >= start)
        return {"name": name, metric: value}


# ---------- the flag the commentator sees ----------

_WORDS = {
    "en": {"goals": ("goal", "goals"), "assists": ("assist", "assists"), "shots": ("shot", "shots"),
           "shots_on_target": ("shot on target", "shots on target"), "xg": ("xG", "xG"), "passes": ("pass", "passes"),
           "passes_completed": ("completed pass", "completed passes"), "tackles_won": ("tackle won", "tackles won"),
           "interceptions": ("interception", "interceptions"), "fouls": ("foul", "fouls"), "corners": ("corner", "corners"),
           "yellow_cards": ("yellow card", "yellow cards"), "red_cards": ("red card", "red cards"),
           "possession_pct": ("% possession", "% possession")},
    "es": {"goals": ("gol", "goles"), "assists": ("asistencia", "asistencias"), "shots": ("tiro", "tiros"),
           "shots_on_target": ("tiro a puerta", "tiros a puerta"), "xg": ("xG", "xG"), "passes": ("pase", "pases"),
           "passes_completed": ("pase completado", "pases completados"), "tackles_won": ("entrada ganada", "entradas ganadas"),
           "interceptions": ("intercepción", "intercepciones"), "fouls": ("falta", "faltas"), "corners": ("córner", "córners"),
           "yellow_cards": ("amarilla", "amarillas"), "red_cards": ("roja", "rojas"),
           "possession_pct": ("% de posesión", "% de posesión")},
    "ar": {"goals": "الأهداف", "assists": "صناعة الأهداف", "shots": "التسديدات", "shots_on_target": "التسديدات على المرمى",
           "xg": "xG", "passes": "التمريرات", "passes_completed": "التمريرات المكتملة", "tackles_won": "الالتحامات الناجحة",
           "interceptions": "الاعتراضات", "fouls": "الأخطاء", "corners": "الركنيات", "yellow_cards": "البطاقات الصفراء",
           "red_cards": "البطاقات الحمراء", "possession_pct": "الاستحواذ %"},
}


def _num(v: float, metric: str) -> str:
    if metric == "xg":
        return f"{v:.2f}"
    return str(round(v))


def _stated(v: dict, language: str) -> str:
    """'Zane Kowalczyk: 1 shot' (since a minute, if the claim was)."""
    actual, metric, since = _num(v["actual"], v["metric"]), v["metric"], v["since_minute"]
    words = _WORDS[language][metric]
    if language == "ar":
        scope = f" منذ الدقيقة {since}" if since else ""
        return f"{v['subject']}: {words} {actual}{scope}"
    word = words[0] if actual == "1" else words[1]
    joined = f"{actual}{word}" if word.startswith("%") else f"{actual} {word}"
    scope = (f" desde el {since}'" if language == "es" else f" since {since}'") if since else ""
    return f"{v['subject']}: {joined}{scope}"


def flag_text(v: dict, language: str) -> str:
    """'Zane Kowalczyk: 1 shot, not 3' — the right number first, then what was said."""
    claimed = _num(v["claimed"], v["metric"])
    return f"{_stated(v, language)}{'، وليس' if language == 'ar' else ', no' if language == 'es' else ', not'} {claimed}"


def confirm_text(v: dict, language: str) -> str:
    """A correct claim, confirmed: 'Zane Kowalczyk: 1 goal' (10-25: correct claims were silent)."""
    return _stated(v, language)
