"""The Producer (GP-1..GP-6): what the commentator should say next, and when.

Every other agent produces talking points (moment explanations, pattern alerts, substitution cards; later
storyline updates and fact flags). The Producer ranks them by rules (importance x freshness, with boosts for
real-world context and storylines, never repeating what the commentator has used) and puts the best one
**on air** at natural stoppages, with how long the break usually lasts. In open play it shows what is
**up next**. Rules decide, so it is instant, testable and works with the AI off; an AI producer may add one
sentence of angle when a cue goes on air, checked by the Critic like everything else (GP-5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from .agents import LLM, CriticAgent
from .overlay import Names
from .schema import Event

MIN = 60_000

# Typical length of each stoppage in the simulation, in seconds (measured over 40 matches; tests keep them
# within 35 % of the median). Throw-ins (~17 s, ~36 a match) and the corner kick itself are not breaks.
BREAK_WINDOWS_S: dict[str, int | None] = {
    "goal": 75, "penalty": 75, "free_kick": 40, "card": 35, "substitution": 30, "goal_kick": 30,
    "half_time": 900, "full_time": None,
}
RESUME = frozenset({"pass", "shot", "kickoff"})

FRESH_MIN = 2.0                      # minutes at full value
HALF_LIFE_MIN = {"pattern": 15.0}     # patterns stay relevant longer than single moments
DEFAULT_HALF_LIFE_MIN = 6.0
STALE_MIN = {"pattern": 40.0}
DEFAULT_STALE_MIN = 25.0
CONTEXT_BOOST = 0.15
STORYLINE_BOOST = 0.3
BIG_MOMENT = 0.8


def break_of(e: Event) -> str | None:
    """The kind of stoppage an event starts, if any."""
    if e.type == "foul":
        return "free_kick"
    if e.type in ("goal", "penalty", "card", "substitution"):
        return e.type
    if e.type == "possession_change" and e.cause == "goal_kick":
        return "goal_kick"
    if e.type == "period_end":
        return "half_time" if e.period == 1 else "full_time"
    return None


@dataclass
class Candidate:
    """One talking point an agent produced."""
    ref: str                 # moment id, pattern id or incident id: what the desk shows
    kind: str                # moment | pattern | sub | storyline | fact
    label: str               # moment kind, pattern kind …
    source: str              # the agent it came from
    importance: float        # 0-1
    elapsed_ms: int
    team_id: str | None = None
    minute: str = ""
    has_context: bool = False
    storyline: str | None = None
    text: str = ""           # English summary, for the AI producer
    numbers: set[str] = field(default_factory=set)
    players: set[str] = field(default_factory=set)


class Cue(BaseModel):
    id: int
    ref: str
    kind: str
    label: str
    source: str
    team_id: str | None = None
    minute: str = ""
    reasons: list[str]
    state: Literal["on_air", "up_next"]
    break_kind: str | None = None
    window_s: int | None = None
    storyline: str | None = None  # PS-3: the storyline this talking point feeds


class Producer:
    def __init__(self):
        self.pool: dict[str, Candidate] = {}
        self.used: set[str] = set()
        self.current: Cue | None = None
        self.break_kind: str | None = None
        self.now_ms = 0
        self.version = 0  # bumps on every change, including the cue clearing
        self._count = 0

    # ---------- inputs ----------

    def offer(self, c: Candidate) -> None:
        old = self.pool.get(c.ref)
        if old is not None and old.has_context:
            c.has_context = True
        self.pool[c.ref] = c

    def mark_context(self, ref: str) -> None:
        if ref in self.pool:
            self.pool[ref].has_context = True

    def mark_storyline(self, ref: str, storyline: str) -> None:
        """PS-3: this talking point feeds a storyline the commentator is following."""
        if ref in self.pool:
            self.pool[ref].storyline = storyline

    def mark_used(self, ref: str, used: bool) -> Cue | None:
        (self.used.add if used else self.used.discard)(ref)
        return self._repick()

    def observe(self, e: Event) -> Cue | None:
        """Follow play; returns the new cue when it changes."""
        self.now_ms = max(self.now_ms, e.elapsed_ms)
        kind = break_of(e)
        if kind is not None:
            self.break_kind = kind
        elif e.type in RESUME:
            self.break_kind = None
        return self._repick()

    # ---------- ranking ----------

    def _age(self, c: Candidate) -> float:
        return max(0.0, (self.now_ms - c.elapsed_ms) / MIN)

    def score(self, c: Candidate) -> float | None:
        """Importance x freshness plus boosts; None once stale or used."""
        if c.ref in self.used:
            return None
        age = self._age(c)
        if age > STALE_MIN.get(c.kind, DEFAULT_STALE_MIN):
            return None
        fresh = 1.0 if age <= FRESH_MIN else 0.5 ** ((age - FRESH_MIN) / HALF_LIFE_MIN.get(c.kind, DEFAULT_HALF_LIFE_MIN))
        return c.importance * fresh + CONTEXT_BOOST * c.has_context + STORYLINE_BOOST * bool(c.storyline)

    def ranked(self) -> list[Candidate]:
        scored = [(s, c) for c in self.pool.values() if (s := self.score(c)) is not None]
        return [c for _, c in sorted(scored, key=lambda sc: (-sc[0], -sc[1].elapsed_ms, sc[1].ref))]

    def reasons(self, c: Candidate) -> list[str]:
        out = []
        if c.importance >= BIG_MOMENT:
            out.append("big_moment")
        if self._age(c) <= FRESH_MIN:
            out.append("fresh")
        if c.has_context:
            out.append("context")
        if c.storyline:
            out.append("storyline")
        if c.kind == "pattern":
            out.append("pattern")
        return out

    def _repick(self) -> Cue | None:
        ranked = self.ranked()
        best = ranked[0] if ranked else None
        if best is None:
            if self.current is not None:
                self.current = None
                self.version += 1
            return None
        state = "on_air" if self.break_kind else "up_next"
        cur = self.current
        if cur is not None and (cur.ref, cur.state, cur.break_kind, cur.storyline) == \
                (best.ref, state, self.break_kind, best.storyline):
            return None
        self._count += 1
        self.version += 1
        self.current = Cue(
            id=self._count, ref=best.ref, kind=best.kind, label=best.label, source=best.source, team_id=best.team_id,
            minute=best.minute, reasons=self.reasons(best), state=state, break_kind=self.break_kind,
            window_s=BREAK_WINDOWS_S.get(self.break_kind) if self.break_kind else None, storyline=best.storyline,
        )
        return self.current


# ---------- GP-5: the AI producer's note ----------

class ProducerNote(BaseModel):
    text: str = Field(description="One sentence (max 140 characters) the commentator could add on air, or NONE.")


INSTRUCTIONS = (
    "You are the producer in a TV gallery, speaking in the commentator's ear. You get the talking point going on "
    "air now and a few others that are still open, each with its facts. If there is a genuinely useful angle to "
    "add, such as a link between the on-air point and another open one, or what it means for the match, write ONE "
    "short sentence (max 140 characters) the commentator could say. Use only numbers, players and clubs that "
    "appear in the items. If there is nothing genuinely useful to add, answer exactly NONE. British English; "
    "treat club names as plural."
)
MAX_NOTE = 140


class ProducerAgent:
    role = "producer"
    instructions = INSTRUCTIONS

    def __init__(self, llm: LLM, critic: CriticAgent):
        self.llm = llm
        self.critic = critic
        self.model: str | None = None

    @staticmethod
    def _line(c: Candidate) -> str:
        return f"[{c.ref}] {c.minute}' {c.text}".strip()

    def problems(self, text: str, item: Candidate, others: list[Candidate], names: Names) -> list[str]:
        allowed = set().union(item.numbers, *(o.numbers for o in others))
        players = set().union(item.players, *(o.players for o in others))
        return self.critic.check_text(text, "", allowed, players, names, max_headline=MAX_NOTE)

    async def note(self, item: Candidate, others: list[Candidate], names: Names) -> str | None:
        """One grounded sentence, or None when there is nothing useful (or it fails the Critic)."""
        others = others[:3]
        prompt = "ON AIR NOW:\n" + self._line(item) + "\nSTILL OPEN:\n" + ("\n".join(map(self._line, others)) or "-")
        res = await self.llm.generate(self.role, self.instructions, prompt, ProducerNote)
        self.model = res.model
        text = (res.value.text or "").strip()
        if not text or text.upper().rstrip(".") == "NONE":
            return None
        return None if self.problems(text, item, others, names) else text
