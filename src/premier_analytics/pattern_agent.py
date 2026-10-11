"""Pattern Analyst (PA-4, PA-6, PA-7, PA-8).

- pattern_text: plain wording for every pattern in EN / ES / AR, built only from the pattern's numbers, so the
  desk works with the AI off and the AI always has a safe fallback.
- fan_line: the same pattern in fan words, without numbers or jargon (fan app Stats card).
- PatternAnalystAgent: picks the most useful patterns for commentators and writes sharper one-line notes;
  the Critic checks every number and name, anything it rejects falls back to the plain wording.
- AlertGate: a new match pattern becomes an alert only once it has held at two checks in a row, and once.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .agents import LLM, CriticAgent, _number_forms
from .overlay import Names
from .patterns import Pattern

CHANNEL_WORDS = {
    "en": {"left": "left", "centre": "middle", "right": "right"},
    "es": {"left": "la izquierda", "centre": "el centro", "right": "la derecha"},
    "ar": {"left": "الجهة اليسرى", "centre": "العمق", "right": "الجهة اليمنى"},
}

TEXT = {
    "en": {
        ("flank", "match"): "{team} keep going down the {ch}: {count} of their {total} attacks into the final third",
        ("switch", "second_half"): "{team} have switched to the {ch} since half-time: {count} of {total} attacks",
        ("high_regains", "match"): "{team} are winning the ball high: {count} of their {total} ball wins in the attacking third",
        ("long_shots", "match"): "{team} keep shooting from distance: {count} of {total} shots from outside the box",
        ("hub", "match"): "{player} is making {team} tick: {count} of their {total} passes into the final third",
        ("counters", "match"): "{team} are dangerous on the break: {count} of {total} shots within {seconds} seconds of winning the ball",
        ("unusual", "match"): "Unusually, {team} aren't using the {ch}: {count} of {total} attacks there today, against {season_share_pct}% this season",
        ("flank", "season"): "{team} usually attack down the {ch} ({season_share_pct}% this season); today {today_count} of {today_total}",
        ("high_regains", "season"): "{team} press high: {season_share_pct}% of their ball wins come in the attacking third this season (league {league_share_pct}%); today {today_count} of {today_total}",
        ("long_shots", "season"): "{team} shoot from distance more than most: {season_share_pct}% of their shots this season (league {league_share_pct}%); today {today_count} of {today_total}",
        ("playmaker", "season"): "{player} is {team}'s playmaker: {season_share_pct}% of their passes into the final third this season; today {today_count} of {today_total}",
    },
    "es": {
        ("flank", "match"): "{team} insiste por {ch}: {count} de sus {total} llegadas al último tercio",
        ("switch", "second_half"): "{team} ha cambiado a {ch} desde el descanso: {count} de {total} llegadas",
        ("high_regains", "match"): "{team} recupera arriba: {count} de sus {total} recuperaciones en campo rival",
        ("long_shots", "match"): "{team} dispara de lejos: {count} de {total} tiros desde fuera del área",
        ("hub", "match"): "{player} es el eje de {team}: {count} de sus {total} pases al último tercio",
        ("counters", "match"): "{team} es peligroso al contragolpe: {count} de {total} tiros a menos de {seconds} segundos de recuperar",
        ("unusual", "match"): "Raro en {team}: apenas ataca por {ch} hoy, {count} de {total} llegadas (esta temporada, {season_share_pct}%)",
        ("flank", "season"): "{team} suele atacar por {ch} ({season_share_pct}% esta temporada); hoy {today_count} de {today_total}",
        ("high_regains", "season"): "{team} presiona arriba: el {season_share_pct}% de sus recuperaciones son en campo rival esta temporada (liga {league_share_pct}%); hoy {today_count} de {today_total}",
        ("long_shots", "season"): "{team} dispara de lejos más que la mayoría: {season_share_pct}% de sus tiros esta temporada (liga {league_share_pct}%); hoy {today_count} de {today_total}",
        ("playmaker", "season"): "{player} es el organizador de {team}: {season_share_pct}% de sus pases al último tercio esta temporada; hoy {today_count} de {today_total}",
    },
    "ar": {
        ("flank", "match"): "{team} يواصل الهجوم عبر {ch}: {count} من {total} هجمة نحو الثلث الأخير",
        ("switch", "second_half"): "{team} انتقل إلى {ch} منذ الاستراحة: {count} من {total} هجمة",
        ("high_regains", "match"): "{team} يستعيد الكرة في مناطق متقدمة: {count} من {total} استعادة في الثلث الهجومي",
        ("long_shots", "match"): "{team} يكثر التسديد من بعيد: {count} من {total} تسديدة من خارج المنطقة",
        ("hub", "match"): "{player} محور لعب {team}: {count} من {total} تمريرة نحو الثلث الأخير",
        ("counters", "match"): "{team} خطير في المرتدات: {count} من {total} تسديدة خلال {seconds} ثانية من استعادة الكرة",
        ("unusual", "match"): "على غير العادة، {team} لا يهاجم عبر {ch} اليوم: {count} من {total} هجمة (هذا الموسم {season_share_pct}%)",
        ("flank", "season"): "{team} يهاجم عادة عبر {ch} ({season_share_pct}% هذا الموسم)؛ اليوم {today_count} من {today_total}",
        ("high_regains", "season"): "{team} يضغط عاليًا: {season_share_pct}% من استعاداته في الثلث الهجومي هذا الموسم (الدوري {league_share_pct}%)؛ اليوم {today_count} من {today_total}",
        ("long_shots", "season"): "{team} يسدد من بعيد أكثر من غيره: {season_share_pct}% من تسديداته هذا الموسم (الدوري {league_share_pct}%)؛ اليوم {today_count} من {today_total}",
        ("playmaker", "season"): "{player} صانع ألعاب {team}: {season_share_pct}% من تمريراته نحو الثلث الأخير هذا الموسم؛ اليوم {today_count} من {today_total}",
    },
}

FAN = {
    "en": {"flank": "{team} attack mostly down the {ch}", "switch": "{team} have switched to the {ch}",
           "high_regains": "{team} are pressing high up the pitch", "long_shots": "{team} like a shot from distance",
           "hub": "{player} is running {team}'s attacks", "playmaker": "{player} is running {team}'s attacks",
           "counters": "{team} are dangerous on the break"},
    "es": {"flank": "{team} ataca sobre todo por {ch}", "switch": "{team} ahora ataca por {ch}",
           "high_regains": "{team} presiona muy arriba", "long_shots": "A {team} le gusta disparar de lejos",
           "hub": "{player} dirige los ataques de {team}", "playmaker": "{player} dirige los ataques de {team}",
           "counters": "{team} es peligroso al contragolpe"},
    "ar": {"flank": "{team} يهاجم غالبًا عبر {ch}", "switch": "{team} انتقل للهجوم عبر {ch}",
           "high_regains": "{team} يضغط في مناطق متقدمة", "long_shots": "{team} يحب التسديد من بعيد",
           "hub": "{player} يقود هجمات {team}", "playmaker": "{player} يقود هجمات {team}",
           "counters": "{team} خطير في المرتدات"},
}
# What a fan should hear first about a team: today's own patterns, then what they're known for.
FAN_ORDER = ("switch", "flank", "counters", "high_regains", "long_shots", "hub", "playmaker")


def _fields(p: Pattern, names: Names, language: str) -> dict:
    player = names.player(p.value) if p.kind in ("hub", "playmaker") else ""
    return {"team": names.club(p.team_id), "player": player,
            "ch": CHANNEL_WORDS[language].get(p.value, p.value), **p.numbers}


def pattern_text(p: Pattern, names: Names, language: str = "en") -> str:
    return TEXT[language][(p.kind, p.scope)].format(**_fields(p, names, language))


def fan_line(p: Pattern, names: Names, language: str = "en") -> str | None:
    template = FAN[language].get(p.kind)
    return template.format(**_fields(p, names, language)) if template else None


def fan_lines(patterns: list[Pattern], names: Names, language: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for kind in FAN_ORDER:
        for p in patterns:
            if p.kind == kind and p.team_id not in out:
                line = fan_line(p, names, language)
                if line:
                    out[p.team_id] = line
    return out


CONFIRMING = re.compile(r"\b(remains?|still|confirms?|confirmed|again|as usual|continues?|true to form|once more)\b", re.I)


def _contradicted_today(p: Pattern) -> bool:
    """A known style that today's numbers run well below (enough of a sample to say so)."""
    n, k = p.numbers.get("today_total", 0), p.numbers.get("today_count", 0)
    return n >= 8 and 100 * k / n < 0.6 * p.numbers.get("season_share_pct", 0)


