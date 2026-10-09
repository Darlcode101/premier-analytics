"""Deterministic statistics engine: T-1 .. T-4, T-6. Exact answers on golden fixtures."""
import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fixtures import AWAY, HOME, MIN, Fx
from premier_analytics.engine import MatchEngine, pass_difficulty, xg


def run(fx: Fx, window_ms=10 * MIN) -> MatchEngine:
    eng = MatchEngine(HOME, AWAY, window_ms=window_ms)
    for e in fx.events:
        eng.apply(e)
    return eng


# ---------- T-2 pass quality ----------

def test_pass_distance_exact():
    fx = Fx()
    fx.kickoff(0)
    p = fx.pass_(1, HOME, 0.0, 0.0, 30.0, 40.0)
    eng = MatchEngine(HOME, AWAY)
    eng.apply(fx.events[0])
    m = eng.apply(p)
    assert m.distance_m == pytest.approx(50.0)
    assert m.progressive_m == pytest.approx(30.0)


lengths = st.floats(min_value=1, max_value=70)
prog = st.floats(min_value=-30, max_value=50)
end_x = st.floats(min_value=0, max_value=105)


@given(lengths, prog, end_x, st.booleans())
def test_pass_difficulty_bounded(length, progressive, ex, pressed):
    assert 0.0 <= pass_difficulty(length, progressive, ex, pressed) <= 1.0


@given(lengths, prog, end_x, st.booleans(), st.floats(min_value=0.5, max_value=30))
def test_pass_difficulty_monotonic(length, progressive, ex, pressed, extra):
    base = pass_difficulty(length, progressive, ex, pressed)
    assert pass_difficulty(length + extra, progressive, ex, pressed) >= base
    assert pass_difficulty(length, progressive + extra, ex, pressed) >= base
    assert pass_difficulty(length, progressive, ex, True) >= base
    assert pass_difficulty(length, progressive, min(105.0, ex + extra), pressed) >= base


def test_pass_difficulty_examples():
    easy = pass_difficulty(8, -5, 30, False)       # short back-pass in own half
    hard = pass_difficulty(40, 30, 95, True)       # long ball into the box under pressure
    assert easy < 0.15
    assert hard > 0.7


# ---------- T-3 xG ----------

def test_xg_examples():
    assert xg(99.0, 34.0) > 0.35            # 6 m, central
    assert 0.15 <= xg(94.0, 34.0) <= 0.45   # penalty spot, open play
    assert xg(75.0, 34.0) < 0.06            # 30 m
    assert xg(103.0, 2.0) < 0.05            # byline, tight angle


@given(st.floats(min_value=60, max_value=104), st.floats(min_value=0.5, max_value=10))
def test_xg_decreases_with_distance(x, step):
    if x - step >= 52.5:
        assert xg(x - step, 34.0) <= xg(x, 34.0)


@given(st.floats(min_value=80, max_value=104), st.floats(min_value=0, max_value=30))
def test_xg_decreases_with_wider_angle(x, offset):
    assert xg(x, 34.0 + offset) <= xg(x, 34.0) + 1e-12


def test_xg_header_and_pressure_lower():
    assert xg(97, 34, header=True) < xg(97, 34)
    assert xg(97, 34, under_pressure=True) < xg(97, 34)


@given(st.floats(min_value=52.5, max_value=105), st.floats(min_value=0, max_value=68), st.booleans(), st.booleans())
def test_xg_bounded(x, y, header, pressed):
    assert 0.0 < xg(x, y, header=header, under_pressure=pressed) < 1.0


# ---------- T-1 totals and possession ----------

