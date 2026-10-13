"""Generator invariants: D-1, D-3, D-5. Each check also runs over many seeds via hypothesis."""
from collections import Counter

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from premier_analytics.generator import generate_match
from premier_analytics.schema import ON_BALL_TYPES, PITCH_LENGTH, PITCH_WIDTH

MIN = 60_000


# ---------- determinism (D-3) ----------

def test_same_seed_identical(fixture_pair):
    home, away = fixture_pair
    assert generate_match(home, away, seed=7).to_jsonl() == generate_match(home, away, seed=7).to_jsonl()


def test_different_seed_differs(fixture_pair):
    home, away = fixture_pair
    assert generate_match(home, away, seed=1).to_jsonl() != generate_match(home, away, seed=2).to_jsonl()


def test_unknown_club_rejected(fixture_pair):
    with pytest.raises(ValueError):
        generate_match("nope", fixture_pair[1], seed=1)


def test_club_cannot_play_itself(fixture_pair):
    with pytest.raises(ValueError):
        generate_match(fixture_pair[0], fixture_pair[0], seed=1)


# ---------- invariant checks, reused by the property test ----------

def check_ids_and_sequence(m):
    assert [e.seq for e in m.events] == list(range(len(m.events)))
    assert len({e.id for e in m.events}) == len(m.events)
    assert all(e.match_id == m.meta.match_id for e in m.events)


def check_time_ordering(m):
    elapsed = [e.elapsed_ms for e in m.events]
    assert elapsed == sorted(elapsed), "elapsed_ms must be non-decreasing"
    for period in (1, 2):
        clocks = [e.clock_ms for e in m.events if e.period == period]
        assert clocks == sorted(clocks)
    assert [e.period for e in m.events] == sorted(e.period for e in m.events)
    assert all(e.clock_ms >= 45 * MIN for e in m.events if e.period == 2)


def check_match_structure(m):
    types = [e.type for e in m.events]
    assert types[0] == "period_start" and m.events[0].period == 1
    assert types[1] == "kickoff"
    assert types[-1] == "period_end" and m.events[-1].period == 2
    period_ends = [e for e in m.events if e.type == "period_end"]
    assert len(period_ends) == 2
    assert period_ends[0].clock_ms >= 45 * MIN and period_ends[0].clock_ms <= 52 * MIN
    assert period_ends[1].clock_ms >= 90 * MIN and period_ends[1].clock_ms <= 100 * MIN
    for i, e in enumerate(m.events):
        if e.type == "period_start" and e.period == 2:
            assert m.events[i + 1].type == "kickoff"


def check_coordinates(m):
    for e in m.events:
        for v, hi in ((e.x, PITCH_LENGTH), (e.end_x, PITCH_LENGTH), (e.y, PITCH_WIDTH), (e.end_y, PITCH_WIDTH)):
            if v is not None:
                assert 0 <= v <= hi, e


def check_score_matches_goals(m):
    goals = [e for e in m.events if e.type == "goal"]
    by_team = Counter(g.team_id for g in goals)
    final = m.events[-1]
    assert final.score_home == by_team[m.meta.home_id]
    assert final.score_away == by_team[m.meta.away_id]
    ids = {e.id: e for e in m.events}
    home = away = 0
    for g in goals:
        shot = ids[g.related_event_id]
        assert shot.type == "shot" and shot.outcome == "goal" and shot.team_id == g.team_id
        assert shot.player_id == g.player_id
        home += g.team_id == m.meta.home_id
        away += g.team_id == m.meta.away_id
        assert (g.score_home, g.score_away) == (home, away)
    goal_shots = [e for e in m.events if e.type == "shot" and e.outcome == "goal"]
    assert len(goal_shots) == len(goals)


def check_kickoff_after_goal(m):
    for i, e in enumerate(m.events):
        if e.type == "goal":
            nxt = next(x for x in m.events[i + 1:] if x.type in ("kickoff", "period_end"))
            if nxt.type == "kickoff":
                assert nxt.team_id != e.team_id, "conceding team kicks off"


def check_players_on_pitch(m, league):
    """Only on-pitch players act; subs and red cards respected; squads and limits respected."""
    on_pitch = {t: set(m.meta.lineups[t].starting) for t in (m.meta.home_id, m.meta.away_id)}
    bench = {t: set(m.meta.lineups[t].bench) for t in on_pitch}
    used = set()
    subs = Counter()
    yellows = Counter()
    for e in m.events:
        team = e.team_id
        if e.type == "substitution":
            assert e.player_out_id in on_pitch[team]
            assert e.player_in_id in bench[team] and e.player_in_id not in used
            on_pitch[team].remove(e.player_out_id)
            on_pitch[team].add(e.player_in_id)
            bench[team].discard(e.player_in_id)
            used.add(e.player_out_id)
            subs[team] += 1
            continue
        for pid in (e.player_id, e.receiver_id, e.fouled_player_id, e.assist_id):
            if pid is None:
                continue
            owner = league.player(pid).club_id
            assert pid in on_pitch[owner], f"{pid} acted off pitch at seq {e.seq} ({e.type})"
        if e.player_id is not None and team is not None:
            assert league.player(e.player_id).club_id == team
        if e.receiver_id is not None:
            assert league.player(e.receiver_id).club_id == team and e.receiver_id != e.player_id
        if e.type == "card":
            if e.card == "yellow":
                yellows[e.player_id] += 1
                assert yellows[e.player_id] == 1, "second yellow must be recorded as second_yellow"
            if e.card in ("second_yellow", "red"):
                if e.card == "second_yellow":
                    assert yellows[e.player_id] == 1
                on_pitch[team].remove(e.player_id)
                used.add(e.player_id)
    for team in on_pitch:
        assert subs[team] <= 5
        assert len(on_pitch[team]) <= 11


