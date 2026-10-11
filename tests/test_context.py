"""CX-1..CX-6: real-world context (benchmarks and tactics explainers) for the commentator desk."""
import asyncio

import pytest

from premier_analytics.agents import FakeLLM
from premier_analytics.context import (
    REAL_CLUBS, AskDesk, ContextAgent, ContextCard, ContextEntry, ResearcherAgent, Source, TopicSpec, WebAnswer,
    check_card, entry_problems, load_library, numbers_in, verify_against_source,
)
from premier_analytics.overlay import Names
from premier_analytics.scout import Fact, Moment

NAMES = Names(home_id="har", away_id="ngc", clubs={"har": "Harbourside", "ngc": "Northgate"},
              players={"p9": "Kai Greaves"})
SRC = [Source(url="https://example.org/pl-2024-25", title="PL 2024/25 in numbers")]


LIB_FOR_APP = [
    ContextEntry(id="goals-per-match", kind="benchmark", topic="Goals per match", sources=SRC, retrieved="2026-10-11",
                 text="The 2024/25 Premier League averaged 2.93 goals per match.", numbers=[2.93],
                 tags=["goal", "half_time", "full_time", "big_chance", "momentum_shift", "pressure_spell"]),
    ContextEntry(id="explain-xg", kind="tactic", topic="Expected goals (xG)", sources=SRC, retrieved="2026-10-11",
                 text="Expected goals (xG) is the chance a shot is scored.", tags=["goal", "stat:xg"],
                 translations={"es": "Los goles esperados (xG) son la probabilidad de marcar.", "ar": "الأهداف المتوقعة."}),
]


def entry(**kw) -> ContextEntry:
    base = dict(id="goals-per-game", kind="benchmark", topic="Goals per match",
                text="The 2024/25 Premier League averaged 2.93 goals per match.", numbers=[2.93], sources=SRC,
                retrieved="2026-10-11", tags=["goal", "full_time"])
    return ContextEntry(**{**base, **kw})


def moment(kind="goal", facts=None) -> Moment:
    facts = facts or [Fact(id="m1-f1", label="score_home", value=2, source_event_ids=["e1"]),
                      Fact(id="m1-f2", label="team_xg", value=2.31, subject="har", source_event_ids=["e1"])]
    return Moment(id="m1", kind=kind, severity=0.9, event_id="e1", period=2, clock_ms=60 * 60_000,
                  elapsed_ms=62 * 60_000, team_id="har", player_id="p9", facts=facts)


class FakeSearch:
    def __init__(self, answer: WebAnswer | Exception | None = None, delay: float = 0.0):
        self.answer = answer
        self.delay = delay
        self.calls: list[str] = []

    async def search(self, question: str, instructions: str) -> WebAnswer:
        self.calls.append(question)
        if self.delay:
            await asyncio.sleep(self.delay)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


# ---------- library (CX-1) ----------

def test_numbers_in_reads_decimals_percentages_and_arabic_digits():
    assert numbers_in("2.93 goals, 45% possession and 1,234 passes") == [2.93, 45.0, 1234.0]
    assert numbers_in("٢٫٩٣ هدف") == [2.93]


def test_a_valid_entry_has_no_problems():
    assert entry_problems(entry()) == []


@pytest.mark.parametrize("change, problem", [
    (dict(sources=[]), "source"),
    (dict(sources=[Source(url="http://example.org/x", title="t")]), "https"),
    (dict(text="Average 3.1 goals per match.", numbers=[2.93]), "3.1"),
    (dict(text="Liverpool scored 2.93 goals per match."), "real club"),
    (dict(retrieved="last week"), "date"),
])
def test_entry_problems(change, problem):
    problems = entry_problems(entry(**change))
    assert any(problem in p for p in problems), problems


def test_tactics_explainers_may_name_real_clubs():
    e = entry(kind="tactic", text="High pressing, as Liverpool did under Klopp, wins the ball near goal.", numbers=[])
    assert entry_problems(e) == []


def test_verify_against_source_needs_every_number_on_the_page():
    pages = {"https://example.org/pl-2024-25": "<p>Goals per game: 2.93 across 380 matches</p>"}
    assert verify_against_source(entry(), pages.get) == []
    wrong = entry(text="The 2024/25 Premier League averaged 3.1 goals per match.", numbers=[3.1])
    assert verify_against_source(wrong, pages.get)
    assert verify_against_source(entry(), lambda url: None)  # page couldn't be fetched: not verified


