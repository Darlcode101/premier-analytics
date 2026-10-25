"""Prep and storylines (PS-1..PS-3).

Before kick-off the desk gets a **brief** computed from the simulated season (earlier meetings, players to watch,
known styles; the table and form are already in the season context) and a handful of **storyline seeds**: short
facts in every language, each tied to the players and clubs it is about. A Storyline agent may pick 3-5 and
word them as storylines (Critic-checked against the seed's own numbers; the plain seed otherwise).

The commentator picks up to four, or types their own (which must name a player or club in the match, so it can
be followed). During the match the **Storyline Watcher** links moments to storylines: any moment involving a
storyline's player, or a moment that matters (severity >= 0.5) for a storyline's club. It writes a short update,
checked by the Critic; without the AI, or when the AI has nothing grounded, player storylines get a plain update
and club storylines only hear about big moments. The Producer boosts moments that feed a storyline.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from .agents import LLM, CriticAgent, _number_forms
from .languages import GENERATED, LANGS, catalogue
from .overlay import Audience, Names, display_minute, fast_overlay
from .pattern_agent import CHANNEL_WORDS
from .scout import Moment

MAX_STORYLINES = 4
MAX_SUGGESTIONS = 5
MIN_SUGGESTIONS = 3
MAX_STORY_TEXT = 120
CLUB_MOMENT = 0.5      # club storylines follow moments that matter, not every pass
CLUB_PLAIN_UPDATE = 0.8  # without the AI, club storylines only hear about big moments
# DK-12: seed wording for the catalogued languages, and the fields each kind of seed fills.
STORY_FIELDS = {"table": {"home", "hpos", "hpts", "away", "apos", "apts"}, "meeting": {"score"},
                "top_scorer": {"p", "g", "club"}, "flank": {"club", "side", "pct"}, "long_shots": {"club", "pct", "lg"},
                "high_regains": {"club", "pct", "lg"}, "playmaker": {"p", "club", "pct"}, "form": {"club", "w", "n"}}
STORY_TEMPLATES = {lang: catalogue(lang)["storylines"] for lang in GENERATED}


def _more(kind: str, **values) -> dict[str, str]:
    """A seed in the catalogued languages; a callable value is worded per language."""
    return {lang: STORY_TEMPLATES[lang][kind].format(**{k: v(lang) if callable(v) else v for k, v in values.items()})
            for lang in GENERATED}


PRONOUNS = re.compile(r"\b(he|him|his|himself|she|her|hers|herself)\b", re.IGNORECASE)


def pronoun_problems(text: str) -> list[str]:
    """Players are fictional and their gender unknown: storylines name them instead (live check 10-17)."""
    found = PRONOUNS.search(text)
    return [f"gendered pronoun '{found.group()}': use the player's name"] if found else []


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


@dataclass
class Seed:
    id: str
    kind: str
    text: dict[str, str]
    numbers: set[str]
    players: list[str] = field(default_factory=list)
    clubs: list[str] = field(default_factory=list)

    def suggestion(self, source: str = "plain", english: str | None = None) -> dict:
        return {"seed_id": self.id, "kind": self.kind, "text": {**self.text, **({"en": english} if english else {})},
                "players": self.players, "clubs": self.clubs, "source": source}


def _numbers(*values) -> set[str]:
    return set().union(*(_number_forms(v) for v in values))


def _players_to_watch(season, league, profiles, cid: str) -> list[dict]:
    squad = league.squad(cid)
    scorer = max(squad, key=lambda p: (season.goals[p.id], p.id))
    creator = max(squad, key=lambda p: (season.assists[p.id], p.id))
    out = [{"player_id": scorer.id, "why": "top_scorer", "value": season.goals[scorer.id]}]
    if season.assists[creator.id] and creator.id != scorer.id:
        out.append({"player_id": creator.id, "why": "top_assists", "value": season.assists[creator.id]})
    profile = profiles.get(cid, {})
    if profile.get("playmaker"):
        out.append({"player_id": profile["playmaker"], "why": "playmaker",
                    "value": round(100 * profile["playmaker_share"])})
    return out


def build_brief(season, league, profiles: dict, names: Names) -> dict:
    """PS-1: what the desk can't already see in the season context. Club ids, player ids and numbers only."""
    home, away = names.home_id, names.away_id
    meetings = [{"matchday": r.matchday, "home": r.home, "away": r.away, "home_goals": r.home_goals,
                 "away_goals": r.away_goals} for r in season.results if {r.home, r.away} == {home, away}]
    return {
        "meetings": meetings,
        **{side: {"players_to_watch": _players_to_watch(season, league, profiles, cid),
                  "styles": [s for s in profiles.get(cid, {}).get("styles", []) if s["kind"] != "playmaker"]}
           for side, cid in (("home", home), ("away", away))},
    }


