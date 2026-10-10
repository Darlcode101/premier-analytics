"""The AI path: Explainer -> Critic -> Personaliser -> Critic -> Translator -> Critic.

Each agent has one job and a typed output. Agents talk to models through the small `LLM`
protocol, so the same code runs against Microsoft Foundry (via Microsoft Agent Framework)
in production and against `FakeLLM` in tests. `ResilientLLM` adds timeouts, a retry and a
fallback model (A-5). The Critic is deterministic: it checks every number, player and club
against the moment's facts before anything can reach the screen (E-2, A-6).
"""
from __future__ import annotations

import asyncio
import os
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
FOUNDRY_SCOPE = "https://ai.azure.com/.default"  # project endpoints reject the cognitiveservices audience
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

    async def generate(self, role: str, instructions: str, prompt: str, schema: type[T],
                       tools: list | None = None) -> LLMResult[T]: ...


class AllModelsFailed(RuntimeError):
    def __init__(self, attempts: list[Attempt]):
        super().__init__("; ".join(f"{a.model}:{a.outcome}" + (f" ({a.detail[:120]})" if a.detail else "") for a in attempts))
        self.attempts = attempts


@dataclass
class FakeCall:
    role: str
    instructions: str
    prompt: str
    tools: list | None = None


class FakeLLM:
    """Scriptable stand-in for a model: per-role responders, optional delay, call log."""

    def __init__(self, responders: dict[str, Callable[[str], Any]], delay: float | dict[str, float] = 0.0,
                 name: str = "fake"):
        self.responders = responders
        self.delay = delay
        self.name = name
        self.calls: list[FakeCall] = []

    async def generate(self, role, instructions, prompt, schema, tools=None):
        self.calls.append(FakeCall(role, instructions, prompt, tools))
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
    """Runs each role as a Microsoft Agent Framework agent on a Foundry model deployment.

    Without an API key it authenticates with Microsoft Entra ID (DefaultAzureCredential): the
    managed identity in Azure, `az login` on a developer machine. No secret to leak or rotate.
    """

    def __init__(self, deployment: str, endpoint: str, api_key: str | None = None, credential: Any = None):
        from agent_framework.openai import OpenAIChatCompletionClient

        self.name = deployment
        if api_key:
            self.auth = "key"
            token: Any = api_key
        else:
            from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider

            self.auth = "entra"
            if credential is None:
                # In App Service go straight to the managed identity: DefaultAzureCredential probes
                # several sources first, and that first fetch can outlast a per-call timeout.
                credential = ManagedIdentityCredential() if os.environ.get("IDENTITY_ENDPOINT") else DefaultAzureCredential()
            # A token provider in place of the key: same OpenAI-compatible v1 endpoint, short-lived tokens.
            token = get_bearer_token_provider(credential, FOUNDRY_SCOPE)
        self._token = token
        self._client = OpenAIChatCompletionClient(
            model=deployment, api_key=token, base_url=endpoint.rstrip("/") + "/openai/v1/",
        )
        self._agents: dict[tuple[str, str], Any] = {}

    async def warm(self) -> None:
        """Fetch (and cache) the first token outside any per-call timeout."""
        if self.auth == "entra":
            await self._token()

    def _agent(self, role: str, instructions: str):
        from agent_framework import Agent

        key = (role, instructions)
        if key not in self._agents:
            self._agents[key] = Agent(client=self._client, name=role, instructions=instructions)
        return self._agents[key]

    async def generate(self, role, instructions, prompt, schema, tools=None):
        start = time.perf_counter()
        response = await self._agent(role, instructions).run(
            prompt, options={"response_format": schema}, tools=tools,
        )
        value = response.value
        if value is None:
            value = schema.model_validate_json(response.text)
        return LLMResult(value=value, model=self.name, ms=(time.perf_counter() - start) * 1000)


