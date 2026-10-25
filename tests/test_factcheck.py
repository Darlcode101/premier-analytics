"""FC-1..FC-3: the live fact-check. The Claim agent turns what the commentator said into structured claims;
the Fact-checker is plain code over the match tools and flags only clear errors."""
import asyncio
import re

import pytest
from fastapi.testclient import TestClient

from premier_analytics.agents import FakeLLM
from premier_analytics.app import create_app
from premier_analytics.factcheck import Claim, ClaimAgent, Claims, FactChecker, confirm_text, flag_text, worth_checking
from premier_analytics.generator import generate_match
from premier_analytics.mcp_server import MatchState, MatchTools
from premier_analytics.overlay import Names
from premier_analytics.scout import MomentScout
from premier_analytics.speech import speech_token
from premier_analytics.languages import LANGS

from test_app import collect, start


@pytest.fixture(scope="module")
def checker(league):
    m = generate_match("har", "ngc", 292, league)
    names = Names.from_league(league, "har", "ngc")
    scout = MomentScout("har", "ngc", m.meta.match_id)
    state = MatchState(names=names, scout=scout)
    for e in m.events:
        state.record(e)
        state.add_moments(scout.observe(e))
    return FactChecker(MatchTools(state))


def claim(subject, metric, value, since=None, quote="..."):
    return Claim(quote=quote, subject=subject, metric=metric, value=value, since_minute=since)


def test_only_lines_with_numbers_are_worth_checking():
    for line in ("That's Kowalczyk's third shot since he came on.", "Northgate have had 9 shots.",
                 "Wakefield-Ames scored in the 13th minute.", "Dos goles para el Harbourside.", "٣ تسديدات"):
        assert worth_checking(line), line
    for line in ("What a game this is.", "Harbourside are pushing on.", ""):
        assert not worth_checking(line), line


def test_spoken_numbers_up_to_a_hundred_and_percentages_are_checked():
    """Live check 10-25: 'about sixty percent of the ball' was skipped."""
    for line in ("Northgate have had about sixty percent of the ball", "seventy per cent possession",
                 "ninety minutes gone", "half a dozen shots", "sesenta por ciento de posesión"):
        assert worth_checking(line), line


def test_wrong_claims_are_flagged_with_the_right_number(checker):
    v = checker.check(claim("Kowalczyk", "shots", 3))
    assert v["verdict"] == "wrong" and v["actual"] == 1 and v["subject"] == "Zane Kowalczyk"
    assert v["evidence"].startswith("get_player_stats(")
    assert checker.check(claim("Zane Kowalczyk", "goals", 1))["verdict"] == "correct"


def test_team_claims_and_from_a_minute(checker):
    assert checker.check(claim("Northgate", "shots", 9, since=46))["verdict"] == "correct"
    wrong = checker.check(claim("Northgate", "shots", 7, since=46))
    assert wrong["verdict"] == "wrong" and wrong["actual"] == 9 and wrong["since_minute"] == 46
    assert checker.check(claim("Harbourside", "goals", 2))["verdict"] == "correct"


def test_tolerances_for_xg_and_possession(checker):
    tools = checker.tools
    poss = tools.get_team_stats("Northgate")["possession_pct"]
    assert checker.check(claim("Northgate", "possession_pct", round(poss) + 1))["verdict"] == "correct"
    assert checker.check(claim("Northgate", "possession_pct", round(poss) + 6))["verdict"] == "wrong"
    xg = tools.get_team_stats("Northgate")["xg"]
    assert checker.check(claim("Northgate", "xg", round(xg + 0.04, 2)))["verdict"] == "correct"
    assert checker.check(claim("Northgate", "xg", round(xg + 0.4, 2)))["verdict"] == "wrong"


def test_player_cards_and_fouls_can_be_checked(checker):
    """Live check 10-25: 'Ashworth has been booked twice' could not be checked. A second yellow is recorded
    as a red card, so bookings count the yellow plus the second yellow."""
    assert checker.check(claim("Ashworth", "yellow_cards", 2))["verdict"] == "correct"   # booked twice
    assert checker.check(claim("Ashworth", "red_cards", 1))["verdict"] == "correct"      # sent off
    wrong = checker.check(claim("Ashworth", "yellow_cards", 3))
    assert wrong["verdict"] == "wrong" and wrong["actual"] == 2
    fouls = checker.check(claim("Ashworth", "fouls", 0))
    assert fouls is not None and fouls["verdict"] in ("correct", "wrong")


