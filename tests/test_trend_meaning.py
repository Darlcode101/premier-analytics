"""E-4, E-5: trend moments carry their meaning as facts; comparisons in text are checked."""
import pytest

from premier_analytics.agents import CriticAgent
from premier_analytics.generator import generate_match
from premier_analytics.overlay import Names
from premier_analytics.scout import STAKES, MomentScout, Fact, Moment

TRENDS = ("momentum_shift", "pressure_spell")
MIN = 60_000


def trend_moments(seed):
    m = generate_match("har", "ngc", seed)
    scout = MomentScout("har", "ngc", m.meta.match_id)
    goals = []
    out = []
    for e in m.events:
        if e.type == "goal":
            goals.append(e)
        for mo in scout.observe(e):
            if mo.kind in TRENDS:
                out.append((mo, list(goals)))
    return out


def facts(mo):
    return {f.label: f.value for f in mo.facts}


@pytest.mark.parametrize("seed", [42, 7, 9])
def test_every_trend_moment_has_its_meaning(seed):
    moments = trend_moments(seed)
    assert moments
    for mo, _ in moments:
        f = facts(mo)
        assert f["stakes"] in STAKES.values()
        assert f["spell_rank"] in ("first spell on top", "strongest spell so far", "back on top", "another spell on top")
        assert isinstance(f["window_shots_before"], int) and isinstance(f["opponent_window_shots"], int)
        assert f["shots_trend"] in ("more shots than the 10 minutes before", "fewer shots than the 10 minutes before",
                                    "as many shots as the 10 minutes before")
        assert isinstance(f["goals_in_spell"], int)


@pytest.mark.parametrize("seed", [42, 7, 9])
def test_meaning_is_consistent_with_the_numbers(seed):
    seen_teams = set()
    for mo, goals in trend_moments(seed):
        f = facts(mo)
        mine, theirs = (f["score_home"], f["score_away"]) if mo.team_id == "har" else (f["score_away"], f["score_home"])
        diff = mine - theirs
        expected = ("opener" if mine == theirs == 0 else "level" if diff == 0 else
                    "one_down" if diff == -1 else "behind" if diff < -1 else "one_up" if diff == 1 else "ahead")
        assert f["stakes"] == STAKES[expected]
        before, now = f["window_shots_before"], f["window_shots"]
        trend = "more" if now > before else "fewer" if now < before else "as many"
        assert f["shots_trend"].startswith(trend)
        recent = [g for g in goals if g.team_id == mo.team_id and mo.elapsed_ms - g.elapsed_ms < 10 * MIN]
        assert f["goals_in_spell"] == len(recent)
        if mo.team_id not in seen_teams:
            assert f["spell_rank"] == "first spell on top"
        seen_teams.add(mo.team_id)


# ---------- E-5: comparisons ----------

NAMES = Names(home_id="har", away_id="ngc", clubs={"har": "Harbourside", "ngc": "Northgate"}, players={})
CRITIC = CriticAgent(set(), {"Harbourside", "Northgate"})


def trend(**values):
    fs = [Fact(id=f"m-f{i}", label=k, value=v, subject="har", source_event_ids=["e"]) for i, (k, v) in enumerate(values.items())]
    return Moment(id="m", kind="pressure_spell", severity=0.5, event_id="e", period=1, clock_ms=30 * MIN,
                  elapsed_ms=30 * MIN, team_id="har", facts=fs)


def problems(text, m):
    return CRITIC.review("Harbourside on top", text, m, NAMES).problems


def test_double_needs_two_facts_in_that_ratio():
    m = trend(team_shots=6, opponent_shots=5, window_shots=3, window_shots_before=3, spell_rank="back on top")
    assert any("double" in p for p in problems("Harbourside have double the shots of Northgate.", m))
    ok = trend(team_shots=10, opponent_shots=5, spell_rank="back on top")
    assert problems("Harbourside have double the shots of Northgate.", ok) == []
    ok2 = trend(window_shots=4, window_shots_before=2, spell_rank="back on top")
    assert problems("Twice as many shots as in the ten minutes before.", ok2) == []


def test_three_times_needs_that_ratio():
    m = trend(window_shots=4, window_shots_before=2, spell_rank="back on top")
    assert any("three times" in p for p in problems("Three times the shots of before.", m))


def test_superlatives_need_the_spell_fact():
    back = trend(spell_rank="back on top")
    assert any("strongest" in p for p in problems("Their strongest spell of the match.", back))
    assert any("first time" in p for p in problems("On top for the first time.", back))
    strongest = trend(spell_rank="strongest spell so far")
    assert problems("Their strongest spell of the match.", strongest) == []
    first = trend(spell_rank="first spell on top")
    assert problems("On top for the first time.", first) == []


def test_first_half_is_not_a_superlative():
    assert problems("Pressure building in the first half.", trend(spell_rank="back on top")) == []


def test_score_wording_must_match_the_stakes():
    from premier_analytics.scout import STAKES
    level = trend(stakes=STAKES["opener"], spell_rank="back on top", score_home=0, score_away=0)
    assert any("trail" in p for p in problems("Northgate dominate but trail 0-0.", level))
    assert problems("Northgate dominate but it's still 0-0.", level) == []
    up = trend(stakes=STAKES["one_up"], spell_rank="back on top")
    assert any("equalis" in p for p in problems("Harbourside push for an equaliser.", up))
    down = trend(stakes=STAKES["one_down"], spell_rank="back on top")
    assert any("protect" in p for p in problems("Harbourside protect their lead.", down))