def seeds(season, league, profiles: dict, names: Names) -> list[Seed]:
    """Storyline seeds, most useful first: each a fact in every language, with its numbers and subjects."""
    home, away = names.home_id, names.away_id
    rows = {r.club_id: r for r in season.table()}
    h, a = rows[home], rows[away]
    club = names.club
    out = [Seed("table", "table", {
        "en": f"{club(home)} ({_ordinal(h.position)}, {h.points} pts) host {club(away)} ({_ordinal(a.position)}, {a.points} pts)",
        "es": f"El {club(home)} ({h.position}.º, {h.points} pts) recibe al {club(away)} ({a.position}.º, {a.points} pts)",
        "ar": f"{club(home)} (المركز {h.position}، {h.points} نقطة) يستضيف {club(away)} (المركز {a.position}، {a.points} نقطة)",
        **_more("table", home=club(home), hpos=h.position, hpts=h.points, away=club(away), apos=a.position, apts=a.points),
    }, _numbers(h.position, h.points, a.position, a.points), clubs=[home, away])]

    meetings = [r for r in season.results if {r.home, r.away} == {home, away}]
    if meetings:
        r = meetings[-1]
        score = f"{club(r.home)} {r.home_goals}-{r.away_goals} {club(r.away)}"
        out.append(Seed("meeting", "meeting", {
            "en": f"Earlier this season: {score}", "es": f"Antes esta temporada: {score}",
            "ar": f"في وقت سابق هذا الموسم: {score}", **_more("meeting", score=score),
        }, _numbers(r.home_goals, r.away_goals), clubs=[home, away]))

    for cid in (home, away):
        watch = {w["why"]: w for w in _players_to_watch(season, league, profiles, cid)}
        top = watch["top_scorer"]
        if top["value"]:
            p, g = names.player(top["player_id"]), top["value"]
            out.append(Seed(f"top_scorer:{cid}", "top_scorer", {
                "en": f"{p} has {g} goals this season for {club(cid)}",
                "es": f"{p} lleva {g} goles esta temporada con el {club(cid)}",
                "ar": f"سجّل {p} {g} أهداف هذا الموسم مع {club(cid)}",
                **_more("top_scorer", p=p, g=g, club=club(cid)),
            }, _numbers(g), players=[top["player_id"]], clubs=[cid]))

    for cid in (home, away):
        for s in profiles.get(cid, {}).get("styles", []):
            pct, lg = round(100 * s["share"]), round(100 * s["league"]) if s.get("league") is not None else None
            if s["kind"] == "flank":
                side = {lang: CHANNEL_WORDS[lang][s["value"]] for lang in LANGS}
                text = {"en": f"{club(cid)} attack down the {side['en']}: {pct}% of their entries this season",
                        "es": f"El {club(cid)} ataca por {side['es']}: {pct}% de sus llegadas esta temporada",
                        "ar": f"{club(cid)} يهاجم عبر {side['ar']}: {pct}% من هجماته هذا الموسم",
                        **_more("flank", club=club(cid), side=side.get, pct=pct)}
            elif s["kind"] == "long_shots":
                text = {"en": f"{club(cid)} shoot from distance: {pct}% of their shots (league {lg}%)",
                        "es": f"El {club(cid)} dispara de lejos: {pct}% de sus tiros (liga {lg}%)",
                        "ar": f"{club(cid)} يسدد من بعيد: {pct}% من تسديداته (الدوري {lg}%)",
                        **_more("long_shots", club=club(cid), pct=pct, lg=lg)}
            elif s["kind"] == "high_regains":
                text = {"en": f"{club(cid)} press high: {pct}% of their ball wins in the attacking third (league {lg}%)",
                        "es": f"El {club(cid)} presiona arriba: {pct}% de sus recuperaciones en campo rival (liga {lg}%)",
                        "ar": f"{club(cid)} يضغط عاليًا: {pct}% من استعاداته في الثلث الهجومي (الدوري {lg}%)",
                        **_more("high_regains", club=club(cid), pct=pct, lg=lg)}
            elif s["kind"] == "playmaker":
                p = names.player(s["value"])
                text = {"en": f"{p} makes {club(cid)} tick: {pct}% of their passes into the final third",
                        "es": f"{p} es el motor del {club(cid)}: {pct}% de sus pases al último tercio",
                        "ar": f"{p} محرك {club(cid)}: {pct}% من تمريراته نحو الثلث الأخير",
                        **_more("playmaker", p=p, club=club(cid), pct=pct)}
                out.append(Seed(f"playmaker:{cid}", "playmaker", text, _numbers(pct), players=[s["value"]], clubs=[cid]))
                continue
            else:
                continue
            out.append(Seed(f"{s['kind']}:{cid}", s["kind"], text, _numbers(pct, *([lg] if lg is not None else [])),
                            clubs=[cid]))

    for cid in (home, away):
        form = season.form(cid)
        if form:
            w, n = form.count("W"), len(form)
            out.append(Seed(f"form:{cid}", "form", {
                "en": f"{club(cid)} have won {w} of their last {n}",
                "es": f"El {club(cid)} ha ganado {w} de sus últimos {n}",
                "ar": f"فاز {club(cid)} في {w} من آخر {n} مباريات", **_more("form", club=club(cid), w=w, n=n),
            }, _numbers(w, n), clubs=[cid]))
    return out


