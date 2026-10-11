"""Real-world context for commentators (CX-1..CX-6).

The clubs and players are fictional, so outside context is comparison and explanation only:
real Premier League benchmarks and tactics explainers, each with its sources.

- ResearcherAgent: Microsoft Agent Framework agent with Foundry web search. Offline it builds the
  context library (scripts/build_context_library.py); live it answers the desk's ask box.
- ContextAgent: picks one library entry for a big moment and writes a one-line card. No web call.
- check_card / entry_problems / verify_against_source: deterministic checks, like the Critic.
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, Field

from .agents import LLMResult, _normalise_numbers, _number_forms, describe_facts
from opentelemetry.trace import StatusCode

from .overlay import Names, display_minute
from .scout import Moment
from .telemetry import tracer

LIBRARY_PATH = Path(__file__).parent / "data" / "context_library.json"

# Real Premier League clubs (2024/25 and common short forms): never named in automatic cards (CX-4).
REAL_CLUBS = (
    "Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Chelsea", "Crystal Palace", "Everton",
    "Fulham", "Ipswich", "Leicester", "Liverpool", "Manchester City", "Man City", "Manchester United", "Man United",
    "Man Utd", "Newcastle", "Nottingham Forest", "Southampton", "Tottenham", "Spurs", "West Ham", "Wolves",
    "Wolverhampton",
)
# Wording that marks a partial, projected or per-club figure rather than a full-season league benchmark.
_NOT_FULL_SEASON = re.compile(r"\b(projected|projection|estimat\w*|as of|so far|by the \w+ (?:matchweek|gameweek|week)|"
                              r"mid-season|first \d+ (?:games|matches)|ranged|range[sd]? from|on pace)\b", re.I)
_REAL_CLUB_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in REAL_CLUBS) + r")\b", re.I)
_NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_SEASON_OR_YEAR = re.compile(  # labels, not figures: 2024/25, 2024-25, 24/25, 1992
    r"\b(?:18|19|20)\d{2}[/-]\d{2,4}\b|\b\d{2}/\d{2}\b|(?<![\d,.])(?:18|19|20)\d{2}(?!\d|[,.]\d)")
MAX_CARD = 200
MAX_ENTRY = 400

# A second, independent source for benchmarks that docs/REALISM.md already covers (sourced there):
# entry id -> accepted values, tolerance. An entry must state at least one of them.
REFERENCE: dict[str, tuple[tuple[float, ...], float]] = {
    "goals-per-match": ((2.93, 1115), 0.02),
    "home-wins": ((40.8, 155), 0.3),
    "draws": ((24.5, 93), 0.3),
    "red-cards": ((52, 0.137), 0.01),
    "shots-per-match": ((13.1, 26.2), 0.3),
    "shot-conversion": ((11.2,), 0.4),
}


class Source(BaseModel):
    url: str
    title: str


class ContextEntry(BaseModel):
    id: str
    kind: Literal["benchmark", "tactic"]
    topic: str
    text: str
    numbers: list[float] = Field(default_factory=list)
    sources: list[Source]
    retrieved: str  # YYYY-MM-DD
    tags: list[str] = Field(default_factory=list)  # moment kinds (and "stat:<name>") it relates to
    translations: dict[str, str] = Field(default_factory=dict)  # language -> text (es, ar)
    origin: Literal["web search", "calibration sources"] = "web search"

    def text_in(self, language: str) -> str:
        return self.translations.get(language, self.text)


class TopicSpec(BaseModel):
    id: str
    kind: Literal["benchmark", "tactic"]
    topic: str
    question: str
    tags: list[str]


class WebAnswer(BaseModel):
    text: str
    sources: list[Source]


class ContextCard(BaseModel):
    entry_id: str = Field(description="The id of the library entry you used, exactly as given.")
    text: str = Field(description="One sentence, at most 200 characters.")


def numbers_in(text: str) -> list[float]:
    """Every figure in a text (thousands separators and Arabic digits handled; seasons and years skipped)."""
    text = re.sub(r"\b\d{1,3}(?:,\d{3})+\b", lambda mm: mm.group().replace(",", ""), text)  # 1,234 before 2,5 = 2.5
    text = _SEASON_OR_YEAR.sub(" ", _normalise_numbers(text))
    return [float(n.replace(",", "")) for n in _NUM.findall(text)]


def _allowed_forms(values) -> set[str]:
    out: set[str] = set()
    for v in values:
        out |= _number_forms(v)
        if isinstance(v, float) and v.is_integer():
            out.add(str(int(v)))
    return out


def _form(n: float) -> str:
    return str(int(n)) if n.is_integer() else f"{n:g}"


def entry_problems(e: ContextEntry) -> list[str]:
    problems = []
    if not e.sources:
        problems.append("no source")
    problems += [f"source is not https: {s.url}" for s in e.sources if not s.url.startswith("https://")]
    allowed = _allowed_forms(e.numbers)
    for language, text in {"en": e.text, **e.translations}.items():
        problems += [f"number {_form(n)} not in the entry's numbers ({language})"
                     for n in numbers_in(text) if _form(n) not in allowed]
    if e.kind == "benchmark" and _REAL_CLUB_RE.search(e.text):
        problems.append("benchmark names a real club")
    if e.kind == "benchmark" and (m := _NOT_FULL_SEASON.search(e.text)):
        problems.append(f"not a full-season league figure ('{m.group()}')")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.retrieved):
        problems.append("retrieved is not a date")
    return problems


def clean_answer(text: str) -> str:
    """Keep the answer itself: no source list, no 'according to …', no markdown."""
    text = re.split(r"\n\s*(?:\*\*)?Sources?:?", text, maxsplit=1)[0]
    text = re.sub(r",?\s*(?:according to|as reported by|as confirmed by|confirmed by)\s+[^.,;]*(?=[.;])", "", text, flags=re.I)
    text = re.sub(r"[*`#]", "", text)  # markdown emphasis; underscores stay (OFF_TOPIC, snake_case)
    text = re.sub(r"(?:\s*,)+\s*([.!?])", r"\1", text)  # commas left behind by removed citations
    text = re.sub(r",(?:\s*,)+", ",", text)
    return " ".join(text.split())


def cross_check(e: ContextEntry, reference=REFERENCE) -> list[str]:
    if e.id not in reference:
        return []
    accepted, tolerance = reference[e.id]
    if any(abs(n - v) <= tolerance for n in e.numbers for v in accepted):
        return []
    return [f"{e.id}: none of {[_form(n) for n in e.numbers]} matches the second source {list(accepted)}"]


def _page_text(raw: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", " ", text))


def verify_against_source(e: ContextEntry, fetch: Callable[[str], str | None]) -> list[str]:
    """Each number must appear on at least one cited page. Returns problems (empty = verified)."""
    pages = [p for p in (fetch(s.url) for s in e.sources) if p]
    if not pages:
        return ["no source page could be fetched"]
    found = set()
    for page in pages:
        found |= {_form(n) for n in numbers_in(_page_text(page))}
    return [f"{_form(n)} not found in the sources" for n in e.numbers if _form(n) not in found]


def load_library(path: Path = LIBRARY_PATH) -> list[ContextEntry]:
    if not path.exists():
        return []
    return [ContextEntry(**row) for row in json.loads(path.read_text())]


# ---------- researcher ----------

class WebSearch(Protocol):
    async def search(self, question: str, instructions: str) -> WebAnswer: ...


LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "ar": "Arabic"}

BUILD_INSTRUCTIONS = (
    "You research real football facts for a TV commentator's notes. Search the web. Reply with one sentence "
    "(at most 220 characters) that states the figure exactly as a source states it. Never calculate, estimate "
    "or combine figures yourself; if no source states it directly, say so. League-wide figures only: do not "
    "name clubs or players. Cite each source inline as a markdown link (links are moved out of the text later)."
)
TACTIC_INSTRUCTIONS = (
    "You research football tactics and analytics concepts for a TV commentator's notes. Search the web. Explain "
    "the concept in at most two plain sentences (at most 300 characters) a viewer would understand. Do not give "
    "examples with figures and do not quote statistics. Cite each source inline as a markdown link (links are "
    "moved out of the text later)."
)
ASK_INSTRUCTIONS = (
    "You help a football commentator during a live broadcast of a fictional league. Answer questions about real "
    "football benchmarks, records, rules and tactics only. Search the web and answer in at most three short "
    "sentences, stating figures exactly as a source states them (no calculations), and cite your sources. "
    "If the question is not about football, reply with exactly OFF_TOPIC. Answer in {language}."
)


class ResearcherAgent:
    role = "researcher"

    def __init__(self, search: WebSearch):
        self.search = search
        self.last_rejection = ""  # why the last build_entry returned None, for the person reviewing

    async def build_entry(self, spec: TopicSpec, retrieved: str) -> ContextEntry | None:
        instructions = BUILD_INSTRUCTIONS if spec.kind == "benchmark" else TACTIC_INSTRUCTIONS
        answer = await self.search.search(spec.question, instructions)
        text = clean_answer(answer.text)
        e = ContextEntry(id=spec.id, kind=spec.kind, topic=spec.topic, text=text,
                         numbers=numbers_in(text), sources=answer.sources, retrieved=retrieved, tags=spec.tags)
        problems = (["no citations"] if not answer.sources else []) + \
            ([f"{len(text)} characters"] if len(text) > MAX_ENTRY else []) + entry_problems(e) + cross_check(e)
        self.last_rejection = f"{'; '.join(problems)} | {text[:200]}" if problems else ""
        return None if problems else e

    async def ask(self, question: str, language: str) -> WebAnswer:
        instructions = ASK_INSTRUCTIONS.format(language=LANGUAGE_NAMES.get(language, "English"))
        answer = await self.search.search(question, instructions)
        return answer.model_copy(update={"text": clean_answer(answer.text)})


class AgentFrameworkWebSearch:
    """Web search through a Microsoft Agent Framework agent on Foundry (Responses API + web search tool).
    Keyless like the other agents: managed identity in Azure, `az login` locally."""

    def __init__(self, deployment: str, endpoint: str, credential: Any = None):
        from agent_framework.openai import OpenAIChatClient
        from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential, get_bearer_token_provider

        from .agents import FOUNDRY_SCOPE

        if credential is None:
            credential = (ManagedIdentityCredential(client_id=os.environ.get("AZURE_CLIENT_ID") or None)
                          if os.environ.get("IDENTITY_ENDPOINT") else DefaultAzureCredential())
        self.name = deployment
        self._client = OpenAIChatClient(model=deployment, api_key=get_bearer_token_provider(credential, FOUNDRY_SCOPE),
                                        base_url=endpoint.rstrip("/") + "/openai/v1/")
        self._tool = self._client.get_web_search_tool()
        self._agents: dict[str, Any] = {}

    async def search(self, question: str, instructions: str) -> WebAnswer:
        from agent_framework import Agent

        agent = self._agents.get(instructions)
        if agent is None:
            agent = self._agents[instructions] = Agent(client=self._client, name="researcher",
                                                       instructions=instructions, tools=[self._tool])
        response = await agent.run(question, options={"tool_choice": "required"})  # always search, never recall
        sources: dict[str, Source] = {}
        for message in response.messages:
            for content in message.contents:
                for a in getattr(content, "annotations", None) or []:
                    get = a.get if isinstance(a, dict) else (lambda k, a=a: getattr(a, k, None))
                    url = get("url")
                    if url and url.startswith("https://") and url not in sources:
                        sources[url] = Source(url=url.split("?utm_source")[0], title=get("title") or url)
        # Links are shown separately, so drop the inline markdown citations from the text.
        text = re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)|\s*\[[^\]]*\]\(https?://[^)]*\)", "", response.text).strip()
        return WebAnswer(text=text, sources=list(sources.values()))


# ---------- context cards ----------

CONTEXT_INSTRUCTIONS = (
    "You write one-line real-world context for a TV commentator. The match is in a fictional league; you are given "
    "the moment's facts and a few entries of real Premier League benchmarks or tactics. Pick the single most "
    "relevant entry and write one sentence (max 200 characters) that compares the moment to it or explains it. "
    "Use only numbers from the chosen entry or the facts. Never attribute real-world facts to the fictional clubs "
    "or players, and never name real clubs or players. Return the entry id you used."
)


def check_card(card: ContextCard, entry: ContextEntry | None, m: Moment, names: Names) -> list[str]:
    problems = []
    if entry is None or card.entry_id != entry.id:
        return [f"unknown entry {card.entry_id}"]
    if not card.text.strip():
        problems.append("empty card")
    if len(card.text) > MAX_CARD:
        problems.append(f"card longer than {MAX_CARD} characters")
    if _REAL_CLUB_RE.search(card.text):
        problems.append("card names a real club")
    minute = numbers_in(display_minute(m))
    allowed = _allowed_forms([*entry.numbers, *(f.value for f in m.facts), *minute])
    problems += [f"number {_form(n)} is in neither the entry nor the facts"
                 for n in numbers_in(card.text) if _form(n) not in allowed]
    return problems


class ContextAgent:
    role = "context"
    instructions = CONTEXT_INSTRUCTIONS

    def __init__(self, llm, library: list[ContextEntry]):
        self.llm = llm
        self.library = library
        self.by_id = {e.id: e for e in library}

    def candidates(self, m: Moment, used: set[str], limit: int = 4) -> list[ContextEntry]:
        return [e for e in self.library if m.kind in e.tags and e.id not in used][:limit]

    async def run_full(self, m: Moment, names: Names, used: set[str], feedback: str = "") -> LLMResult[ContextCard]:
        entries = "\n".join(f"[{e.id}] ({e.kind}) {e.text}" for e in self.candidates(m, used))
        prompt = f"{describe_facts(m, names)}\n\nReal-world entries:\n{entries}"
        if feedback:
            prompt += f"\n\nYour previous answer was rejected: {feedback}. Fix it."
        return await self.llm.generate(self.role, self.instructions, prompt, ContextCard)


# ---------- ask box ----------

class AskDesk:
    """One match's ask box: cached, capped and time-limited live web answers (CX-3)."""

    def __init__(self, researcher: ResearcherAgent, limit: int = 15, timeout_s: float = 15.0):
        self.researcher = researcher
        self.limit = limit
        self.timeout_s = timeout_s
        self.used = 0
        self.cache: dict[tuple[str, str], dict] = {}

    @staticmethod
    def _key(question: str) -> str:
        return " ".join(re.sub(r"[^\w\s]", " ", question.lower()).split())

    def _result(self, status: str, text: str = "", sources: list[Source] | None = None) -> dict:
        return {"status": status, "text": text, "sources": [s.model_dump() for s in sources or []],
                "remaining": self.limit - self.used}

    async def ask(self, question: str, language: str) -> dict:
        key = (self._key(question), language)
        if key in self.cache:
            return {**self.cache[key], "status": "cached", "remaining": self.limit - self.used}
        if self.used >= self.limit:
            return self._result("limit")
        with tracer.start_as_current_span("invoke_agent researcher", attributes={
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "researcher", "pa.language": language,
        }) as span:  # CX-7; prompts and answers are not recorded
            try:
                answer = await asyncio.wait_for(self.researcher.ask(question, language), self.timeout_s)
            except asyncio.TimeoutError:
                span.set_attribute("pa.outcome", "timeout")
                return self._result("timeout")
            except Exception as err:  # the desk shows a plain message; the trace keeps the reason
                span.set_status(StatusCode.ERROR, repr(err)[:300])
                span.set_attribute("pa.outcome", "error")
                print(f"ask box search failed: {err!r}"[:500], flush=True)
                return self._result("error")
            outcome = "off_topic" if answer.text.strip() == "OFF_TOPIC" else "no_source" if not answer.sources else "ok"
            span.set_attributes({"pa.outcome": outcome, "pa.sources": len(answer.sources)})
        if outcome != "ok":
            return self._result(outcome)
        self.used += 1
        result = self._result("ok", answer.text, answer.sources)
        self.cache[key] = result
        return result
