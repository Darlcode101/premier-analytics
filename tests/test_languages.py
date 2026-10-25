"""DK-12: 13 languages. Every catalogued language has every string English has, with the same placeholders,
so nothing on the desk depends on the AI to be in the caster's language."""
import json
import re
import string
from pathlib import Path

import pytest

from premier_analytics.context import ContextEntry, entry_problems
from premier_analytics.factcheck import _WORDS, confirm_text, flag_text
from premier_analytics.languages import GENERATED, LANGS, LANGUAGE_NAMES, catalogue, direction
from premier_analytics.overlay import LABELS, TEMPLATES
from premier_analytics.pattern_agent import CHANNEL_WORDS, FAN, TEXT
from premier_analytics.storylines import STORY_FIELDS, STORY_TEMPLATES
from premier_analytics.subs import _FAN, _STAT_WORDS, key_stat

LIBRARY = Path(__file__).parents[1] / "src/premier_analytics/data/context_library.json"


def fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def test_thirteen_languages_named_and_only_arabic_right_to_left():
    assert len(LANGS) == 13 == len(set(LANGS)) and set(LANGUAGE_NAMES) == set(LANGS)
    assert [lang for lang in LANGS if direction(lang) == "rtl"] == ["ar"]


@pytest.mark.parametrize("language", GENERATED)
def test_catalogues_have_every_section(language):
    c = catalogue(language)
    assert set(c) >= {"overlay", "labels", "channels", "patterns", "pattern_fan", "stat_words", "sub_fan",
                      "storylines", "factcheck"}, set(c)


@pytest.mark.parametrize("language", LANGS)
def test_overlay_templates_keep_englishs_placeholders(language):
    assert set(TEMPLATES[language]) == set(TEMPLATES["en"])
    for kind, slots in TEMPLATES["en"].items():
        theirs = TEMPLATES[language][kind]
        assert len(theirs) == 3 and all(s.strip() for s in theirs), (kind, theirs)
        for mine, other in zip(slots, theirs):
            assert fields(other) == fields(mine), (language, kind, other)
    assert set(LABELS[language]) == set(LABELS["en"]) and all(LABELS[language].values())


@pytest.mark.parametrize("language", LANGS)
def test_pattern_wording_keeps_englishs_placeholders(language):
    assert set(CHANNEL_WORDS[language]) == set(CHANNEL_WORDS["en"]) and all(CHANNEL_WORDS[language].values())
    assert set(TEXT[language]) == set(TEXT["en"])
    for key, text in TEXT["en"].items():
        assert fields(TEXT[language][key]) == fields(text), (language, key)
    assert set(FAN[language]) == set(FAN["en"])
    for key, text in FAN["en"].items():
        assert fields(FAN[language][key]) == fields(text), (language, key)


@pytest.mark.parametrize("language", GENERATED)
def test_substitution_lines_keep_englishs_placeholders(language):
    assert set(_STAT_WORDS[language]) == set(_STAT_WORDS["en"]) and all(_STAT_WORDS[language].values())
    assert set(_FAN[language]) == set(_FAN["en"])
    for key, text in _FAN["en"].items():
        mine = text[1] if isinstance(text, tuple) else text
        theirs = _FAN[language][key]
        for form in theirs if isinstance(theirs, tuple) else (theirs,):
            assert form and fields(form) == fields(mine), (language, key, form)
    line = key_stat({"goals": 1, "assists": 2, "passes": 34, "shots": 1, "ball_wins": 0}, language)
    assert all(n in line for n in ("1", "2")) and "{" not in line


@pytest.mark.parametrize("language", GENERATED)
def test_storyline_seeds_keep_their_placeholders(language):
    assert set(STORY_TEMPLATES[language]) == set(STORY_FIELDS)
    for kind, want in STORY_FIELDS.items():
        assert fields(STORY_TEMPLATES[language][kind]) == want, (language, kind)


@pytest.mark.parametrize("language", LANGS)
def test_fact_check_words_cover_every_metric(language):
    assert set(_WORDS[language]) == set(_WORDS["en"]) and all(_WORDS[language].values())
    v = {"subject": "Zane Kowalczyk", "metric": "possession_pct", "actual": 47, "claimed": 60, "since_minute": 46}
    for text in (flag_text(v, language), confirm_text(v, language)):
        assert "Zane Kowalczyk" in text and "47" in text and "46" in text and "{" not in text
    assert "60" in flag_text(v, language) and "60" not in confirm_text(v, language)


def test_tactics_explainers_exist_in_every_language_and_keep_their_numbers():
    entries = [ContextEntry(**e) for e in json.loads(LIBRARY.read_text())]
    explainers = [e for e in entries if any(t.startswith("stat:") for t in e.tags)]
    assert len(explainers) >= 5
    for e in explainers:
        assert set(e.translations) >= set(LANGS) - {"en"}, (e.id, sorted(set(LANGS) - set(e.translations)))
        assert all(e.translations[lang].strip() for lang in LANGS if lang != "en")
        assert entry_problems(e) == [], (e.id, entry_problems(e))


@pytest.mark.parametrize("language", GENERATED)
def test_catalogues_carry_no_english_leftovers_or_stray_braces(language):
    """A copied English line would pass the placeholder checks, so look for it."""
    raw = json.dumps(catalogue(language), ensure_ascii=False)
    for english in ("scores for", "this season", "is booked", "Last {wmin} min", "attacks into the final third"):
        assert english not in raw, (language, english)
    for s in re.findall(r'"((?:[^"\\]|\\.)*)"', raw):
        assert s.count("{") == s.count("}"), (language, s)


def test_every_data_file_ships_in_the_package():
    """The image pip-installs the package, so a data file the package-data globs miss is missing in production
    (caught 10-25: the new locales folder was not covered)."""
    import tomllib
    root = Path(__file__).parents[1]
    globs = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["premier_analytics"]
    pkg = root / "src/premier_analytics"
    assert set((pkg / "data").rglob("*.json")) <= {p for g in globs for p in pkg.glob(g)}