def golden_match() -> Fx:
    fx = Fx()
    fx.kickoff(0, HOME)
    fx.pass_(2, HOME, 52.5, 34, 40, 30)                          # complete
    fx.pass_(5, HOME, 40, 30, 70, 20)                            # complete
    fx.pass_(8, HOME, 70, 20, 90, 30, outcome="incomplete")
    fx.interception(8, AWAY, 15, 38)
    fx.change(8, AWAY, 15, 38)
    fx.pass_(20, AWAY, 15, 38, 50, 40)                           # complete
    fx.foul(30, HOME, 60, 30, player="h6")
    fx.card(30, HOME, "h6")
    fx.pass_(40, AWAY, 50, 40, 85, 30)                           # complete
    s1 = fx.shot(42, AWAY, 90, 34, outcome="saved")
    fx.change(60, HOME, 6, 34, cause="save")
    fx.pass_(70, HOME, 6, 34, 50, 34)                            # complete
    fx.pass_(80, HOME, 50, 34, 92, 36)                           # complete, final third
    s2 = fx.shot(85, HOME, 95, 33, outcome="goal", player="h9")
    fx.goal(85, HOME, s2, 1, 0, assist="h8")
    fx.kickoff(120, AWAY, player="a9")
    fx.tackle(125, HOME, 60, 34, outcome="won")
    fx.change(125, HOME, 60, 34, cause="tackle")
    return fx, s1, s2


def test_team_totals_golden():
    fx, s1, s2 = golden_match()
    snap = run(fx).snapshot()
    h, a = snap.teams[HOME], snap.teams[AWAY]
    assert snap.score == (1, 0)
    assert (h.passes, h.passes_completed) == (5, 4)
    assert (a.passes, a.passes_completed) == (2, 2)
    assert h.pass_accuracy == pytest.approx(0.8)
    assert (h.shots, h.shots_on_target, h.goals) == (1, 1, 1)
    assert (a.shots, a.shots_on_target, a.goals) == (1, 1, 0)
    assert h.xg == pytest.approx(xg(95, 33))
    assert a.xg == pytest.approx(xg(90, 34))
    assert (h.fouls, h.yellow_cards, h.red_cards) == (1, 1, 0)
    assert (h.tackles, h.tackles_won) == (1, 1)
    assert a.interceptions == 1


def test_player_totals_golden():
    fx, *_ = golden_match()
    snap = run(fx).snapshot()
    assert snap.players["h9"].goals == 1
    assert snap.players["h9"].shots == 1
    assert snap.players["h8"].assists == 1
    assert snap.players["h6"].yellow_cards == 1
    assert snap.players["a5"].interceptions == 1


def test_possession_time_based_golden():
    """home holds 0-8 s, away 8-60 s, home 60-120 s (goal stoppage counts to scorer),
    away 120-125 s, home 125 s onwards. Snapshot at 125 s."""
    fx, *_ = golden_match()
    snap = run(fx).snapshot()
    assert snap.teams[HOME].possession_pct == pytest.approx(100 * (8 + 60) / 125, abs=0.01)
    assert snap.teams[AWAY].possession_pct == pytest.approx(100 * (52 + 5) / 125, abs=0.01)


def test_snapshot_at_later_time_includes_ongoing_possession():
    fx, *_ = golden_match()
    eng = run(fx)
    snap = eng.snapshot(at_ms=225_000)  # home has held the ball 125-225 s
    assert snap.teams[HOME].possession_pct == pytest.approx(100 * (68 + 100) / 225, abs=0.01)


def test_totals_match_direct_counts_on_generated_match(match):
    """Incremental (event by event) totals equal counting the finished event list."""
    eng = MatchEngine(match.meta.home_id, match.meta.away_id)
    for e in match.events:
        eng.apply(e)
    snap = eng.snapshot()
    for team in (match.meta.home_id, match.meta.away_id):
        ev = [e for e in match.events if e.team_id == team]
        t = snap.teams[team]
        assert t.passes == sum(e.type == "pass" for e in ev)
        assert t.passes_completed == sum(e.type == "pass" and e.outcome == "complete" for e in ev)
        assert t.shots == sum(e.type == "shot" for e in ev)
        assert t.goals == sum(e.type == "goal" for e in ev)
        assert t.fouls == sum(e.type == "foul" for e in ev)
        assert t.yellow_cards == sum(e.type == "card" and e.card == "yellow" for e in ev)
        assert t.tackles_won == sum(e.type == "tackle" and e.outcome == "won" for e in ev)
    assert snap.teams[match.meta.home_id].possession_pct + snap.teams[match.meta.away_id].possession_pct == pytest.approx(100)
    final = match.events[-1]
    assert snap.score == (final.score_home, final.score_away)


