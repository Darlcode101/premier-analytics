"""Offline model stand-ins for end-to-end tests and demos without Azure.

scripted_llm(): deterministic, always passes the Critic (no numbers or names it can't back up).
down_llm():     every call fails, to show the fast path carrying on during a model outage.
"""
from __future__ import annotations

import re

from .agents import Explanation, FakeLLM, Personalised
from .recap import RecapDraft

_PHRASES = {
    "es": {
        "A moment that shifts the game": "Un momento que cambia el partido",
        "Here is why it matters.": "Por esto es importante.",
        "Key moment": "Momento clave",
        "The evidence panel shows the numbers behind it.": "El panel de datos muestra las cifras.",
    },
    "ar": {
        "A moment that shifts the game": "لحظة تغير مجرى المباراة",
        "Here is why it matters.": "ولهذا هي مهمة.",
        "Key moment": "لحظة حاسمة",
        "The evidence panel shows the numbers behind it.": "لوحة الأدلة تعرض الأرقام.",
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


def scripted_llm(delay: float = 0.3) -> FakeLLM:
    return FakeLLM({
        "explainer": _explainer,
        "personaliser": _personaliser,
        "translator": _translator,
        "recap": lambda p: RecapDraft(headline="Match recap", summary="The key moments, explained.", key_points=[]),
    }, delay=delay, name="scripted")


def down_llm() -> FakeLLM:
    def fail(_prompt: str) -> Exception:
        return RuntimeError("model unavailable (simulated outage)")

    return FakeLLM({role: fail for role in ("explainer", "personaliser", "translator", "recap")}, name="down")
