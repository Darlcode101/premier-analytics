"""Ask about this match (AM-1..AM-3): the desk's ask box answers questions about the live match.

The Match Analyst gets the question and the read-only match tools (the same ones the MCP server exposes),
calls what it needs and answers in a sentence or two. Code computes, the model explains: every number and
player in the answer must appear in what the tools returned (the Critic), with one retry; if it still fails,
the desk gets the tool results without a narrative. Questions about the real world go to the Researcher;
questions the data can't answer (offsides, injuries, distance run) are said to be outside the feed.
"""
from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel, Field

from .agents import _NUMBER, LLM, CriticAgent, _number_forms
from .languages import LANGUAGE_NAMES
from .mcp_server import MatchState, MatchTools
from .telemetry import tracer

__all__ = ["AskRoute", "MatchAnalyst", "MatchAnswer", "MatchTools"]

MAX_ANSWER = 300


class AskRoute(BaseModel):
    scope: Literal["match", "real_world"]


# The router only separates this match from the wider game; whether this match's data holds the answer is
# for the Match Analyst, which can see the data (live check 10-17: a router that also judged that refused
# questions the tools answer).
ROUTER_INSTRUCTIONS = (
    "Classify a TV commentator's question asked during a live match. "
    "match: anything about the match being played: score, goals, shots, chances, passes, tackles, fouls, cards "
    "and why, substitutions, possession, momentum, players or teams in this match, including things the data "
    "may not hold. "
    "real_world: about football beyond this match: records, history, other matches, teams or leagues, the laws "
    "of the game, tactics or terms in general. When unsure, choose match."
)


class MatchAnswer(BaseModel):
    scope: Literal["match", "real_world", "not_in_data"] = Field(
        description="match: answered from the tools; real_world: about football beyond this match; "
                    "not_in_data: about this match but the feed doesn't hold it")
    answer: str = Field(description="At most two short sentences (max 300 characters). Empty for real_world.")


INSTRUCTIONS = (
    "You answer a TV commentator's question about the match in progress, using only the match tools. Call the "
    "tools you need, then answer in at most two short sentences, quoting numbers exactly as the tools return them. Never "
    "guess or round differently. Player stats say when a substitute came on and their totals already start "
    "then, so for 'since he came on' do not pass since_minute. Pass since_minute only for a minute the question "
    "names (second half = 46). If the question is about football beyond this match (records, history, other "
    "teams, rules, tactics in general), set scope to real_world and leave the answer empty. If it is about this "
    "match but the data does not hold it (offsides, injuries, distance run, heart rates, VAR), set scope to "
    "not_in_data and say in one short sentence what isn't in the feed. Answer in {language}."
)


def _walk(value, numbers: set[str], strings: set[str]) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _walk(v, numbers, strings)
    elif isinstance(value, list):
        for v in value:
            _walk(v, numbers, strings)
    elif isinstance(value, str):
        strings.add(value)
        numbers.update(_NUMBER.findall(value))
    else:
        numbers.update(_number_forms(value))