# ---------- PS-1: the Storyline agent ----------

class Idea(BaseModel):
    seed_id: str
    text: str = Field(description="One storyline, max 110 characters.")


class StorylineIdeas(BaseModel):
    ideas: list[Idea] = Field(description="3-5 storylines, best first.")


SUGGEST_INSTRUCTIONS = (
    "You are a football commentator's researcher, preparing storylines before kick-off. From the facts below, "
    "pick the 3-5 that make the best storylines to follow during this match and word each as a storyline a "
    "commentator can track (max 110 characters, often a question). Use only the numbers, players and clubs in "
    "the fact you are wording; refer to players by name, never by pronoun; British English, club names plural. "
    "Return the fact id for each."
)
MAX_IDEA = 110


class StorylineAgent:
    role = "storylines"

    def __init__(self, llm: LLM, critic: CriticAgent):
        self.llm = llm
        self.critic = critic
        self.model: str | None = None

    def problems(self, text: str, seed: Seed, names: Names) -> list[str]:
        involved = {names.player(p) for p in seed.players}
        return self.critic.check_text(text, "", seed.numbers, involved, names, max_headline=MAX_IDEA) + pronoun_problems(text)

    async def suggest(self, pool: list[Seed], names: Names) -> list[dict]:
        by_id = {s.id: s for s in pool}
        prompt = "\n".join(f"[{s.id}] {s.text['en']}" for s in pool)
        res = await self.llm.generate(self.role, SUGGEST_INSTRUCTIONS, prompt, StorylineIdeas)
        self.model = res.model
        out, seen = [], set()
        for idea in res.value.ideas:
            seed = by_id.get(idea.seed_id)
            if seed is None or seed.id in seen:
                continue
            seen.add(seed.id)
            ok = not self.problems(idea.text, seed, names)
            out.append(seed.suggestion("ai", idea.text) if ok else seed.suggestion())
            if len(out) == MAX_SUGGESTIONS:
                break
        for seed in pool:  # always offer a few
            if len(out) >= MIN_SUGGESTIONS:
                break
            if seed.id not in seen:
                seen.add(seed.id)
                out.append(seed.suggestion())
        return out


def plain_suggestions(pool: list[Seed]) -> list[dict]:
    return [s.suggestion() for s in pool[:MAX_SUGGESTIONS]]


# ---------- PS-2: the storylines a desk is following ----------

