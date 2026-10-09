"""The AI path: Explainer -> Critic -> Personaliser -> Critic -> Translator -> Critic.

Each agent has one job and a typed output. Agents talk to models through the small `LLM`
protocol, so the same code runs against Microsoft Foundry (via Microsoft Agent Framework)
in production and against `FakeLLM` in tests. `ResilientLLM` adds timeouts, a retry and a
fallback model (A-5). The Critic is deterministic: it checks every number, player and club
against the moment's facts before anything can reach the screen (E-2, A-6).
"""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, Field

from .overlay import MAX_BODY, MAX_HEADLINE, Audience, Names, display_minute
from .scout import Moment

T = TypeVar("T", bound=BaseModel)

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "ar": "Arabic"}
FAN_JARGON = ("xg", "ppda", "field tilt", "progressive", "expected goals", "tempo")


# ---------- typed agent outputs ----------

class Explanation(BaseModel):
    headline: str = Field(description="At most 50 characters.")
    why: str = Field(description="Why this moment matters, at most 160 characters.")
    evidence: list[str] = Field(description="IDs of the facts relied on, e.g. m-mo0001-f2.")


class Personalised(BaseModel):
    headline: str = Field(description="At most 55 characters.")
    body: str = Field(description="At most 170 characters.")


# ---------- model access ----------

@dataclass
class Attempt:
    model: str
    outcome: str  # ok | timeout | error
    ms: float
    detail: str = ""


@dataclass
class LLMResult(Generic[T]):
    value: T
    model: str
    ms: float
    attempts: list[Attempt] = field(default_factory=list)


class LLM(Protocol):
    name: str

    async def generate(self, role: str, instructions: str, prompt: str, schema: type[T]) -> LLMResult[T]: ...


class AllModelsFailed(RuntimeError):
    def __init__(self, attempts: list[Attempt]):
        super().__init__("; ".join(f"{a.model}:{a.outcome}" for a in attempts))
        self.attempts = attempts


@dataclass
class FakeCall:
    role: str
    instructions: str
    prompt: str


class FakeLLM:
    """Scriptable stand-in for a model: per-role responders, optional delay, call log."""

    def __init__(self, responders: dict[str, Callable[[str], Any]], delay: float | dict[str, float] = 0.0,
                 name: str = "fake"):
        self.responders = responders
        self.delay = delay
        self.name = name
        self.calls: list[FakeCall] = []

    async def generate(self, role, instructions, prompt, schema):
        self.calls.append(FakeCall(role, instructions, prompt))
        delay = self.delay.get(role, 0.0) if isinstance(self.delay, dict) else self.delay
        start = time.perf_counter()
        if delay:
            await asyncio.sleep(delay)
        value = self.responders[role](prompt)
        if isinstance(value, Exception):
            raise value
        return LLMResult(value=value, model=self.name, ms=(time.perf_counter() - start) * 1000)

    def count(self, role: str) -> int:
        return sum(c.role == role for c in self.calls)


class AgentFrameworkLLM:
    """Runs each role as a Microsoft Agent Framework agent on a Foundry model deployment."""

    def __init__(self, deployment: str, endpoint: str, api_key: str):
        from agent_framework.openai import OpenAIChatCompletionClient

        self.name = deployment
        self._client = OpenAIChatCompletionClient(
            model=deployment, api_key=api_key, base_url=endpoint.rstrip("/") + "/openai/v1/",
        )
        self._agents: dict[tuple[str, str], Any] = {}

    def _agent(self, role: str, instructions: str):
        from agent_framework import Agent

        key = (role, instructions)
        if key not in self._agents:
            self._agents[key] = Agent(client=self._client, name=role, instructions=instructions)
        return self._agents[key]

    async def generate(self, role, instructions, prompt, schema):
        start = time.perf_counter()
        response = await self._agent(role, instructions).run(prompt, options={"response_format": schema})
        value = response.value
        if value is None:
            value = schema.model_validate_json(response.text)
        return LLMResult(value=value, model=self.name, ms=(time.perf_counter() - start) * 1000)