class ResilientLLM:
    """Primary model with a per-call timeout and retries, then a fallback model."""

    async def warm(self) -> None:
        for model in (self.primary, self.fallback):
            if model is not None and hasattr(model, "warm"):
                await model.warm()

    def __init__(self, primary: LLM, fallback: LLM | None, timeout_s: float = 3.0, retries: int = 1):
        self.primary, self.fallback = primary, fallback
        self.timeout_s, self.retries = timeout_s, retries
        self.name = f"{primary.name}|{fallback.name if fallback else '-'}"

    async def generate(self, role, instructions, prompt, schema, tools=None):
        attempts: list[Attempt] = []
        plan = [self.primary] * (1 + self.retries) + ([self.fallback] if self.fallback else [])
        for model in plan:
            start = time.perf_counter()
            try:
                res = await asyncio.wait_for(model.generate(role, instructions, prompt, schema, tools), self.timeout_s)
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


FACT_TEXT = {
    "score_home": "home score", "score_away": "away score", "minute": "minute",
    "goal_context": "goal context", "team_shots": "team shots in the match so far",
    "team_xg": "team xG in the match so far", "shot_xg": "xG of this shot", "shot_distance_m": "shot distance (m)",
    "assist": "assisted by", "player_goals": "player's goals in this match", "outcome": "shot outcome",
    "shot_speed_kmh": "shot speed (km/h)", "players_remaining": "players left on the pitch",
    "pass_difficulty": "pass difficulty (0-1)", "pass_distance_m": "pass distance (m)",
    "possession_home_pct": "home possession % in the match so far",
    "shots_home": "home shots in the match so far", "shots_away": "away shots in the match so far",
    "xg_home": "home xG in the match so far", "xg_away": "away xG in the match so far",
    "momentum": "momentum (-1 to 1) in the last {w} minutes",
    "field_tilt": "share of final-third passes (0-1) in the last {w} minutes",
    "window_shots": "shots in the last {w} minutes", "window_xg": "xG in the last {w} minutes",
    "window_minutes": "window length (minutes)", "tempo_passes_per_min": "passes per minute in the last {w} minutes",
    "ppda": "opponent passes per defensive action in the last {w} minutes",
}
GOAL_CONTEXT_TEXT = {
    "equaliser": "equaliser: makes the scores level", "takes_lead": "takes the lead",
    "extends_lead": "extends an existing lead", "pulls_one_back": "pulls a goal back but still behind",
}

# Phrases that contradict a goal's context (checked on English text before translation).
CONTRADICTIONS = {
    "equaliser": (r"\blead\b", r"\bahead\b", r"\bin front\b", r"\bdeadlock\b", r"\bwinner\b"),
    "takes_lead": (r"\bequali[sz]", r"\blevel", r"\bextends?\b"),
    "extends_lead": (r"\bequali[sz]", r"\blevel", r"\bdeadlock\b", r"\btakes? the lead\b"),
    "pulls_one_back": (r"\blead\b", r"\bahead\b", r"\bin front\b", r"\bequali[sz]", r"\blevel", r"\bdeadlock\b"),
}


