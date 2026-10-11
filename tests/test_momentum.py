"""Attack momentum: a per-minute series where every bar carries the numbers that drive it."""
import pytest

from fixtures import AWAY, HOME, MIN, Fx
from premier_analytics.engine import MatchEngine
from premier_analytics.momentum import AttackMomentum


def run(fx: Fx):
    eng = MatchEngine(HOME, AWAY)
    am = AttackMomentum(HOME, AWAY)
    for e in fx.events:
        am.observe(e, eng.apply(e))
    return am.series()


def test_shots_and_final_third_passes_push_the_bar_towards_that_team():
    fx = Fx()
    fx.kickoff(0)
    fx.pass_(4 * 60 + 5, HOME, 60, 30, 80, 30)        # final-third entry, minute 4
    fx.shot(4 * 60 + 10, HOME, 95, 34, outcome="saved")
    s = run(fx)
    point = next(p for p in s if p["minute"] == 4)
    assert point["value"] > 0.3
    assert point["home"]["shots"] == 1 and point["home"]["final_third_passes"] == 1
    assert point["home"]["xg"] > 0
    assert point["away"] == {"shots": 0, "xg": 0.0, "final_third_passes": 0, "high_regains": 0}


def test_away_pressure_points_the_other_way_and_counts_high_regains():
    fx = Fx()
    fx.kickoff(0)
    fx.tackle(10 * 60, AWAY, 70, 30, outcome="won")    # in the home half, from away's perspective x >= 52.5
    fx.interception(10 * 60 + 5, AWAY, 60, 30)
    fx.shot(10 * 60 + 20, AWAY, 90, 30, outcome="off_target")
    point = next(p for p in run(fx) if p["minute"] == 10)
    assert point["value"] < -0.3
    assert point["away"]["high_regains"] == 2 and point["away"]["shots"] == 1


def test_bars_are_smoothed_over_three_minutes_and_bounded():
    fx = Fx()
    fx.kickoff(0)
    fx.shot(5 * 60, HOME, 95, 34, outcome="saved")
    fx.pass_(8 * 60 + 30, HOME, 40, 30, 45, 30)  # keeps the clock running to minute 8
    s = {p["minute"]: p for p in run(fx)}
    # a minute-5 shot still counts for minutes 6 and 7 (rolling three-minute window), not minute 8
    assert s[5]["value"] > 0 and s[7]["value"] > 0 and s[8]["value"] == 0
    assert s[7]["window"] == [5, 7]


def test_one_point_per_elapsed_minute_on_a_full_match(match):
    eng = MatchEngine(match.meta.home_id, match.meta.away_id)
    am = AttackMomentum(match.meta.home_id, match.meta.away_id)
    for e in match.events:
        am.observe(e, eng.apply(e))
    s = am.series()
    minutes = [p["minute"] for p in s]
    assert minutes == list(range(len(s)))
    assert len(s) >= 90
    assert all(-1 < p["value"] < 1 for p in s)
    shots = sum(m[t]["shots"] for m in am.per_minute() for t in m)  # raw counts, not the rolling windows
    assert shots == sum(e.type == "shot" for e in match.events)


@pytest.mark.parametrize("minute", [0, 1])
def test_first_minutes_have_points_even_when_quiet(minute):
    fx = Fx()
    fx.kickoff(0)
    fx.pass_(90, HOME, 40, 30, 45, 30)
    s = {p["minute"]: p for p in run(fx)}
    assert s[minute]["value"] == 0


def test_points_carry_a_broadcast_clock_label(match):
    eng = MatchEngine(match.meta.home_id, match.meta.away_id)
    am = AttackMomentum(match.meta.home_id, match.meta.away_id)
    for e in match.events:
        am.observe(e, eng.apply(e))
    labels = [p["label"] for p in am.series()]
    assert labels[0] == "1"
    assert any(label.startswith("45+") for label in labels)   # first-half stoppage time
    assert labels[-1].startswith("90+")