class ResilientLLM:
    """Primary model with a per-call timeout and retries, then a fallback model."""

    def __init__(self, primary: LLM, fallback: LLM | None, timeout_s: float = 3.0, retries: int = 1):
        self.primary, self.fallback = primary, fallback
        self.timeout_s, self.retries = timeout_s, retries
        self.name = f"{primary.name}|{fallback.name if fallback else '-'}"

    async def generate(self, role, instructions, prompt, schema):
        attempts: list[Attempt] = []
        plan = [self.primary] * (1 + self.retries) + ([self.fallback] if self.fallback else [])
        for model in plan:
            start = time.perf_counter()
            try:
                res = await asyncio.wait_for(model.generate(role, instructions, prompt, schema), self.timeout_s)
            except TimeoutError:
                attempts.append(Attempt(model.name, "timeout", (time.perf_counter() - start) * 1000))
                continue
            except Exception as e:  # any model failure moves on to the next option
                attempts.append(Attempt(model.name, "error", (time.perf_counter() - start) * 1000, repr(e)[:200]))
                continue
            attempts.append(Attempt(model.name, "ok", res.ms))
            res.attempts = attempts
            return res
        raise AllModelsFailed(attempts)


# ---------- context ----------

def _display(value: Any, names: Names) -> str:
    if isinstance(value, str) and value in names.players:
        return names.player(value)
    if isinstance(value, str) and value in names.clubs:
        return names.club(value)
    return str(value)


def describe_facts(m: Moment, names: Names) -> str:
    team = names.club(m.team_id) if m.team_id else "-"
    player = names.player(m.player_id) if m.player_id else "-"
    lines = [
        f"Match: {names.club(names.home_id)} (home) v {names.club(names.away_id)} (away).",
        f"Moment: {m.kind.replace('_', ' ')} at {display_minute(m)}' (half {m.period}). Team: {team}. Player: {player}.",
        "Facts:",
    ]
    for f in m.facts:
        subject = f" ({_display(f.subject, names)})" if f.subject and f.subject not in (m.player_id,) else ""
        lines.append(f"[{f.id}] {f.label.replace('_', ' ')} = {_display(f.value, names)}{subject}")
    return "\n".join(lines)


def describe_audience(a: Audience, names: Names) -> str:
    parts = ["casual fan" if a.mode == "fan" else "data analyst"]
    if a.club_id:
        parts.append(f"supports {names.club(a.club_id)}")
    if a.player_id:
        parts.append(f"is following {names.player(a.player_id)} all match")
    return "Audience: " + ", ".join(parts) + "."


# ---------- agents ----------

class ExplainerAgent:
    role = "explainer"
    instructions = (
        "You are the Explainer in a live football broadcast graphics system. You receive verified facts about "
        "one match moment. Explain in British English WHY it matters (consequence, context, pattern) instead of "
        "restating what happened. Use only numbers, players and teams that appear in the facts; never invent "
        "statistics or describe quality the facts don't support. Headline at most 50 characters, why at most "
        "160 characters. List the IDs of the facts you used in evidence."
    )

    def __init__(self, llm: LLM):
        self.llm = llm

    async def run(self, m: Moment, names: Names, feedback: str = "") -> Explanation:
        return (await self.run_full(m, names, feedback)).value

    async def run_full(self, m: Moment, names: Names, feedback: str = "") -> LLMResult[Explanation]:
        prompt = describe_facts(m, names)
        if feedback:
            prompt += f"\n\nYour previous answer was rejected: {feedback}. Fix it."
        return await self.llm.generate(self.role, self.instructions, prompt, Explanation)


class PersonaliserAgent:
    role = "personaliser"
    instructions = (
        "You are the Personaliser for live football graphics. Rewrite an explanation for one audience, in "
        "British English. For a casual fan: warm, simple and vivid, no jargon (never say xG, PPDA, field tilt "
        "or tempo), at most one number. For a data analyst: precise and tactical, two or three numbers, xG "
        "allowed. If the viewer supports a club, frame it from their side. If they follow a player, mention "
        "that player when the facts involve them. Use only facts given. Headline at most 55 characters, body "
        "at most 170 characters."
    )

    def __init__(self, llm: LLM):
        self.llm = llm

    async def run(self, exp: Explanation, m: Moment, names: Names, a: Audience, feedback: str = "") -> Personalised:
        return (await self.run_full(exp, m, names, a, feedback)).value

    async def run_full(self, exp, m, names, a, feedback=""):
        prompt = (
            f"{describe_audience(a, names)}\n\nExplanation headline: {exp.headline}\nExplanation: {exp.why}\n\n"
            f"{describe_facts(m, names)}"
        )
        if feedback:
            prompt += f"\n\nYour previous answer was rejected: {feedback}. Fix it."
        return await self.llm.generate(self.role, self.instructions, prompt, Personalised)


