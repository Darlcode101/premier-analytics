"""PA-1: clubs have playing styles the generator honours (favoured flank, long-shot tendency)."""
from collections import Counter

import pytest

from premier_analytics.generator import generate_match
from premier_analytics.schema import PITCH_WIDTH

W = PITCH_WIDTH
BOX_X = 105 - 16.5


def channel(y: float) -> str:
    """In a team's own frame (attacking +x), the low-y third is their left."""
    return "left" if y < W / 3 else "centre" if y < 2 * W / 3 else "right"


@pytest.fixture(scope="module")
def club_samples(league):
    """Twelve matches per club, home and away against everyone, the club's own events only."""
    out = {}
    ids = [c.id for c in league.clubs]
    for club in ids:
        entries: Counter = Counter()
        shots = [0, 0]  # outside box, total
        for i, other in enumerate(x for x in ids if x != club):
            for home, away, seed in ((club, other, 500 + i), (other, club, 600 + i)):
                for e in generate_match(home, away, seed, league).events:
                    if e.team_id != club:
                        continue
                    if e.type == "pass" and e.outcome == "complete" and e.x < 70 <= e.end_x:
                        entries[channel(e.end_y)] += 1
                    if e.type == "shot":
                        shots[1] += 1
                        shots[0] += e.x < BOX_X
        out[club] = (entries, shots)
    return out


def share(counter: Counter, key: str) -> float:
    return counter[key] / sum(counter.values())


def test_every_club_has_a_style(league):
    for c in league.clubs:
        assert c.flank in ("left", "right", "balanced")
        assert 0 <= c.flank_strength <= 1 and 0 <= c.long_shots <= 1
    assert sum(c.flank == "balanced" for c in league.clubs) >= 2  # needed to measure false alarms (PA-9)
    assert {c.flank for c in league.clubs} == {"left", "right", "balanced"}


def test_clubs_attack_down_their_favoured_flank(league, club_samples):
    for c in league.clubs:
        entries, _ = club_samples[c.id]
        if c.flank == "balanced":
            assert all(0.25 <= share(entries, ch) <= 0.43 for ch in ("left", "centre", "right")), (c.id, entries)
        else:
            other = "right" if c.flank == "left" else "left"
            assert share(entries, c.flank) >= 0.42 and share(entries, c.flank) > share(entries, other) + 0.12, (c.id, entries)
            assert share(entries, c.flank) <= 0.62, (c.id, entries)  # realistic: strongly one-sided real teams sit near 45-55 %


def test_long_shot_tendency_shows(league, club_samples):
    ranked = sorted(league.clubs, key=lambda c: c.long_shots)
    low, high = ranked[0], ranked[-1]
    low_share = club_samples[low.id][1][0] / club_samples[low.id][1][1]
    high_share = club_samples[high.id][1][0] / club_samples[high.id][1][1]
    assert high_share > low_share + 0.08, (low.id, low_share, high.id, high_share)


@pytest.fixture(scope="module")
def match_samples(league):
    """Per club and match: share of ball wins in the attacking third, outside-box shot share, top entry passer share."""
    from collections import defaultdict
    out = defaultdict(lambda: {"high": [], "outside": [], "hub": [], "hub_player": Counter()})
    ids = [c.id for c in league.clubs]
    pairs = [(h, a) for h in ids for a in ids if h != a]
    for seed in range(4000, 4168):
        home, away = pairs[seed % len(pairs)]
        d = {t: {"reg": [0, 0], "sh": [0, 0], "pas": Counter()} for t in (home, away)}
        for e in generate_match(home, away, seed, league).events:
            t = d.get(e.team_id)
            if t is None:
                continue
            if e.type == "interception" or (e.type == "tackle" and e.outcome == "won"):
                t["reg"][1] += 1
                t["reg"][0] += e.x >= 70
            if e.type == "shot":
                t["sh"][1] += 1
                t["sh"][0] += e.x < BOX_X
            if e.type == "pass" and e.outcome == "complete" and e.x < 70 <= e.end_x:
                t["pas"][e.player_id] += 1
        for team, t in d.items():
            o = out[team]
            o["high"].append(t["reg"][0] / max(t["reg"][1], 1))
            o["outside"].append(t["sh"][0] / max(t["sh"][1], 1))
            if t["pas"]:
                player, k = t["pas"].most_common(1)[0]
                o["hub"].append(k / sum(t["pas"].values()))
                o["hub_player"][player] += 1
    return out


def mean(xs):
    return sum(xs) / len(xs)


def test_pressing_teams_win_the_ball_higher_up(league, match_samples):
    ranked = sorted(league.clubs, key=lambda c: c.pressing)
    low, high = ranked[0], ranked[-1]
    assert mean(match_samples[high.id]["high"]) >= mean(match_samples[low.id]["high"]) + 0.07
    assert 0.25 <= mean(match_samples[high.id]["high"]) <= 0.40  # real high-pressing sides: roughly a third


def test_long_shot_sides_clearly_shoot_from_distance(league, match_samples):
    ranked = sorted(league.clubs, key=lambda c: c.long_shots)
    assert mean(match_samples[ranked[-1].id]["outside"]) >= mean(match_samples[ranked[0].id]["outside"]) + 0.15


def test_each_club_has_a_playmaker(league, match_samples):
    for c in league.clubs:
        s = match_samples[c.id]
        assert mean(s["hub"]) >= 0.25, (c.id, mean(s["hub"]))
        top = s["hub_player"].most_common(1)[0][0]
        assert league.player(top).position in ("CM", "AM", "DM", "W"), (c.id, top)
