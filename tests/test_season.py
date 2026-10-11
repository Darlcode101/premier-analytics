"""CD-14: season context from a simulated season (table, form, players' season goals)."""
from collections import Counter

import pytest

from premier_analytics.generator import generate_match
from premier_analytics.season import club_context, schedule, simulate_season


@pytest.fixture(scope="module")
def season(league):
    return simulate_season(league)


def test_schedule_is_a_double_round_robin(league):
    clubs = [c.id for c in league.clubs]
    rounds = schedule(clubs)
    n = len(clubs)
    assert len(rounds) == 2 * (n - 1)
    for r in rounds:
        playing = [c for pair in r for c in pair]
        assert sorted(playing) == sorted(clubs)  # everyone plays exactly once per matchday
    pairs = Counter(pair for r in rounds for pair in r)
    assert set(pairs) == {(h, a) for h in clubs for a in clubs if h != a} and set(pairs.values()) == {1}
    first_half_home = Counter(h for r in rounds[: n - 1] for h, _ in r)
    assert all(abs(first_half_home[c] - (n - 1) / 2) <= 0.5 for c in clubs)  # 3 or 4 home games each of 7


def test_results_come_from_the_real_generator(league, season):
    first = season.results[0]
    m = generate_match(first.home, first.away, first.seed, league)
    goals = [e for e in m.events if e.type == "goal"]
    expected = (goals[-1].score_home, goals[-1].score_away) if goals else (0, 0)
    assert (first.home_goals, first.away_goals) == expected


def test_table_is_consistent(league, season):
    table = season.table()
    assert len(table) == len(league.clubs)
    for row in table:
        assert row.played == 2 * (len(league.clubs) - 1)
        assert row.points == 3 * row.won + row.drawn
        assert row.won + row.drawn + row.lost == row.played
    assert sum(r.goals_for for r in table) == sum(r.goals_against for r in table)
    keys = [(r.points, r.goals_for - r.goals_against, r.goals_for) for r in table]
    assert keys == sorted(keys, reverse=True)
    assert [r.position for r in table] == list(range(1, len(table) + 1))


def test_form_is_the_last_five_results_oldest_first(season):
    club = season.results[0].home
    games = [r for r in season.results if club in (r.home, r.away)]
    expected = []
    for r in games[-5:]:
        mine, theirs = (r.home_goals, r.away_goals) if r.home == club else (r.away_goals, r.home_goals)
        expected.append("W" if mine > theirs else "D" if mine == theirs else "L")
    assert season.form(club) == expected


def test_player_season_goals_equal_goal_events(league, season):
    goals: Counter = Counter()
    assists: Counter = Counter()
    for r in season.results:
        for e in generate_match(r.home, r.away, r.seed, league).events:
            if e.type == "goal":
                goals[e.player_id] += 1
                if e.assist_id:
                    assists[e.assist_id] += 1
    assert season.goals == goals and season.assists == assists


def test_season_is_deterministic(league, season):
    again = simulate_season(league)
    assert [(r.home, r.away, r.home_goals, r.away_goals) for r in again.results] == \
           [(r.home, r.away, r.home_goals, r.away_goals) for r in season.results]


def test_club_context_for_the_desk(league, season):
    club = league.clubs[0]
    ctx = club_context(season, league, club.id)
    row = next(r for r in season.table() if r.club_id == club.id)
    assert ctx["position"] == row.position and ctx["points"] == row.points
    assert ctx["form"] == season.form(club.id)
    squad = {p.id for p in league.squad(club.id)}
    assert set(ctx["players"]) <= squad
    assert all(v["goals"] == season.goals[pid] and v["assists"] == season.assists[pid]
               for pid, v in ctx["players"].items())
    scorers = ctx["top_scorers"]
    assert scorers == sorted(scorers, key=lambda s: (-s["goals"], s["player_id"]))[:3]
