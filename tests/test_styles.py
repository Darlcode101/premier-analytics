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