class PatternNote(BaseModel):
    pattern_id: str = Field(description="The id of the pattern, exactly as given in brackets.")
    text: str = Field(description="One line for the commentator, at most 160 characters.")


class PatternNotes(BaseModel):
    notes: list[PatternNote] = Field(description="The 1-3 most useful patterns per team, best first.")


class Note(BaseModel):
    pattern_id: str
    team_id: str
    kind: str
    scope: str
    value: str
    text: str
    numbers: dict
    source: str  # ai | plain


INSTRUCTIONS = (
    "You are the Pattern Analyst for a TV commentator. You get statistically checked patterns for both teams: "
    "some from today's match, some describing what a club is known for this season (with today's numbers). Pick "
    "the 1-3 most useful per team (today's patterns first, then a known style that today's numbers confirm or "
    "contradict) and write each as one sharp line a commentator can say on air (max 160 characters). Use only the "
    "numbers, players and teams in the pattern you are writing about; never present a season style as today's "
    "finding, and if today's numbers fall well short of the usual style, say so (\"quiet today\") rather than "
    "\"remains\" or \"confirms\". British English. Treat club names as plural. Return the pattern id for each line."
)
MAX_NOTE = 160
PER_TEAM = 3


class PatternAnalystAgent:
    role = "pattern_analyst"
    instructions = INSTRUCTIONS

    def __init__(self, llm: LLM, critic: CriticAgent):
        self.llm = llm
        self.critic = critic
        self.model: str | None = None

    def problems(self, text: str, p: Pattern, names: Names) -> list[str]:
        allowed: set[str] = set()
        for v in p.numbers.values():
            allowed |= _number_forms(v)
        involved = {names.player(p.value)} if p.kind in ("hub", "playmaker") else set()
        problems = self.critic.check_text(text, "", allowed, involved, names, max_headline=MAX_NOTE)
        if p.scope == "season" and "today" not in text.lower() and "this season" not in text.lower():
            problems.append("a season style must be worded as a season style")
        if p.scope == "season" and _contradicted_today(p) and CONFIRMING.search(text):
            problems.append(f"today's numbers don't confirm the usual style ('{CONFIRMING.search(text).group()}')")
        return problems

    async def run(self, patterns: list[Pattern], names: Names) -> list[Note]:
        by_id = {p.id: p for p in patterns}
        prompt = "\n".join(f"[{p.id}] ({names.club(p.team_id)}, {'season' if p.scope == 'season' else 'today'}) "
                           f"{pattern_text(p, names)}" for p in patterns)
        res = await self.llm.generate(self.role, self.instructions, prompt, PatternNotes)
        self.model = res.model
        notes, per_team = [], {}
        for n in res.value.notes:
            p = by_id.get(n.pattern_id)
            if p is None or per_team.get(p.team_id, 0) >= PER_TEAM:
                continue
            per_team[p.team_id] = per_team.get(p.team_id, 0) + 1
            ok = not self.problems(n.text, p, names)
            notes.append(_note(p, n.text if ok else pattern_text(p, names), "ai" if ok else "plain"))
        return notes or plain_notes(patterns, names, "en")


def _note(p: Pattern, text: str, source: str) -> Note:
    return Note(pattern_id=p.id, team_id=p.team_id, kind=p.kind, scope=p.scope, value=p.value, text=text,
                numbers=p.numbers, source=source)


def plain_notes(patterns: list[Pattern], names: Names, language: str) -> list[Note]:
    out, per_team = [], {}
    for p in patterns:
        if per_team.get(p.team_id, 0) < PER_TEAM:
            per_team[p.team_id] = per_team.get(p.team_id, 0) + 1
            out.append(_note(p, pattern_text(p, names, language), "plain"))
    return out


class AlertGate:
    """PA-6: alert on a match pattern once it has held at two checks in a row, and only once."""

    def __init__(self):
        self.previous: set[str] = set()
        self.alerted: set[str] = set()

    def update(self, current: set[str]) -> set[str]:
        fresh = (current & self.previous) - self.alerted
        self.alerted |= fresh
        self.previous = set(current)
        return fresh
