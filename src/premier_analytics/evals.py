"""Evaluation of the AI path (A-8).

`collect()` runs fixed matches through the real pipeline and records every published AI
overlay with the facts it was given. The deterministic metrics here (grounding re-check,
number density, readability, language, mode gap) need no model; the AI-judge metrics
(Foundry evaluators and an "explains why" rubric) are wired up in scripts/run_evals.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .agents import FAN_JARGON, CriticAgent, describe_facts
from .generator import generate_match
from .league import League
from .orchestrator import Orchestrator
from .overlay import Audience, Names
from .scout import Moment

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_ARABIC = re.compile(r"[؀-ۿ]")
_ES_WORDS = {"el", "la", "los", "las", "del", "con", "para", "por", "una", "un", "que", "en", "al", "y", "gol", "tiros"}
_EN_WORDS = {"the", "and", "with", "for", "a", "of", "to", "in", "on", "their", "after", "goal", "shots"}


def number_density(text: str) -> float:
    """Numbers per 100 characters."""
    return 100 * len(_NUMBER.findall(text)) / max(len(text), 1)


def _syllables(word: str) -> int:
    groups = re.findall(r"[aeiouy]+", word.lower())
    n = len(groups) - (1 if word.lower().endswith("e") and len(groups) > 1 else 0)
    return max(n, 1)


def flesch_reading_ease(text: str) -> float:
    """Classic Flesch score for English: higher is easier (60-70 is plain English)."""
    sentences = max(len(re.findall(r"[.!?]+", text)), 1)
    words = re.findall(r"[A-Za-z']+", text)
    if not words:
        return 100.0
    syllables = sum(_syllables(w) for w in words)
    return 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words))


def detect_language(text: str) -> str:
    letters = re.findall(r"[^\W\d_]", text)
    if letters and len(_ARABIC.findall(text)) / len(letters) > 0.3:
        return "ar"
    words = [w.lower() for w in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñü]+", text)]
    es = sum(w in _ES_WORDS for w in words) + 2 * len(re.findall(r"[áéíóúñ¡¿]", text))
    en = sum(w in _EN_WORDS for w in words)
    return "es" if es > en else "en"


_NOT_STATS = re.compile(r"\d+\s*-\s*\d+|\d+(?:\+\d+)?\s*'|\d+\s*(?:minutes?|mins?)\b|(?:last|first|final)\s+\d+", re.I)


def is_plain_for_fans(text: str) -> bool:
    """What the fan instructions require: no analytics jargon and at most one statistic.
    Scorelines, minutes and "the last 10 minutes" are everyday football language, not statistics."""
    lowered = text.lower()
    stats = _NUMBER.findall(_NOT_STATS.sub(" ", text))
    return len(stats) <= 1 and not any(re.search(rf"\b{re.escape(t)}\b", lowered) for t in FAN_JARGON)


def mode_gap(fan: dict, analyst: dict) -> dict:
    """For the same moment: do analysts get more numbers, and is the fan version plain?"""
    f, a = f"{fan['headline']}. {fan['body']}", f"{analyst['headline']}. {analyst['body']}"
    return {
        "more_numbers": number_density(a) > number_density(f),
        "simpler_for_fans": is_plain_for_fans(f),
    }


@dataclass
class Record:
    match: str
    moment: Moment
    audience: Audience
    headline: str
    body: str
    facts: str
    extra: dict = field(default_factory=dict)

    def row(self) -> dict:
        return {
            "match": self.match, "moment_id": self.moment.id, "kind": self.moment.kind,
            "audience": self.audience.key, "mode": self.audience.mode, "language": self.audience.language,
            # What a viewer implicitly asks of an on-screen graphic, plus the moment it is about.
            "query": "What just happened in the match, and why does it matter? "
                     + self.facts.splitlines()[1].replace("Moment: ", "Moment: "),
            "context": self.facts, "response": f"{self.headline}\n{self.body}",
            "headline": self.headline, "body": self.body,
        }


async def collect(league: League, fixtures: list[tuple[str, str, int]], audiences: list[Audience], llm,
                  critic: CriticAgent, max_pending: int = 6) -> list[Record]:
    """Play fixed matches through the real AI path and keep every published AI overlay."""
    records: list[Record] = []
    for home, away, seed in fixtures:
        match = generate_match(home, away, seed, league)
        names = Names.from_league(league, home, away)
        # Quality, not latency, is under test here, so nothing is discarded as stale.
        orch = Orchestrator(home, away, match.meta.match_id, names, audiences, llm=llm, critic=critic,
                            stale_ms=10 * 60_000)
        moments: dict[str, Moment] = {}
        for e in match.events:
            await orch.handle(e)
            for m in orch.state.moments[len(moments):]:
                moments[m.id] = m
            if len(orch._tasks) >= max_pending:  # keep within model rate limits
                await orch.drain()
        await orch.drain()
        by_key = {a.key: a for a in audiences}
        for o in orch.published:
            if o.source == "ai":
                m = moments[o.moment_id]
                records.append(Record(match.meta.match_id, m, by_key[o.audience], o.headline, o.body,
                                      describe_facts(m, names)))
    return records


def grounding_recheck(records: list[Record], critic: CriticAgent, league: League) -> float:
    """Share of published AI overlays that still pass the Critic (should be 1.0)."""
    passed = 0
    for r in records:
        home, away = r.match.split("-")[:2]
        names = Names.from_league(league, home, away)
        verdict = critic.review(r.headline, r.body, r.moment, names, audience=r.audience)
        passed += verdict.ok
    return passed / max(len(records), 1)