def test_committed_library_is_valid():
    lib = load_library()
    assert lib, "library is empty"
    assert len({e.id for e in lib}) == len(lib)
    for e in lib:
        assert entry_problems(e) == [], (e.id, entry_problems(e))
    assert {e.kind for e in lib} == {"benchmark", "tactic"}


# ---------- researcher (CX-1, CX-3) ----------

def test_researcher_builds_entries_only_from_cited_answers():
    spec = TopicSpec(id="goals-per-game", kind="benchmark", topic="Goals per match",
                     question="Average goals per match in the 2024/25 Premier League?", tags=["goal"])
    cited = ResearcherAgent(FakeSearch(WebAnswer(text="The 2024/25 Premier League averaged 2.93 goals per match.", sources=SRC)))
    e = asyncio.run(cited.build_entry(spec, retrieved="2026-10-11"))
    assert e and e.numbers == [2.93] and e.sources == SRC and e.tags == ["goal"]
    uncited = ResearcherAgent(FakeSearch(WebAnswer(text="About 2.9 goals per match.", sources=[])))
    assert asyncio.run(uncited.build_entry(spec, retrieved="2026-10-11")) is None


# ---------- context cards (CX-2, CX-4) ----------

def test_card_numbers_must_come_from_the_entry_or_the_moment():
    m, e = moment(), entry()
    ok = ContextCard(entry_id=e.id, text="Harbourside's 2.31 xG already tops a typical real PL match, which averages 2.93 goals.")
    assert check_card(ok, e, m, NAMES) == []
    made_up = ContextCard(entry_id=e.id, text="Real PL matches average 3.4 goals.")
    assert any("3.4" in p for p in check_card(made_up, e, m, NAMES))


def test_card_may_not_name_real_clubs_or_use_another_entry():
    m, e = moment(), entry()
    assert any("real club" in p for p in check_card(ContextCard(entry_id=e.id, text="Like Arsenal, 2.93 a game."), e, m, NAMES))
    assert any("entry" in p for p in check_card(ContextCard(entry_id="other", text="2.93 a game."), e, m, NAMES))
    assert "Manchester City" in REAL_CLUBS and "Spurs" in REAL_CLUBS


def test_context_agent_picks_from_relevant_unused_entries():
    lib = [entry(), entry(id="red-cards", topic="Red cards", text="There were 30 red cards.", numbers=[30.0], tags=["red_card"]),
           entry(id="conversion", topic="Conversion", text="Shots convert 11% of the time.", numbers=[11.0], tags=["goal"])]
    agent = ContextAgent(FakeLLM({}), lib)
    assert [e.id for e in agent.candidates(moment("goal"), used=set())] == ["goals-per-game", "conversion"]
    assert [e.id for e in agent.candidates(moment("goal"), used={"goals-per-game"})] == ["conversion"]
    assert agent.candidates(moment("woodwork"), used=set()) == []


def test_context_agent_prompt_carries_entries_and_facts():
    seen = []

    def respond(prompt):
        seen.append(prompt)
        return ContextCard(entry_id="goals-per-game", text="2.93 goals a game is the real PL norm.")

    agent = ContextAgent(FakeLLM({"context": respond}), [entry()])
    res = asyncio.run(agent.run_full(moment(), NAMES, used=set()))
    assert res.value.entry_id == "goals-per-game"
    assert "[goals-per-game]" in seen[0] and "2.31" in seen[0]


# ---------- ask box (CX-3) ----------

ANSWER = WebAnswer(text="Real PL teams averaged 1.47 xG per match in 2024/25.", sources=SRC)


def test_ask_answers_with_sources_and_caches():
    search = FakeSearch(ANSWER)
    desk = AskDesk(ResearcherAgent(search), limit=15, timeout_s=1)
    first = asyncio.run(desk.ask("What is the average xG per team?", "en"))
    again = asyncio.run(desk.ask("  what is the average xG per team ", "en"))
    assert first["status"] == "ok" and first["sources"][0]["url"].startswith("https://")
    assert again["status"] == "cached" and again["text"] == first["text"]
    assert len(search.calls) == 1
    assert first["remaining"] == 14 and again["remaining"] == 14


def test_ask_answers_are_cleaned_like_library_entries():
    raw = WebAnswer(text="Teams average 1.47 xG,, according to FBref.\n\nSources:\n- FBref", sources=SRC)
    out = asyncio.run(AskDesk(ResearcherAgent(FakeSearch(raw)), limit=5, timeout_s=1).ask("xG?", "en"))
    assert out["text"] == "Teams average 1.47 xG."