class Storylines:
    """Shared by every desk on the match."""

    def __init__(self, names: Names):
        self.names = names
        self.active: list[dict] = []
        self._ids = itertools.count(1)

    def _add(self, text: dict[str, str], players: list[str], clubs: list[str], source: str, seed_id: str | None) -> dict:
        if len(self.active) >= MAX_STORYLINES:
            raise ValueError(f"At most {MAX_STORYLINES} storylines at a time")
        story = {"id": f"st{next(self._ids)}", "text": text, "players": players, "clubs": clubs, "source": source,
                 "seed_id": seed_id, "updates": []}
        self.active.append(story)
        return story

    def add_suggestion(self, suggestion: dict) -> dict:
        if any(s["seed_id"] == suggestion["seed_id"] for s in self.active):
            raise ValueError("That storyline is already on the board")
        return self._add(dict(suggestion["text"]), list(suggestion["players"]), list(suggestion["clubs"]),
                         "suggested", suggestion["seed_id"])

    def subjects(self, text: str) -> tuple[list[str], list[str]]:
        """Players (full name or unique surname) and clubs named in a typed storyline."""
        lowered = text.lower()
        players = []
        surnames: dict[str, list[str]] = {}
        for pid, name in self.names.players.items():
            surnames.setdefault(name.split(" ")[-1].lower(), []).append(pid)
        for pid, name in self.names.players.items():
            surname = name.split(" ")[-1].lower()
            if name.lower() in lowered or (len(surnames[surname]) == 1 and re.search(rf"\b{re.escape(surname)}\b", lowered)):
                players.append(pid)
        clubs = [cid for cid, name in self.names.clubs.items() if re.search(rf"\b{re.escape(name.lower())}\b", lowered)]
        return players, clubs

    def add_custom(self, text: str) -> dict:
        text = " ".join(text.split())[:MAX_STORY_TEXT]
        players, clubs = self.subjects(text)
        if not players and not clubs:
            raise ValueError("A storyline must name a player or club in this match, so it can be followed")
        return self._add({lang: text for lang in LANGS}, players, clubs, "custom", None)

    def remove(self, story_id: str) -> None:
        self.active = [s for s in self.active if s["id"] != story_id]

    def relevant(self, m: Moment) -> list[dict]:
        involved = {m.player_id} | {f.value for f in m.facts if isinstance(f.value, str)}
        out = []
        for s in self.active:
            if s["players"]:
                if involved & set(s["players"]):
                    out.append(s)
            elif m.team_id in s["clubs"] and m.severity >= CLUB_MOMENT:
                out.append(s)
        return out


# ---------- PS-3: the Storyline Watcher ----------

class StorylineUpdate(BaseModel):
    text: str = Field(description="One line (max 120 characters) on how this moment moves the storyline, or NONE.")


WATCH_INSTRUCTIONS = (
    "You follow one storyline for a TV commentator. Given the storyline and a moment that has just happened, "
    "write ONE line (max 120 characters) saying how this moment moves the storyline on, using only the numbers, "
    "players and clubs in the moment's facts and the storyline. If the moment does not really bear on the "
    "storyline, answer exactly NONE. Refer to players by name, never by pronoun; British English."
)


class WatcherAgent:
    role = "storyline_watcher"

    def __init__(self, llm: LLM, critic: CriticAgent):
        self.llm = llm
        self.critic = critic
        self.model: str | None = None

    async def update(self, story: dict, m: Moment, names: Names) -> str | None:
        o = fast_overlay(m, Audience(mode="analyst", language="en"), names)
        facts = "\n".join(f"[{f.id}] {f.label} = {names.player(f.value) if isinstance(f.value, str) and f.value in names.players else f.value}"
                          for f in m.facts)
        prompt = f"STORYLINE: {story['text']['en']}\nMOMENT ({display_minute(m)}'): {o.headline}. {o.body}\nFACTS:\n{facts}"
        res = await self.llm.generate(self.role, WATCH_INSTRUCTIONS, prompt, StorylineUpdate)
        self.model = res.model
        text = (res.value.text or "").strip()
        if not text or text.upper().rstrip(".") == "NONE":
            return None
        allowed = self.critic.allowed_numbers(m) | set(re.findall(r"\d+", story["text"]["en"]))
        involved = {names.player(m.player_id)} if m.player_id else set()
        involved |= {names.player(f.value) for f in m.facts if isinstance(f.value, str) and f.value in names.players}
        involved |= {names.player(p) for p in story["players"]}
        problems = self.critic.check_text(text, "", allowed, involved, names, max_headline=MAX_STORY_TEXT)
        return None if problems or pronoun_problems(text) else text


def plain_update(m: Moment, names: Names) -> dict[str, str]:
    """The moment's own headline in each language: a storyline update that needs no AI."""
    return {lang: fast_overlay(m, Audience(mode="analyst", language=lang), names).headline for lang in LANGS}