class TranslatorAgent:
    role = "translator"
    instructions = (
        "You translate short on-screen football graphics. Keep player and club names exactly as written, in "
        "Latin script. Keep every number as Western digits. Natural broadcast style for the target language. "
        "Headline at most 55 characters, body at most 170 characters."
    )

    def __init__(self, llm: LLM):
        self.llm = llm

    async def run(self, text: Personalised, language: str) -> Personalised:
        return (await self.run_full(text, language)).value

    async def run_full(self, text: Personalised, language: str):
        prompt = f"Target language: {LANGUAGE_NAMES[language]}.\nHeadline: {text.headline}\nBody: {text.body}"
        return await self.llm.generate(self.role, self.instructions, prompt, Personalised)


# ---------- critic ----------

_DIGIT_MAP = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹٫", "01234567890123456789.")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _normalise_numbers(text: str) -> str:
    text = text.translate(_DIGIT_MAP)
    return re.sub(r"(?<=\d),(?=\d)", ".", text)  # Spanish decimal comma


def _number_forms(value: Any) -> set[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return set()
    forms = {str(value), str(round(value)), f"{value:.1f}", f"{value:.2f}"}
    if 0 < value < 1:
        forms |= {str(round(value * 100)), f"{value * 100:.1f}"}
    if isinstance(value, float) and value >= 1:
        forms.add(str(int(value)))
    return {f.rstrip("0").rstrip(".") if "." in f else f for f in forms}


@dataclass
class Verdict:
    ok: bool
    problems: list[str]


class CriticAgent:
    """Deterministic fact-checker. Rejects anything not supported by the moment's facts."""

    role = "critic"

    def __init__(self, league_player_names: set[str], league_club_names: set[str]):
        self.league_players = league_player_names
        self.league_clubs = league_club_names

    def allowed_numbers(self, m: Moment) -> set[str]:
        allowed: set[str] = set()
        for f in m.facts:
            allowed |= _number_forms(f.value)
        allowed |= set(_NUMBER.findall(display_minute(m))) | {display_minute(m), "45", "90"}
        return allowed

    def review(self, headline: str, body: str, m: Moment, names: Names, evidence: list[str] | None = None,
               audience: Audience | None = None) -> Verdict:
        problems: list[str] = []
        text = f"{headline}\n{body}"
        if not headline.strip() or len(headline) > MAX_HEADLINE:
            problems.append(f"headline must be 1-{MAX_HEADLINE} characters")
        if len(body) > MAX_BODY:
            problems.append(f"body must be at most {MAX_BODY} characters")
        if evidence is not None:
            ids = {f.id for f in m.facts}
            if not evidence or not set(evidence) <= ids:
                problems.append("evidence must list fact IDs from this moment")

        allowed = self.allowed_numbers(m)
        for n in _NUMBER.findall(_normalise_numbers(text)):
            norm = n.rstrip("0").rstrip(".") if "." in n else n
            if norm not in allowed:
                problems.append(f"number {n} is not in the facts")

        involved = {names.player(m.player_id)} if m.player_id else set()
        involved |= {names.player(f.value) for f in m.facts if isinstance(f.value, str) and f.value in names.players}
        if audience and audience.player_id:
            involved.add(names.player(audience.player_id))
        involved_surnames = {n.split(" ", 1)[-1] for n in involved}
        for name in sorted(self.league_players - involved):
            surname = name.split(" ", 1)[-1]
            if name in text or (surname not in involved_surnames and re.search(rf"\b{re.escape(surname)}\b", text)):
                problems.append(f"player {name} is not part of this moment")

        match_clubs = {names.club(names.home_id), names.club(names.away_id)}
        for club in sorted(self.league_clubs - match_clubs):
            if club in text:
                problems.append(f"club {club} is not in this match")

        if audience is not None and audience.mode == "fan":
            lowered = text.lower()
            for term in FAN_JARGON:
                if re.search(rf"\b{re.escape(term)}\b", lowered):
                    problems.append(f"jargon '{term}' is not for casual fans")
        return Verdict(ok=not problems, problems=problems)
