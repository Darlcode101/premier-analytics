"""Moment Scout: T-5 key-moment detection, E-3 evidence, noise suppression, D-6 storylines."""
from statistics import mean

import pytest

from fixtures import AWAY, HOME, MIN, Fx
from premier_analytics.scout import ANALYST_THRESHOLD, FAN_THRESHOLD, MomentScout


def scout_all(fx: Fx):
    scout = MomentScout(HOME, AWAY, match_id="fx")
    moments = []
    for e in fx.events:
        moments += scout.observe(e)
    return moments


def run_match(m):
    scout = MomentScout(m.meta.home_id, m.meta.away_id, match_id=m.meta.match_id)
    out = []
    for e in m.events:
        out += scout.observe(e)
    return out


# ---------- single-event moments ----------

def test_goal_is_top_severity_with_evidence():
    fx = Fx()
    fx.kickoff(0)
    fx.pass_(3, HOME, 80, 20, 92, 34, player="h8", receiver="h9")
    s = fx.shot(5, HOME, 95, 33, outcome="goal", player="h9")
    g = fx.goal(5, HOME, s, 1, 0, assist="h8")
    moments = scout_all(fx)
    goals = [m for m in moments if m.kind == "goal"]
    assert len(goals) == 1
    gm = goals[0]
    assert gm.severity >= 0.9
    assert gm.event_id == g.id and gm.team_id == HOME and gm.player_id == "h9"
    labels = {f.label: f.value for f in gm.facts}
    assert labels["score_home"] == 1 and labels["score_away"] == 0
    assert labels["assist"] == "h8"
    assert 0 < labels["shot_xg"] < 1


def test_routine_back_pass_is_not_a_moment():
    fx = Fx()
    fx.kickoff(0)
    fx.pass_(3, HOME, 40, 30, 30, 30)
    assert scout_all(fx) == []


def test_big_chance_missed():
    fx = Fx()
    fx.kickoff(0)
    fx.shot(5, HOME, 100, 34, outcome="saved")  # xG well above 0.3
    kinds = {m.kind: m for m in scout_all(fx)}
    assert "big_chance" in kinds
    assert 0.6 <= kinds["big_chance"].severity < 0.9


def test_speculative_shot_is_minor():
    fx = Fx()
    fx.kickoff(0)
    fx.shot(5, HOME, 72, 34, outcome="off_target", speed=80)
    assert all(m.severity < FAN_THRESHOLD for m in scout_all(fx))


def test_rocket_shot_threshold_trigger():
    fx = Fx()
    fx.kickoff(0)
    fx.shot(5, HOME, 80, 34, outcome="saved", speed=118.0)
    kinds = {m.kind: m for m in scout_all(fx)}
    assert "rocket_shot" in kinds
    assert {f.label: f.value for f in kinds["rocket_shot"].facts}["shot_speed_kmh"] == 118.0


def test_red_card_and_yellow_card():
    fx = Fx()
    fx.kickoff(0)
    fx.foul(10, AWAY, 30, 30, player="a4")
    fx.card(10, AWAY, "a4", "yellow")
    fx.foul(20, AWAY, 30, 30, player="a4")
    fx.card(20, AWAY, "a4", "second_yellow")
    moments = scout_all(fx)
    red = [m for m in moments if m.kind == "red_card"]
    yellow = [m for m in moments if m.kind == "yellow_card"]
    assert len(red) == 1 and red[0].severity >= 0.85
    assert len(yellow) == 1 and yellow[0].severity < FAN_THRESHOLD


def test_brace_and_hat_trick_milestones():
    fx = Fx()
    fx.kickoff(0)
    score = 0
    for t in (60, 600, 1200):
        s = fx.shot(t, HOME, 96, 34, outcome="goal", player="h9")
        score += 1
        fx.goal(t, HOME, s, score, 0)
        fx.kickoff(t + 60, AWAY, player="a9")
        fx.change(t + 70, HOME)
    ms = [m for m in scout_all(fx) if m.kind == "milestone"]
    assert [round(m.severity, 2) >= 0.9 for m in ms] == [True, True]
    assert [{f.label: f.value for f in m.facts}["player_goals"] for m in ms] == [2, 3]


def test_late_equaliser_is_maximum_severity():
    fx = Fx()
    fx.kickoff(0, AWAY, player="a9")
    s1 = fx.shot(600, AWAY, 96, 34, outcome="goal", player="a9")
    fx.goal(600, AWAY, s1, 0, 1)
    fx.kickoff(660, HOME)
    s2 = fx.shot(87 * 60, HOME, 96, 34, outcome="goal", player="h9")
    fx.goal(87 * 60, HOME, s2, 1, 1)
    goals = [m for m in scout_all(fx) if m.kind == "goal"]
    assert goals[1].severity == 1.0
    assert goals[0].severity < 1.0


def test_half_time_and_full_time_summaries():
    fx = Fx()
    fx.add("period_start", 0)
    fx.kickoff(0)
    fx.add("period_end", 46 * 60, score_home=0, score_away=0)
    kinds = [m.kind for m in scout_all(fx)]
    assert kinds == ["half_time"]


# ---------- momentum and pressure (T-4 -> T-5) ----------

def dominate(fx: Fx, team: str, start_s: float, minutes: float):
    """`team` camps in the final third, shooting about once a minute."""
    other = AWAY if team == HOME else HOME
    fx.change(start_s, team, 50, 34)
    t = start_s + 1
    while t < start_s + minutes * 60:
        fx.pass_(t, team, 75, 20, 85, 40)
        fx.pass_(t + 4, team, 85, 40, 80, 25)
        if int(t - start_s) % 60 < 12:
            fx.shot(t + 6, team, 92, 30, outcome="saved")
            fx.change(t + 6, other, 6, 34, cause="save")
            fx.pass_(t + 9, other, 6, 34, 30, 30, outcome="incomplete")
            fx.change(t + 10, team, 75, 38)
        t += 12