def test_ask_limit_per_match():
    desk = AskDesk(ResearcherAgent(FakeSearch(ANSWER)), limit=2, timeout_s=1)
    statuses = [asyncio.run(desk.ask(f"question {i}", "en"))["status"] for i in range(3)]
    assert statuses == ["ok", "ok", "limit"]


def test_ask_timeout_off_topic_and_missing_sources():
    slow = AskDesk(ResearcherAgent(FakeSearch(ANSWER, delay=0.5)), limit=5, timeout_s=0.05)
    assert asyncio.run(slow.ask("xG?", "en"))["status"] == "timeout"
    off = AskDesk(ResearcherAgent(FakeSearch(WebAnswer(text="OFF_TOPIC", sources=[]))), limit=5, timeout_s=1)
    assert asyncio.run(off.ask("Who will win the election?", "en"))["status"] == "off_topic"
    bare = AskDesk(ResearcherAgent(FakeSearch(WebAnswer(text="About 1.5.", sources=[]))), limit=5, timeout_s=1)
    assert asyncio.run(bare.ask("xG?", "en"))["status"] == "no_source"
    down = AskDesk(ResearcherAgent(FakeSearch(RuntimeError("down"))), limit=5, timeout_s=1)
    assert asyncio.run(down.ask("xG?", "en"))["status"] == "error"


def test_ask_failures_do_not_use_up_the_allowance():
    desk = AskDesk(ResearcherAgent(FakeSearch(RuntimeError("down"))), limit=1, timeout_s=1)
    asyncio.run(desk.ask("one", "en"))
    desk.researcher = ResearcherAgent(FakeSearch(ANSWER))
    assert asyncio.run(desk.ask("two", "en"))["status"] == "ok"


def test_ask_passes_the_desk_language_to_the_researcher():
    class Spy(FakeSearch):
        async def search(self, question, instructions):
            self.instructions = instructions
            return ANSWER

    spy = Spy()
    asyncio.run(AskDesk(ResearcherAgent(spy), limit=5, timeout_s=1).ask("xG?", "es"))
    assert "Spanish" in spy.instructions


# ---------- second source and clean-up (CX-1) ----------

def test_years_at_the_end_of_a_sentence_are_not_figures():
    assert numbers_in("Introduced in 2023.") == []
    assert numbers_in("Since 1992, 2.93 a game.") == [2.93]
    assert numbers_in("En la temporada 24/25, el 31,7 %.") == [31.7]
    assert numbers_in("between 30% and 37%, 10-12 shots") == [30.0, 37.0, 10.0, 12.0]


def test_clean_answer_drops_source_lists_and_attributions():
    from premier_analytics.context import clean_answer
    raw = ("The 2024/25 Premier League averaged 2.93 goals per match, according to Wikipedia.\n\n"
           "Sources:\n- Wikipedia\n- The Analyst")
    assert clean_answer(raw) == "The 2024/25 Premier League averaged 2.93 goals per match."
    assert clean_answer("There were 2.93 goals per match in 2024/25.") == "There were 2.93 goals per match in 2024/25."
    assert clean_answer("It estimates chance quality,,.") == "It estimates chance quality."


def test_benchmarks_are_cross_checked_against_a_second_source():
    from premier_analytics.context import REFERENCE, cross_check
    assert cross_check(entry(id="goals-per-match"), REFERENCE) == []  # 2.93 agrees with docs/REALISM.md
    wrong = entry(id="shot-conversion", text="Shots were converted 8.5% of the time.", numbers=[8.5])
    assert cross_check(wrong, REFERENCE)
    unknown = entry(id="headed-goals", text="There were 150 headed goals.", numbers=[150.0])
    assert cross_check(unknown, REFERENCE) == []  # nothing to compare with: left to the person reviewing


def test_overlong_answers_are_not_kept():
    spec = TopicSpec(id="goals-per-match", kind="benchmark", topic="Goals", question="?", tags=["goal"])
    long = ResearcherAgent(FakeSearch(WebAnswer(text="2.93 goals per match. " + "Filler sentence here. " * 30, sources=SRC)))
    assert asyncio.run(long.build_entry(spec, retrieved="2026-10-11")) is None


@pytest.mark.parametrize("text", [
    "By the fourth matchweek, 18 goals had been scored from outside the box.",
    "There were approximately 157 headed goals, projected from the first 70 games.",
    "As of mid-season, 21 draws from 70 matches.",
    "Shots per team ranged from 8.82 to 17.1.",
])
def test_benchmarks_must_be_full_season_league_figures(text):
    e = entry(text=text, numbers=numbers_in(text))
    assert any("full-season" in p for p in entry_problems(e)), entry_problems(e)
