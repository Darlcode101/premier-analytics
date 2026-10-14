"""D-4: a synthetic 380-match season matches real 2024/25 Premier League averages.

Targets and sources: docs/REALISM.md. Each test states the real value and tolerance.
"""
from collections import defaultdict
from statistics import mean

import pytest

from premier_analytics.engine import MatchEngine

pytestmark = pytest.mark.slow

BOX_X = 105 - 16.5
BOX_Y = (34 - 20.16, 34 + 20.16)


def per_team(matches, fn):
    return [fn(m, t) for m in matches for t in (m.meta.home_id, m.meta.away_id)]


def passes(m, t):
    return [e for e in m.events if e.type == "pass" and e.team_id == t]


def count(m, t, etype, **attrs):
    return sum(
        1 for e in m.events
        if e.type == etype and e.team_id == t and all(getattr(e, k) == v for k, v in attrs.items())
    )


def shots(matches):
    return [e for m in matches for e in m.events if e.type == "shot"]


def in_box(s):
    return s.x >= BOX_X and BOX_Y[0] <= s.y <= BOX_Y[1]


def near(actual, target, tol):
    return abs(actual - target) <= tol


# ---------- sourced targets ----------

def test_goals_per_match(season):
    g = mean(sum(e.type == "goal" for e in m.events) for m in season)
    assert near(g, 2.93, 0.25), g


def test_passes_per_team(season):
    p = mean(per_team(season, lambda m, t: len(passes(m, t))))
    assert near(p, 447, 44.7), p


def test_pass_completion(season):
    done = sum(e.outcome == "complete" for m in season for e in m.events if e.type == "pass")
    total = sum(e.type == "pass" for m in season for e in m.events)
    assert near(done / total, 0.834, 0.025), done / total


def test_shots_per_team(season):
    s = mean(per_team(season, lambda m, t: count(m, t, "shot")))
    assert near(s, 13.1, 1.5), s


def test_outside_box_shot_share(season):
    ss = shots(season)
    share = sum(not in_box(s) for s in ss) / len(ss)
    assert near(share, 0.317, 0.06), share


def test_conversion_overall(season):
    ss = shots(season)
    conv = sum(s.outcome == "goal" for s in ss) / len(ss)
    assert near(conv, 0.112, 0.015), conv


def test_conversion_inside_and_outside_box(season):
    ss = shots(season)
    inside = [s for s in ss if in_box(s)]
    outside = [s for s in ss if not in_box(s)]
    c_in = sum(s.outcome == "goal" for s in inside) / len(inside)
    c_out = sum(s.outcome == "goal" for s in outside) / len(outside)
    assert near(c_in, 0.147, 0.03), c_in
    assert near(c_out, 0.042, 0.02), c_out


def test_fouls_per_team(season):
    f = mean(per_team(season, lambda m, t: count(m, t, "foul")))
    assert near(f, 11.1, 1.2), f


def test_yellow_cards_per_team(season):
    y = mean(per_team(season, lambda m, t: count(m, t, "card", card="yellow")))
    assert near(y, 2.04, 0.3), y


def test_red_cards_per_match(season):
    reds = sum(e.type == "card" and e.card in ("red", "second_yellow") for m in season for e in m.events)
    assert near(reds / len(season), 0.137, 0.07), reds / len(season)


def test_result_distribution(season):
    home = draw = away = 0
    for m in season:
        f = m.events[-1]
        if f.score_home > f.score_away:
            home += 1
        elif f.score_home == f.score_away:
            draw += 1
        else:
            away += 1
    n = len(season)
    assert near(home / n, 0.408, 0.06), home / n
    assert near(draw / n, 0.245, 0.06), draw / n
    assert near(away / n, 0.347, 0.06), away / n


# ---------- club spread ----------

def club_averages(season, fn):
    by_club = defaultdict(list)
    for m in season:
        for t in (m.meta.home_id, m.meta.away_id):
            by_club[t].append(fn(m, t))
    return {c: mean(v) for c, v in by_club.items()}


def test_club_passing_spread(season):
    avg = club_averages(season, lambda m, t: len(passes(m, t)))
    assert max(avg.values()) >= 540, avg
    assert min(avg.values()) <= 380, avg


def test_club_completion_spread(season):
    def completion(m, t):
        ps = passes(m, t)
        return sum(p.outcome == "complete" for p in ps) / len(ps)

    avg = club_averages(season, completion)
    assert max(avg.values()) >= 0.87, avg
    assert min(avg.values()) <= 0.79, avg


def test_better_attack_scores_more(season, league):
    ranked = sorted(league.clubs, key=lambda c: c.attack)
    weak = {c.id for c in ranked[: len(ranked) // 2]}
    goals = {"weak": [], "strong": []}
    for m in season:
        for t in (m.meta.home_id, m.meta.away_id):
            goals["weak" if t in weak else "strong"].append(count(m, t, "goal"))
    assert mean(goals["strong"]) > mean(goals["weak"]) * 1.25


# ---------- plausibility (no sourced target, see docs/REALISM.md) ----------

def test_shots_on_target_share(season):
    def share(m, t):
        ss = [e for e in m.events if e.type == "shot" and e.team_id == t]
        return sum(s.outcome in ("goal", "saved") for s in ss) / max(len(ss), 1)

    assert 0.28 <= mean(per_team(season, share)) <= 0.42


def test_goal_distribution_not_degenerate(season):
    totals = [sum(e.type == "goal" for e in m.events) for m in season]
    assert 0.04 <= totals.count(0) / len(totals) <= 0.12, "0-0s happen but aren't common"
    assert max(totals) >= 6
    assert max(totals) <= 12


def test_substitutions_happen(season):
    assert 3 <= mean(per_team(season, lambda m, t: count(m, t, "substitution"))) <= 5


# ---------- engine agrees with generator ----------

def _final_snapshots(matches):
    snaps = []
    for m in matches:
        eng = MatchEngine(m.meta.home_id, m.meta.away_id)
        for e in m.events:
            eng.apply(e)
        snaps.append(eng.snapshot())
    return snaps


def test_engine_xg_calibrated_to_generated_goals(season):
    """The engine's xG model and the generator's finishing agree: total xG within 10 % of goals."""
    snaps = _final_snapshots(season)
    total_xg = sum(t.xg for s in snaps for t in s.teams.values())
    total_goals = sum(t.goals for s in snaps for t in s.teams.values())
    assert abs(total_xg - total_goals) / total_goals <= 0.10, (total_xg, total_goals)


def test_typical_chaos_is_mid_range(season):
    readings = []
    for m in season[:40]:
        eng = MatchEngine(m.meta.home_id, m.meta.away_id)
        for i, e in enumerate(m.events):
            eng.apply(e)
            if i % 200 == 199:
                readings.append(eng.snapshot().chaos)
    assert 0.25 <= mean(readings) <= 0.75
    assert min(readings) < mean(readings) < max(readings)


def test_card_reasons_follow_the_real_mix(season):
    """F-6b: why players are booked. Estimates from 2023/24 reporting (docs/REALISM.md): dissent about 14 %,
    time-wasting about 8 %, handball a few %, the rest fouls."""
    reasons = [e.card_reason for m in season for e in m.events if e.type == "card" and e.card != "red"]
    share = lambda r: sum(x == r for x in reasons) / len(reasons)  # noqa: E731
    assert 0.10 <= share("dissent") <= 0.19, share("dissent")
    assert 0.04 <= share("time_wasting") <= 0.12, share("time_wasting")
    assert 0.02 <= share("handball") <= 0.08, share("handball")
    assert share("late_tackle") > share("tactical_foul") > 0 and share("holding") > 0
