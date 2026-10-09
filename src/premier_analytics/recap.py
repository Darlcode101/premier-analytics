"""Recap Producer: half-time and full-time recaps (R-3).

Runs off the live path. In production the agent pulls what it needs through the match MCP
server's tools; without tools (tests, MCP unavailable) the state is summarised into the
prompt instead. Either way the Critic checks every number and name against the full
match state before the recap is published, and the Translator localises it.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field

from .agents import LLM, AllModelsFailed, CriticAgent, Personalised, TranslatorAgent, _number_forms
from .mcp_server import MatchState
from .overlay import display_minute

MAX_SUMMARY = 420
MAX_POINT = 120


class RecapDraft(BaseModel):
    """What the model writes. Kept separate so bookkeeping fields aren't in the model's schema."""
    headline: str = Field(description="At most 60 characters.")
    summary: str = Field(description=f"Two or three sentences, at most {MAX_SUMMARY} characters.")
    key_points: list[str] = Field(description=f"Up to three short points, each at most {MAX_POINT} characters.")


class Recap(RecapDraft):
    language: str = "en"
    kind: str = "full_time"
    model: str | None = None


def _numbers(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        for v in value.values():
            yield from _numbers(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _numbers(v)
    else:
        yield value


class RecapProducer:
    role = "recap"
    instructions = (
        "You are the Recap Producer for a live football broadcast. Use the match tools (get_score, "
        "get_team_stats, get_top_players, get_key_moments, get_player_stats) to gather what you need, then "
        "write the recap in British English. Explain why the match is going (or went) the way it did: chances "
        "created, xG, momentum swings, key players. Quote numbers exactly as the tools return them, never invent "
        "statistics, never predict, never copy internal field names (write 'xG', not 'shot_xg'). Treat club names as plural. Headline at most 60 characters; summary two or "
        f"three sentences, at most {MAX_SUMMARY} characters; up to three key points of at most {MAX_POINT} "
        "characters each."
    )

    def __init__(self, llm: LLM, critic: CriticAgent, state: MatchState, tools: list | None = None,
                 translator: TranslatorAgent | None = None):
        self.llm = llm
        self.critic = critic
        self.state = state
        self.tools = tools
        names = state.names
        self.translator = translator or TranslatorAgent(llm, list(names.players.values()) + list(names.clubs.values()))
        self._english: dict[str, asyncio.Task] = {}

    # ---------- grounding ----------

    def _state_summary(self) -> dict:
        snap = self.state.scout.engine.snapshot()
        names = self.state.names
        teams = {
            names.club(tid): {k: (round(v, 2) if isinstance(v, float) else v) for k, v in t.model_dump().items()}
            for tid, t in snap.teams.items()
        }
        moments = [
            {"minute": display_minute(m), "kind": m.kind, "team": names.club(m.team_id) if m.team_id else None,
             "player": names.player(m.player_id) if m.player_id else None,
             "facts": {f.label: names.players.get(f.value, f.value) if isinstance(f.value, str) else f.value
                       for f in m.facts}}
            for m in self.state.moments if m.severity >= 0.5
        ]
        players = {names.player(pid): p.model_dump(exclude={"team_id"}) for pid, p in snap.players.items()}
        return {"score": {"home": names.club(names.home_id), "away": names.club(names.away_id),
                          "score_home": snap.score[0], "score_away": snap.score[1]},
                "teams": teams, "players": players, "key_moments": moments}

    def allowed_numbers(self) -> set[str]:
        allowed: set[str] = set()
        for v in _numbers(self._state_summary()):
            allowed |= _number_forms(v)
            if isinstance(v, str):
                allowed |= {part for part in v.replace("+", " ").split() if part.isdigit()}
        return allowed | {"45", "90"}

    def review(self, r: Recap) -> list[str]:
        names = self.state.names
        body = r.summary + "\n" + "\n".join(r.key_points)
        problems = self.critic.check_text(
            r.headline, body, self.allowed_numbers(), set(names.players.values()), names,
            max_body=MAX_SUMMARY + 3 * (MAX_POINT + 1),
        )
        if len(r.summary) > MAX_SUMMARY:
            problems.append(f"summary must be at most {MAX_SUMMARY} characters")
        if len(r.key_points) > 3 or any(len(p) > MAX_POINT for p in r.key_points):
            problems.append(f"at most three key points of {MAX_POINT} characters")
        return problems

    # ---------- run ----------

    def _prompt(self, kind: str, feedback: str) -> str:
        names = self.state.names
        moment = "half-time" if kind == "half_time" else "full-time"
        prompt = f"Write the {moment} recap for {names.club(names.home_id)} v {names.club(names.away_id)}."
        if not self.tools:
            prompt += "\n\nMatch state (key moments, teams, players):\n" + json.dumps(self._state_summary(), default=str)
        if feedback:
            prompt += f"\n\nYour previous recap was rejected: {feedback}. Fix it."
        return prompt

    async def run(self, kind: str, language: str = "en") -> Recap | None:
        """English is written once per kind and shared; other languages translate it."""
        if kind not in self._english:
            self._english[kind] = asyncio.ensure_future(self._write(kind))
        recap = await self._english[kind]
        if recap is None or language == "en":
            return recap
        return await self._translate(recap, language)

    async def _write(self, kind: str) -> Recap | None:
        feedback = ""
        recap = None
        for _ in range(2):
            try:
                res = await self.llm.generate(self.role, self.instructions, self._prompt(kind, feedback),
                                              RecapDraft, tools=self.tools)
            except AllModelsFailed:
                return None
            draft = res.value
            candidate = Recap(headline=draft.headline, summary=draft.summary, key_points=draft.key_points,
                              model=res.model, kind=kind, language="en")
            problems = self.review(candidate)
            if not problems:
                recap = candidate
                break
            feedback = "; ".join(problems)
        return recap

    async def _translate(self, recap: Recap, language: str) -> Recap | None:
        body = recap.summary + "".join(f"\n• {p}" for p in recap.key_points)
        try:
            res = await self.translator.run_full(Personalised(headline=recap.headline, body=body), language)
        except AllModelsFailed:
            return None
        lines = [ln.strip() for ln in res.value.body.split("\n") if ln.strip()]
        summary = " ".join(ln for ln in lines if not ln.startswith("•"))
        points = [ln.lstrip("• ").strip() for ln in lines if ln.startswith("•")]
        translated = recap.model_copy(update={
            "headline": res.value.headline, "summary": summary, "key_points": points, "language": language,
        })
        return None if self.review(translated) else translated