def check_possession_coherent(m):
    """Passes and shots only by the team in possession; possession only moves via
    kickoff or possession_change events, and possession_change actually changes it."""
    possession = None
    for e in m.events:
        if e.type == "kickoff":
            possession = e.team_id
        elif e.type == "possession_change":
            assert e.team_id != possession, f"no-op possession change at seq {e.seq}"
            possession = e.team_id
        elif e.type in ON_BALL_TYPES:
            assert e.team_id == possession, f"{e.type} by non-possessing team at seq {e.seq}"


def check_lost_ball_followed_by_change(m):
    """A failed pass, a won tackle or an interception hands the ball over."""
    for i, e in enumerate(m.events):
        handover = (
            (e.type == "pass" and e.outcome in ("incomplete", "out"))
            or (e.type == "tackle" and e.outcome == "won")
            or e.type == "interception"
        )
        if handover:
            nxt = next(x for x in m.events[i + 1:] if x.type not in ("pressure", "card", "foul"))
            allowed = {"possession_change", "period_end"}
            if e.type == "pass":
                allowed.add("interception")  # pass -> interception -> possession_change
                allowed.add("corner")        # D-10: cleared behind, the attacking side keeps it
            assert nxt.type in allowed, f"seq {e.seq} {e.type} -> {nxt.type}"


ALL_CHECKS = [
    check_ids_and_sequence, check_time_ordering, check_match_structure, check_coordinates,
    check_score_matches_goals, check_kickoff_after_goal, check_possession_coherent,
    check_lost_ball_followed_by_change,
]


@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda c: c.__name__)
def test_invariant_seed_42(match, check):
    check(match)


def test_players_on_pitch_seed_42(match, league):
    check_players_on_pitch(match, league)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(seed=st.integers(min_value=0, max_value=2**31 - 1), pair=st.integers(min_value=0, max_value=55))
def test_invariants_hold_for_any_seed(seed, pair, league):
    clubs = [c.id for c in league.clubs]
    home = clubs[pair % len(clubs)]
    away = clubs[(pair // len(clubs) + 1 + pair) % len(clubs)]
    if home == away:
        away = clubs[(clubs.index(home) + 1) % len(clubs)]
    m = generate_match(home, away, seed=seed)
    for check in ALL_CHECKS:
        check(m)
    check_players_on_pitch(m, league)


# ---------- content (D-1) ----------

def test_all_required_event_types_occur(match):
    types = {e.type for e in match.events}
    required = {
        "period_start", "period_end", "kickoff", "pass", "shot", "tackle", "interception",
        "pressure", "possession_change", "foul",
    }
    assert required <= types, required - types


def test_metadata_present(match, fixture_pair):
    meta = match.meta
    assert (meta.home_id, meta.away_id) == fixture_pair
    assert meta.venue and meta.referee and meta.weather.condition
    assert -10 <= meta.weather.temp_c <= 40
    assert meta.seed == 42


def test_shot_fields_plausible(match):
    for e in match.events:
        if e.type == "shot":
            assert 30 <= e.shot_speed_kmh <= 140
            assert e.x >= PITCH_LENGTH / 2, "shots come from the attacking half"


def test_identical_across_processes(fixture_pair):
    """Guards against hidden dependence on set/dict ordering, which varies per process."""
    import hashlib
    import os
    import subprocess
    import sys
    from pathlib import Path

    home, away = fixture_pair
    code = (
        "import hashlib; from premier_analytics.generator import generate_match as g; "
        f"print(hashlib.sha256(g({home!r}, {away!r}, 42).to_jsonl().encode()).hexdigest())"
    )
    src = str(Path(__file__).parent.parent / "src")
    digests = {
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True,
            env={**os.environ, "PYTHONHASHSEED": str(h), "PYTHONPATH": src},
        ).stdout.strip()
        for h in (1, 2, 999)
    }
    in_process = hashlib.sha256(generate_match(home, away, 42).to_jsonl().encode()).hexdigest()
    assert digests == {in_process}


def test_a_substitute_is_never_taken_off_again(league):
    """SB-1 made this visible: a player who came on stays on (barring a red card)."""
    for seed in range(30):
        came_on = set()
        for e in generate_match("har", "ngc", seed, league).events:
            if e.type == "substitution":
                assert e.player_out_id not in came_on, (seed, e.player_out_id)
                came_on.add(e.player_in_id)
