"""Offline model stand-ins for end-to-end tests and demos without Azure.

scripted_llm():    deterministic, always passes the Critic (no numbers or names it can't back up).
down_llm():        every call fails, to show the fast path carrying on during a model outage.
scripted_search(): a stand-in web search for the desk's ask box, with a source.
"""
from __future__ import annotations

import re

from .agents import Explanation, FakeLLM, Personalised
from .context import ContextCard, Source, WebAnswer
from .match_analyst import AskRoute, MatchAnswer
from .producer import ProducerNote
from .recap import RecapDraft

_PHRASES = {
    "es": {
        "A moment that shifts the game": "Un momento que cambia el partido",
        "Here is why it matters.": "Por esto es importante.",
        "Key moment": "Momento clave",
        "The evidence panel shows the numbers behind it.": "El panel de datos muestra las cifras.",
        "How this compares with the real Premier League.": "Cómo se compara con la Premier League real.",
    },
    "ar": {
        "A moment that shifts the game": "لحظة تغير مجرى المباراة",
        "Here is why it matters.": "ولهذا هي مهمة.",
        "Key moment": "لحظة حاسمة",
        "The evidence panel shows the numbers behind it.": "لوحة الأدلة تعرض الأرقام.",
        "How this compares with the real Premier League.": "مقارنة بالدوري الإنجليزي الحقيقي.",
    },
}


def _explainer(prompt: str) -> Explanation:
    fact = re.search(r"\[([^\]]+-f\d+)\]", prompt).group(1)
    return Explanation(headline="A moment that shifts the game", why="Here is why it matters.", evidence=[fact])


def _personaliser(prompt: str) -> Personalised:
    if "casual fan" in prompt:
        return Personalised(headline="A moment that shifts the game", body="Here is why it matters.")
    return Personalised(headline="Key moment", body="The evidence panel shows the numbers behind it.")


def _translator(prompt: str) -> Personalised:
    language = "ar" if "Arabic" in prompt else "es"
    headline = re.search(r"Headline: (.*)", prompt).group(1)
    body = re.search(r"Body: (.*)", prompt, re.S).group(1).strip()
    table = _PHRASES[language]
    return Personalised(headline=table.get(headline, headline), body=table.get(body, body))


def _context(prompt: str) -> ContextCard:
    entry = re.search(r"^\[([\w-]+)\] \(", prompt, re.M).group(1)
    return ContextCard(entry_id=entry, text="How this compares with the real Premier League.")


class _ScriptedSearch:
    async def search(self, question: str, instructions: str) -> WebAnswer:
        return WebAnswer(text="A scripted answer for offline demos; with Foundry it is a live web search.",
                         sources=[Source(url="https://learn.microsoft.com/azure/ai-foundry/", title="Microsoft Foundry")])


def scripted_search() -> _ScriptedSearch:
    return _ScriptedSearch()


def scripted_llm(delay: float = 0.3) -> FakeLLM:
    llm = _scripted(delay)

    def match_analyst(_prompt: str) -> MatchAnswer:  # really calls a tool, as the Agent Framework would
        call = next(c for c in reversed(llm.calls) if c.role == "match_analyst")
        s = {t.__name__: t for t in call.tools}["get_score"]()
        return MatchAnswer(scope="match", answer=f"{s['home']} {s['score_home']}-{s['score_away']} {s['away']}.")

    llm.responders["match_analyst"] = match_analyst
    llm.responders["ask_router"] = lambda p: AskRoute(
        scope="real_world" if re.search(r"league|record|average|history|rule", p, re.I) else "match")
    return llm


def _scripted(delay: float) -> FakeLLM:
    return FakeLLM({
        "explainer": _explainer,
        "personaliser": _personaliser,
        "translator": _translator,
        "context": _context,
        "recap": lambda p: RecapDraft(headline="Match recap", summary="The key moments, explained.", key_points=[]),
        "producer": lambda p: ProducerNote(text="Worth a mention while play is stopped."),
    }, delay=delay, name="scripted")


def down_llm() -> FakeLLM:
    def fail(_prompt: str) -> Exception:
        return RuntimeError("model unavailable (simulated outage)")

    return FakeLLM({role: fail for role in ("explainer", "personaliser", "translator", "context", "recap", "producer",
                                         "ask_router", "match_analyst")}, name="down")