# ---------- T-4 rolling windows, T-6 control vs chaos ----------

def one_way_pressure(minutes=10) -> Fx:
    """Away kicks off and loses it; then home camps in the final third for `minutes`."""
    fx = Fx()
    fx.kickoff(0, AWAY, player="a9")
    fx.change(5, HOME, 50, 34)
    t = 6.0
    while t < minutes * 60:
        fx.pass_(t, HOME, 75, 20, 85, 40)
        fx.pass_(t + 4, HOME, 85, 40, 80, 25)
        if int(t) % 60 < 8:
            fx.shot(t + 6, HOME, 92, 30, outcome="saved")
            fx.add("possession_change", t + 6, team_id=AWAY, cause="save", x=6, y=34)
            fx.pass_(t + 10, AWAY, 6, 34, 30, 30, outcome="incomplete")
            fx.change(t + 10, HOME, 75, 38)
        t += 12
    return fx


def test_momentum_and_field_tilt_under_one_way_pressure():
    snap = run(one_way_pressure()).snapshot()
    h, a = snap.teams[HOME], snap.teams[AWAY]
    assert h.window.momentum > 0.5
    assert a.window.momentum == pytest.approx(-h.window.momentum)
    assert h.window.field_tilt > 0.8
    assert h.window.field_tilt + a.window.field_tilt == pytest.approx(1.0)


def test_window_forgets_old_events():
    fx = one_way_pressure(minutes=10)
    eng = run(fx, window_ms=5 * MIN)
    late = eng.snapshot(at_ms=30 * MIN)  # nothing happened in the last 5 minutes
    assert late.teams[HOME].window.momentum == 0.0
    assert late.teams[HOME].window.field_tilt == 0.5


def test_ppda_golden():
    """Away makes 10 passes in their own 60 %; home makes 5 defensive actions in away's 60 %.
    PPDA(home) = 10 / 5 = 2.0."""
    fx = Fx()
    fx.kickoff(0, AWAY, player="a9")
    t = 1
    for i in range(10):
        fx.pass_(t, AWAY, 20, 30, 30, 30)
        t += 3
    for i in range(5):
        fx.tackle(t, HOME, 80, 30, outcome="lost")
        t += 3
    snap = run(fx).snapshot()
    assert snap.teams[HOME].window.ppda == pytest.approx(2.0)
    assert snap.teams[AWAY].window.ppda is None  # away made no defensive actions


def test_tempo_golden():
    fx = Fx()
    fx.kickoff(0, HOME)
    for i in range(30):
        fx.pass_(i * 10, HOME, 40, 30, 45, 30)  # 30 passes in 5 minutes
    eng = run(fx, window_ms=10 * MIN)
    snap = eng.snapshot(at_ms=5 * MIN)
    assert snap.teams[HOME].window.tempo == pytest.approx(30 / 5)


def test_chaos_higher_with_more_turnovers():
    calm, chaotic = Fx(), Fx()
    calm.kickoff(0, HOME)
    chaotic.kickoff(0, HOME)
    for i in range(60):
        calm.pass_(i * 5, HOME, 40, 30, 45, 30)
    team = HOME
    for i in range(60):
        team = AWAY if team == HOME else HOME
        chaotic.change(i * 5, team)
    c1 = run(calm).snapshot(at_ms=5 * MIN).chaos
    c2 = run(chaotic).snapshot(at_ms=5 * MIN).chaos
    assert 0.0 <= c1 < 0.2
    assert c2 > 0.8
    assert c2 <= 1.0


def test_snapshot_is_json_serialisable(match):
    eng = MatchEngine(match.meta.home_id, match.meta.away_id)
    for e in match.events[:500]:
        eng.apply(e)
    s = eng.snapshot().model_dump_json()
    assert '"possession_pct"' in s and not math.isnan(eng.snapshot().teams[match.meta.home_id].xg)