def test_claims_the_data_cannot_settle_are_left_alone(checker):
    assert checker.check(claim("Nobody Atall", "goals", 1)) is None
    assert checker.check(claim("Northgate", "corners", 3, since=46)) is None  # not counted from a minute
    assert checker.check(claim("Northgate", "goals", 1, since=200)) is None    # not played yet


@pytest.mark.parametrize("language", LANGS)
def test_flags_say_the_right_number_plainly(checker, language):
    for c in (claim("Kowalczyk", "shots", 3), claim("Northgate", "shots", 7, since=46)):
        v = checker.check(c)
        text = flag_text(v, language)
        assert "{" not in text and str(v["actual"]) in text and str(int(c.value)) in text
        assert set(re.findall(r"\d+", text)) <= {str(v["actual"]), str(int(c.value)), "46"}


@pytest.mark.parametrize("language", LANGS)
def test_correct_claims_get_a_short_confirmation(checker, language):
    """Live check 10-25: correct claims were silent, so the desk looked unresponsive."""
    v = checker.check(claim("Kowalczyk", "goals", 1))
    text = confirm_text(v, language)
    assert "Zane Kowalczyk" in text and "1" in text and "{" not in text
    assert "not" not in text and " no " not in f" {text} "


def test_claim_agent_returns_structured_claims():
    llm = FakeLLM({"claims": lambda p: Claims(claims=[claim("Kowalczyk", "shots", 3, quote="third shot")])})
    out = asyncio.run(ClaimAgent(llm).extract("That's Kowalczyk's third shot.", "en"))
    assert [(c.subject, c.metric, c.value) for c in out] == [("Kowalczyk", "shots", 3)]
    assert "third shot" in llm.calls[0].prompt or "Kowalczyk" in llm.calls[0].prompt


# ---------- the speech token (FC-0: keyless) ----------

def test_speech_tokens_are_entra_tokens_tied_to_the_resource():
    async def entra(scope):
        assert scope == "https://cognitiveservices.azure.com/.default"
        return "tok123"
    out = asyncio.run(speech_token("/subscriptions/s/resourceGroups/g/providers/Microsoft.CognitiveServices/accounts/a",
                                   "switzerlandnorth", entra))
    assert out == {"status": "ok", "token": "aad#/subscriptions/s/resourceGroups/g/providers/Microsoft.CognitiveServices/accounts/a#tok123",
                   "region": "switzerlandnorth"}


# ---------- through the app ----------

def test_desk_says_a_line_and_only_that_desk_gets_the_flag(league):
    llm = FakeLLM({"claims": lambda p: Claims(claims=[claim("Kowalczyk", "shots", 3, quote="third shot")] if "Kowalczyk" in p else [])})
    with TestClient(create_app(llm=llm, live_session=False)) as c:
        mid = start(c, home="har", away="ngc", seed=292)
        with c.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as me, \
                c.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as other, \
                c.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as fan:
            for ws in (me, other, fan):
                collect(ws)
            me.send_json({"type": "said", "text": "That's Kowalczyk's third shot since he came on.", "id": "line-7"})
            got = me.receive_json()
            while got["type"] != "fact_check":
                got = me.receive_json()
            fan.send_json({"type": "said", "text": "That's Kowalczyk's third shot."})
        assert got["checked"] == 1 and len(got["flags"]) == 1 and got["id"] == "line-7"  # the desk matches reply to line
        assert [r["verdict"] for r in got["results"]] == ["wrong"]
        flag = got["flags"][0]
        assert flag["actual"] == 1 and "not 3" in flag["text"]["en"] and flag["evidence"]
        with c.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as late:
            hello = late.receive_json()
        assert "That's Kowalczyk" not in str(hello)  # nothing said is stored (FC-1)
        assert llm.count("claims") == 1             # the fan's line was ignored