def test_momentum_shift_detected_at_the_right_time():
    fx = Fx()
    fx.kickoff(0, AWAY, player="a9")
    dominate(fx, AWAY, 1, 12)        # away on top for 12 minutes
    dominate(fx, HOME, 12 * 60, 12)  # then home takes over
    shifts = [m for m in scout_all(fx) if m.kind == "momentum_shift"]
    home_shifts = [m for m in shifts if m.team_id == HOME]
    assert home_shifts, shifts
    minute = home_shifts[0].clock_ms / MIN
    assert 13 <= minute <= 21, minute
    facts = {f.label: f.value for f in home_shifts[0].facts}
    assert facts["momentum"] >= 0.5


def test_momentum_shift_has_cooldown():
    fx = Fx()
    fx.kickoff(0, AWAY, player="a9")
    dominate(fx, AWAY, 1, 12)
    dominate(fx, HOME, 12 * 60, 3)
    dominate(fx, AWAY, 15 * 60, 3)
    dominate(fx, HOME, 18 * 60, 3)
    shifts = [m for m in scout_all(fx) if m.kind == "momentum_shift"]
    times = [m.elapsed_ms for m in shifts]
    assert all(b - a >= 8 * MIN for a, b in zip(times, times[1:]))


def test_pressure_spell_detected():
    fx = Fx()
    fx.kickoff(0, AWAY, player="a9")
    dominate(fx, HOME, 1, 12)
    spells = [m for m in scout_all(fx) if m.kind == "pressure_spell"]
    assert spells and spells[0].team_id == HOME


# ---------- whole-match behaviour ----------

def test_goals_never_suppressed(many_matches):
    for m in many_matches[:30]:
        moments = run_match(m)
        goal_ids = {e.id for e in m.events if e.type == "goal"}
        goal_moments = {mo.event_id for mo in moments if mo.kind == "goal" and mo.severity >= FAN_THRESHOLD}
        assert goal_ids == goal_moments


def test_noise_suppression_rates(many_matches):
    fan, analyst = [], []
    for m in many_matches[:30]:
        moments = run_match(m)
        fan.append(sum(mo.severity >= FAN_THRESHOLD for mo in moments))
        analyst.append(sum(mo.severity >= ANALYST_THRESHOLD for mo in moments))
    assert 8 <= mean(fan) <= 45, mean(fan)        # a handful of big moments, well under 1/min
    assert max(fan) <= 95
    assert mean(analyst) >= 1.5 * mean(fan)       # analysts see more


def test_every_moment_has_traceable_evidence(match):
    moments = run_match(match)
    event_ids = {e.id for e in match.events}
    fact_ids = [f.id for mo in moments for f in mo.facts]
    assert len(fact_ids) == len(set(fact_ids))
    assert len({mo.id for mo in moments}) == len(moments)
    for mo in moments:
        assert mo.facts, mo.kind
        assert mo.event_id in event_ids
        for f in mo.facts:
            assert f.source_event_ids and set(f.source_event_ids) <= event_ids


def test_moments_are_deterministic(match):
    a = [mo.model_dump() for mo in run_match(match)]
    b = [mo.model_dump() for mo in run_match(match)]
    assert a == b


@pytest.mark.slow
def test_storylines_present(many_matches):
    """D-6: most matches contain at least one momentum swing worth explaining."""
    with_shift = sum(any(mo.kind == "momentum_shift" for mo in run_match(m)) for m in many_matches[:100])
    assert with_shift >= 80


def test_no_momentum_shift_from_passing_alone():
    """Final-third passing with no shots is territory, not momentum."""
    fx = Fx()
    fx.kickoff(0, HOME)
    for i in range(80):
        fx.pass_(i * 6, HOME, 75, 20, 85, 40)
    assert not [m for m in scout_all(fx) if m.kind == "momentum_shift"]


def test_momentum_shifts_cite_real_shots(many_matches):
    for m in many_matches[:20]:
        for mo in run_match(m):
            if mo.kind == "momentum_shift":
                assert {f.label: f.value for f in mo.facts}["window_shots"] >= 2


@pytest.mark.parametrize(
    "before, scorer, expected",
    [((0, 0), HOME, "takes_lead"), ((0, 1), HOME, "equaliser"), ((1, 0), HOME, "extends_lead"),
     ((0, 2), HOME, "pulls_one_back"), ((1, 1), AWAY, "takes_lead"), ((2, 1), AWAY, "equaliser")],
)
def test_goal_context_is_stated(before, scorer, expected):
    fx = Fx()
    fx.kickoff(0)
    h, a = before
    s = fx.shot(5, scorer, 95, 33, outcome="goal", player="h9" if scorer == HOME else "a9")
    fx.goal(5, scorer, s, h + (scorer == HOME), a + (scorer == AWAY))
    goal = next(m for m in scout_all(fx) if m.kind == "goal")
    assert {f.label: f.value for f in goal.facts}["goal_context"] == expected


def test_every_moment_carries_score_and_minute_context(many_matches):
    """Explanations can only say why a moment matters if they know the scoreline and the time."""
    m = many_matches[0]
    for mo in run_match(m):
        labels = {f.label for f in mo.facts}
        assert {"score_home", "score_away", "minute"} <= labels, (mo.kind, labels)
        if mo.kind in ("momentum_shift", "pressure_spell"):
            assert {"team_shots", "opponent_shots"} <= labels
