"""PA-2, PA-3, PA-9: pattern detectors, significance, and their accuracy over a simulated season."""
import pytest

from premier_analytics.generator import generate_match
from premier_analytics.patterns import PatternTracker, binomial_tail, channel_of
from premier_analytics.schema import PITCH_WIDTH
from premier_analytics.season import HISTORY_SEASONS, simulate_season

W = PITCH_WIDTH


def track(home, away, seed, league, season=None):
    m = generate_match(home, away, seed, league)
    t = PatternTracker(home, away, season_profiles=season)
    for e in m.events:
        t.observe(e)
    return t, m


def test_binomial_tail():
    assert binomial_tail(0, 10, 0.3) == pytest.approx(1.0)
    assert binomial_tail(10, 10, 0.5) == pytest.approx(0.5 ** 10)
    assert binomial_tail(5, 10, 0.5) == pytest.approx(0.623046875)


def test_channels_are_named_from_the_attacking_teams_view():
    assert channel_of(5) == "left" and channel_of(W / 2) == "centre" and channel_of(W - 5) == "right"


def test_counts_match_the_events(league):
    t, m = track("har", "ngc", 42, league)
    entries = [e for e in m.events if e.type == "pass" and e.outcome == "complete" and e.team_id == "har"
               and e.x < 70 <= e.end_x]
    s = t.summary("har")
    assert sum(s["entries"].values()) == len(entries)
    assert s["entries"]["left"] == sum(channel_of(e.end_y) == "left" for e in entries)
    shots = [e for e in m.events if e.type == "shot" and e.team_id == "har"]
    assert len(s["shots"]) == len(shots)
    regains = [e for e in m.events if e.team_id == "har" and (e.type == "interception" or (e.type == "tackle" and e.outcome == "won"))]
    assert sum(s["regains"].values()) == len(regains)


def test_every_pattern_is_significant_and_carries_its_numbers(league):
    for seed in (42, 7, 9, 11):
        t, _ = track("har", "kin", seed, league)
        for p in t.patterns():
            assert p.p_value < 0.01 and p.total >= 6 and 0 < p.count <= p.total
            assert p.share == pytest.approx(p.count / p.total)
            assert p.team_id in ("har", "kin") and p.kind in ("flank", "high_regains", "long_shots", "hub", "counters", "switch", "unusual")


def test_patterns_are_stable_ids_and_sorted_by_strength(league):
    t, _ = track("har", "kin", 42, league)
    ps = t.patterns()
    assert len({p.id for p in ps}) == len(ps)
    assert [p.p_value for p in ps] == sorted(p.p_value for p in ps)


def test_second_half_switch_is_reported_only_when_the_flank_changes(league):
    for seed in range(20):
        t, _ = track("har", "ngc", seed, league)
        for p in t.patterns():
            if p.kind == "switch":
                assert p.scope == "second_half" and p.value != p.numbers["first_half_channel"]


# ---------- PA-9: accuracy over a simulated season ----------

@pytest.fixture(scope="module")
def season_results(league):
    """380 matches (every pairing, many seeds): 14 matches per club is too few to judge 'most matches'."""
    season = simulate_season(league, history=HISTORY_SEASONS)
    profiles = season.profiles()
    clubs = [c.id for c in league.clubs]
    pairs = [(h, a) for h in clubs for a in clubs if h != a]
    found, alarms = {}, {}
    for seed in range(2000, 2380):
        home, away = pairs[seed % len(pairs)]
        t, _ = track(home, away, seed, league, profiles)
        for club_id in (home, away):
            club = league.club(club_id)
            flanks = {p.value for p in t.patterns() if p.kind == "flank" and p.team_id == club_id and p.scope == "match"}
            if club.flank == "balanced":
                alarms.setdefault(club_id, []).append(bool(flanks & {"left", "right"}))
            else:
                found.setdefault(club_id, []).append(club.flank in flanks)
    return league, found, alarms, profiles


def test_season_profiles_reflect_each_clubs_style(season_results):
    league, _, _, profiles = season_results
    for c in league.clubs:
        shares = profiles[c.id]["flank_shares"]
        if c.flank != "balanced":
            assert max(shares, key=shares.get) == c.flank


def test_detector_finds_strong_styles_in_most_matches(season_results):
    league, found, _, _ = season_results
    strong = [h for club_id, hits in found.items() if league.club(club_id).flank_strength >= 0.7 for h in hits]
    assert sum(strong) / len(strong) >= 0.5, (sum(strong), len(strong))


def test_detector_rarely_raises_false_alarms(season_results):
    _, _, alarms, _ = season_results
    all_alarms = [a for v in alarms.values() for a in v]
    assert sum(all_alarms) / len(all_alarms) <= 0.05, (sum(all_alarms), len(all_alarms))


# ---------- known styles from the season, with today's numbers ----------

@pytest.fixture(scope="module")
def profiles(league):
    return simulate_season(league, history=HISTORY_SEASONS).profiles()


def test_season_profiles_hold_every_style_measure(league, profiles):
    assert "_league" in profiles
    for c in league.clubs:
        p = profiles[c.id]
        assert set(p) >= {"flank_shares", "high_regain_share", "long_shot_share", "playmaker", "playmaker_share", "styles"}
        assert league.player(p["playmaker"]).club_id == c.id


def test_distinctive_styles_are_the_configured_ones(league, profiles):
    styles = {c.id: {s["kind"]: s["value"] for s in profiles[c.id]["styles"]} for c in league.clubs}
    for c in league.clubs:
        if c.flank_strength >= 0.5:
            assert styles[c.id].get("flank") == c.flank, (c.id, styles[c.id])
        if c.flank == "balanced":
            assert "flank" not in styles[c.id], (c.id, styles[c.id])
    top_long = max(league.clubs, key=lambda c: c.long_shots)
    assert "long_shots" in styles[top_long.id]
    top_press = max(league.clubs, key=lambda c: c.pressing)
    assert "high_regains" in styles[top_press.id]
    low_press = min(league.clubs, key=lambda c: c.pressing)
    assert "high_regains" not in styles[low_press.id]


def test_known_styles_come_with_todays_numbers(league, profiles):
    t, m = track("har", "sil", 42, league, profiles)
    notes = t.style_notes()
    har = {n.kind: n for n in notes if n.team_id == "har"}
    assert "flank" in har and har["flank"].scope == "season"
    today = t.summary("har")["entries"]
    assert har["flank"].numbers["today_count"] == today["left"] and har["flank"].numbers["today_total"] == sum(today.values())
    assert 0 < har["flank"].numbers["season_share_pct"] <= 100
    sil = {n.kind for n in notes if n.team_id == "sil"}
    assert "long_shots" in sil
