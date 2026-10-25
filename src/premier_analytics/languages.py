"""The languages the desk works in (user request 10-25: English, Spanish, Arabic, plus the Premier League's
biggest broadcast markets). One list for every module; right-to-left only where the script needs it."""
from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Literal

Language = Literal["en", "es", "ar", "fr", "de", "it", "pt", "nl", "tr", "zh", "ja", "ko", "hi"]
LANGS: tuple[str, ...] = ("en", "es", "ar", "fr", "de", "it", "pt", "nl", "tr", "zh", "ja", "ko", "hi")
# Languages whose text is written with hand-tuned wording; the rest come from translated catalogues
# (scripts/translate_locales.py, checked by tests/test_languages.py).
HAND_WRITTEN = ("en", "es", "ar")
GENERATED = tuple(lang for lang in LANGS if lang not in HAND_WRITTEN)
RTL = frozenset({"ar"})

# English names, for model prompts ("Translate into …", "Answer in …").
LANGUAGE_NAMES = {
    "en": "English", "es": "Spanish", "ar": "Arabic", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese (Brazil)", "nl": "Dutch", "tr": "Turkish", "zh": "Simplified Chinese", "ja": "Japanese",
    "ko": "Korean", "hi": "Hindi",
}


def direction(language: str) -> Literal["ltr", "rtl"]:
    return "rtl" if language in RTL else "ltr"


@cache
def catalogue(language: str) -> dict:
    """Every backend string of a catalogued language: data/locales/<language>.json."""
    return json.loads((Path(__file__).parent / "data" / "locales" / f"{language}.json").read_text(encoding="utf-8"))