def summary(entry: dict) -> str:
    """One line of evidence: the call and its top-level values, e.g. get_score() → score_home 1 · score_away 2."""
    args = ", ".join(f"{k}={v}" for k, v in entry["args"].items())
    result = entry["result"]

    def item(x) -> str:  # one list entry: its names first, then labelled numbers
        if not isinstance(x, dict):
            return str(x)
        words = [str(v) for v in x.values() if isinstance(v, str)]
        nums = [f"{k} {v}" for k, v in x.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return ", ".join(words + nums)

    parts = []
    for k, v in (result.items() if isinstance(result, dict) else []):
        if isinstance(v, list):
            shown = "; ".join(item(x) for x in v[:3]) or "none"
            parts.append(f"{k}: {shown}" + (f" (+{len(v) - 3} more)" if len(v) > 3 else ""))
        elif not isinstance(v, dict):
            parts.append(f"{k} {v}")
    return f"{entry['tool']}({args}) → {' · '.join(parts[:10])}"


class MatchAnalyst:
    role = "match_analyst"

    def __init__(self, llm: LLM, critic: CriticAgent, state: MatchState, limit: int = 40, timeout_s: float = 25.0):
        self.llm = llm
        self.critic = critic
        self.state = state
        self.tools = MatchTools(state)
        self.limit = limit
        self.timeout_s = timeout_s
        self.used = 0
        self.model: str | None = None

    def problems(self, text: str, log: list[dict], question: str, as_of: str) -> list[str]:
        """AM-2: numbers and players must come from the tool results (or the question and the clock)."""
        numbers: set[str] = set()
        strings: set[str] = set()
        for entry in log:
            _walk(entry["args"], numbers, strings)
            _walk(entry["result"], numbers, strings)
        numbers |= set(_NUMBER.findall(question)) | set(_NUMBER.findall(as_of))
        players = {s for s in strings if s in self.state.names.players.values()}
        return self.critic.check_text(text, "", numbers, players, self.state.names, max_headline=MAX_ANSWER)

    def _result(self, status: str, as_of: str, text: str = "", log: list[dict] | None = None) -> dict:
        evidence, seen = [], set()
        for e in log or []:  # the same call made twice is one piece of evidence
            line = summary(e)
            if line not in seen:
                seen.add(line)
                evidence.append({"tool": e["tool"], "args": e["args"], "summary": line})
        return {"status": status, "source": "match", "text": text, "sources": [], "evidence": evidence,
                "as_of": as_of, "remaining": self.limit - self.used}

    async def _generate(self, prompt: str, language: str, tools: list) -> MatchAnswer:
        instructions = INSTRUCTIONS.format(language=LANGUAGE_NAMES.get(language, "English"))
        res = await asyncio.wait_for(self.llm.generate(self.role, instructions, prompt, MatchAnswer, tools=tools),
                                     self.timeout_s)
        self.model = res.model
        return res.value

    async def _route(self, question: str, language: str) -> AskRoute | None:
        """The Ask Router: this match or the real world. None if it fails (the analyst then decides)."""
        try:
            res = await asyncio.wait_for(self.llm.generate("ask_router", ROUTER_INSTRUCTIONS, question, AskRoute),
                                         self.timeout_s)
            return res.value
        except Exception as err:
            print(f"ask router failed: {err!r}"[:300], flush=True)
            return None

    async def ask(self, question: str, language: str, as_of: str) -> dict:
        if self.used >= self.limit:  # every question counts, routed or answered
            return self._result("limit", as_of)
        self.used += 1
        route = await self._route(question, language)
        if route is not None and route.scope == "real_world":
            return {"status": "real_world"}
        log: list[dict] = []
        tools = self.tools.recorded(log)
        prompt = f"The match is at {as_of}'. Question: {question}"
        with tracer.start_as_current_span("invoke_agent match_analyst", attributes={
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": self.role, "pa.language": language,
        }) as span:  # prompts and answers are not recorded
            try:
                ans = await self._generate(prompt, language, tools)
                if ans.scope == "real_world":
                    span.set_attribute("pa.outcome", "real_world")
                    return {"status": "real_world"}
                problems = self.problems(ans.answer, log, question, as_of)
                if ans.scope == "not_in_data":
                    span.set_attribute("pa.outcome", "not_in_data")
                    return self._result("not_in_data", as_of, "" if problems else ans.answer, log)
                if problems or not ans.answer.strip():  # one retry, told exactly what was wrong
                    retry = (f"{prompt}\n\nYour previous answer was rejected: {'; '.join(problems) or 'empty'}.\n"
                             f"Previous answer: {ans.answer}\nCall the tools you need and answer again using only "
                             "values they return.")
                    ans = await self._generate(retry, language, tools)
                    problems = self.problems(ans.answer, log, question, as_of) if ans.scope == "match" else ["scope"]
            except asyncio.TimeoutError:
                span.set_attribute("pa.outcome", "timeout")
                return self._result("timeout", as_of)
            except Exception as err:
                span.set_attribute("pa.outcome", "error")
                print(f"match analyst failed: {err!r}"[:500], flush=True)
                return self._result("error", as_of)
            outcome = "facts_only" if problems or not ans.answer.strip() else "ok"
            span.set_attributes({"pa.outcome": outcome, "pa.tool_calls": len(log)})
        return self._result(outcome, as_of, ans.answer if outcome == "ok" else "", log)
