"""D-4: aggregate stats over 200 matches land in real-football ranges (TEST_PLAN §2)."""
from statistics import mean

import pytest

pytestmark = pytest.mark.slow


def per_team(matches, fn):
    """fn(match, team_id) for both teams of every match, flattened."""
    return [fn(m, t) for m in matches for t in (m.meta.home_id, m.meta.away_id)]


def passes(m, t):
    return [e for e in m.events if e.type == "pass" and e.team_id == t]


def count(m, t, etype, **attrs):
    return sum(
        1 for e in m.events
        if e.type == etype and e.team_id == t and all(getattr(e, k) == v for k, v in attrs.items())
    )


def test_passes_per_team(many_matches):
    assert 350 <= mean(per_team(many_matches, lambda m, t: len(passes(m, t)))) <= 650


def test_pass_completion(many_matches):
    def completion(m, t):
        ps = passes(m, t)
        return sum(p.outcome == "complete" for p in ps) / len(ps)

    assert 0.70 <= mean(per_team(many_matches, completion)) <= 0.90


def test_shots_per_team(many_matches):
    assert 8 <= mean(per_team(many_matches, lambda m, t: count(m, t, "shot"))) <= 18


def test_shots_on_target_share(many_matches):
    def share(m, t):
        shots = [e for e in m.events if e.type == "shot" and e.team_id == t]
        return sum(s.outcome in ("goal", "saved") for s in shots) / max(len(shots), 1)

    assert 0.25 <= mean(per_team(many_matches, share)) <= 0.45


def test_goals_per_match(many_matches):
    assert 2.4 <= mean(sum(e.type == "goal" for e in m.events) for m in many_matches) <= 3.2


def test_goal_distribution_not_degenerate(many_matches):
    totals = [sum(e.type == "goal" for e in m.events) for m in many_matches]
    assert sum(t == 0 for t in totals) >= 5, "some 0-0s should happen"
    assert max(totals) >= 5, "occasional high-scoring games"
    assert max(totals) <= 12


def test_fouls_per_team(many_matches):
    assert 8 <= mean(per_team(many_matches, lambda m, t: count(m, t, "foul"))) <= 15


def test_yellow_cards_per_team(many_matches):
    assert 1 <= mean(per_team(many_matches, lambda m, t: count(m, t, "card", card="yellow"))) <= 3


def test_red_cards_rare(many_matches):
    reds = sum(e.type == "card" and e.card in ("red", "second_yellow") for m in many_matches for e in m.events)
    assert 0.03 <= reds / len(many_matches) <= 0.4


def test_substitutions_happen(many_matches):
    subs = per_team(many_matches, lambda m, t: count(m, t, "substitution"))
    assert 2.5 <= mean(subs) <= 5


def test_possession_varies_by_team_strength(many_matches):
    """Not every match is 50/50: some teams dominate the ball."""
    def pass_share(m):
        h = len(passes(m, m.meta.home_id))
        a = len(passes(m, m.meta.away_id))
        return h / (h + a)

    shares = [pass_share(m) for m in many_matches]
    assert min(shares) < 0.40 and max(shares) > 0.60


def test_better_attack_scores_more(many_matches, league):
    """Club attack rating should matter: top-half attacks outscore bottom-half attacks."""
    ranked = sorted(league.clubs, key=lambda c: c.attack)
    weak = {c.id for c in ranked[: len(ranked) // 2]}
    goals = {"weak": [], "strong": []}
    for m in many_matches:
        for t in (m.meta.home_id, m.meta.away_id):
            goals["weak" if t in weak else "strong"].append(count(m, t, "goal"))
    assert mean(goals["strong"]) > mean(goals["weak"])


def _final_snapshots(matches):
    from premier_analytics.engine import MatchEngine

    snaps = []
    for m in matches:
        eng = MatchEngine(m.meta.home_id, m.meta.away_id)
        for e in m.events:
            eng.apply(e)
        snaps.append(eng.snapshot())
    return snaps


def test_engine_xg_calibrated_to_generated_goals(many_matches):
    """The engine's xG model and the generator's finishing agree: total xG within 15 % of goals."""
    snaps = _final_snapshots(many_matches)
    total_xg = sum(t.xg for s in snaps for t in s.teams.values())
    total_goals = sum(t.goals for s in snaps for t in s.teams.values())
    assert abs(total_xg - total_goals) / total_goals <= 0.15, (total_xg, total_goals)


def test_typical_chaos_is_mid_range(many_matches):
    """Over full matches the chaos index should sit mid-scale, leaving room for calm and frantic spells."""
    from premier_analytics.engine import MatchEngine

    readings = []
    for m in many_matches[:40]:
        eng = MatchEngine(m.meta.home_id, m.meta.away_id)
        for i, e in enumerate(m.events):
            eng.apply(e)
            if i % 200 == 199:
                readings.append(eng.snapshot().chaos)
    assert 0.25 <= mean(readings) <= 0.75
    assert min(readings) < mean(readings) < max(readings)