def describe_facts(m: Moment, names: Names) -> str:
    team = names.club(m.team_id) if m.team_id else "-"
    player = names.player(m.player_id) if m.player_id else "-"
    lines = [
        f"Match: {names.club(names.home_id)} (home) v {names.club(names.away_id)} (away).",
        f"Moment: {m.kind.replace('_', ' ')} at {display_minute(m)}' (half {m.period}). Team: {team}. Player: {player}.",
        "Facts:",
    ]
    window = next((f.value for f in m.facts if f.label == "window_minutes"), 10)
    for f in m.facts:
        subject = f" ({_display(f.subject, names)})" if f.subject and f.subject not in (m.player_id,) else ""
        label = FACT_TEXT.get(f.label, f.label.replace("_", " ")).format(w=window)
        value = GOAL_CONTEXT_TEXT.get(f.value, f.value) if f.label == "goal_context" else _display(f.value, names)
        lines.append(f"[{f.id}] {label} = {value}{subject}")
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
        "statistics, describe quality the facts don't support, or predict what will happen next. Treat club "
        "names as plural (\"Northgate are\"). Headline at most 50 characters, why at most "
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
        "that player only when the facts involve them. Use only facts given: no predictions about the rest of "
        "the match, no events that are not in the facts. Treat club names as plural (\"Northgate are\"). "
        "Headline at most 55 characters, body at most 170 characters."
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
    """Translates on-screen text. Names are masked as ⟦A⟧, ⟦B⟧ ... before the model sees them and
    restored afterwards, so they can never be transliterated or altered."""

    role = "translator"
    instructions = (
        "You translate short on-screen football graphics. Tokens like ⟦A⟧ stand for names: copy every token "
        "exactly, once each, and do not add new ones. Keep every number as Western digits. Natural broadcast "
        "style for the target language. Headline at most 55 characters, body at most 170 characters."
    )

    def __init__(self, llm: LLM, names: list[str] | None = None):
        self.llm = llm
        full = set(names or [])
        parts = {part for n in full if " " in n for part in n.split(" ", 1) if len(part) >= 4}
        self.names = sorted(full | parts, key=len, reverse=True)  # longest first: "Kai Greaves" before "Greaves"

    def _mask(self, text: str, tokens: dict[str, str]) -> str:
        for name in self.names:
            if name in text:
                token = tokens.setdefault(name, f"⟦{chr(ord('A') + len(tokens))}⟧")
                text = text.replace(name, token)
        return text

    @staticmethod
    def _unmask(text: str, tokens: dict[str, str]) -> str:
        for name, token in tokens.items():
            text = text.replace(token, name)
        return text

    async def run(self, text: Personalised, language: str) -> Personalised:
        return (await self.run_full(text, language)).value

    async def run_full(self, text: Personalised, language: str):
        tokens: dict[str, str] = {}
        headline, body = self._mask(text.headline, tokens), self._mask(text.body, tokens)
        prompt = f"Target language: {LANGUAGE_NAMES[language]}.\nHeadline: {headline}\nBody: {body}"
        res = await self.llm.generate(self.role, self.instructions, prompt, Personalised)
        res.value = Personalised(
            headline=self._unmask(res.value.headline, tokens), body=self._unmask(res.value.body, tokens),
        )
        return res


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
        """Check text written about one moment against that moment's facts."""
        problems: list[str] = []
        if evidence is not None:
            ids = {f.id for f in m.facts}
            if not evidence or not set(evidence) <= ids:
                problems.append("evidence must list fact IDs from this moment")
        involved = {names.player(m.player_id)} if m.player_id else set()
        involved |= {names.player(f.value) for f in m.facts if isinstance(f.value, str) and f.value in names.players}
        context = next((f.value for f in m.facts if f.label == "goal_context"), None)
        problems += self.check_text(headline, body, self.allowed_numbers(m), involved, names, audience, context)
        return Verdict(ok=not problems, problems=problems)

    def check_text(self, headline: str, body: str, allowed: set[str], involved: set[str], names: Names,
                   audience: Audience | None = None, context: str | None = None,
                   max_headline: int = MAX_HEADLINE, max_body: int = MAX_BODY) -> list[str]:
        """Shared checks: lengths, numbers, names, clubs, goal context and fan jargon."""
        problems: list[str] = []
        text = f"{headline}\n{body}"
        if not headline.strip() or len(headline) > max_headline:
            problems.append(f"headline must be 1-{max_headline} characters")
        if len(body) > max_body:
            problems.append(f"body must be at most {max_body} characters")
        if "⟦" in text or "⟧" in text:
            problems.append("unrestored name tokens in text")

        for n in _NUMBER.findall(_normalise_numbers(text)):
            norm = n.rstrip("0").rstrip(".") if "." in n else n
            if norm not in allowed:
                problems.append(f"number {n} is not in the facts")

        involved_surnames = {n.split(" ", 1)[-1] for n in involved}
        for name in sorted(self.league_players - involved):
            surname = name.split(" ", 1)[-1]
            if name in text or (surname not in involved_surnames and re.search(rf"\b{re.escape(surname)}\b", text)):
                problems.append(f"player {name} is not part of this moment")

        match_clubs = {names.club(names.home_id), names.club(names.away_id)}
        for club in sorted(self.league_clubs - match_clubs):
            if club in text:
                problems.append(f"club {club} is not in this match")

        for pattern in CONTRADICTIONS.get(context, ()):
            if re.search(pattern, text, re.IGNORECASE):
                problems.append(f"contradicts the goal context ({context}): '{pattern}'")

        if audience is not None and audience.mode == "fan":
            lowered = text.lower()
            for term in FAN_JARGON:
                if re.search(rf"\b{re.escape(term)}\b", lowered):
                    problems.append(f"jargon '{term}' is not for casual fans")
        return problems
