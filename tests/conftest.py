import pytest

from premier_analytics.generator import generate_match
from premier_analytics.league import load_league

REALISM_SEEDS = range(200)


@pytest.fixture(scope="session")
def league():
    return load_league()


@pytest.fixture(scope="session")
def fixture_pair(league):
    """A fixed home/away pairing used by single-match tests."""
    return league.clubs[0].id, league.clubs[1].id


@pytest.fixture(scope="session")
def match(fixture_pair):
    home, away = fixture_pair
    return generate_match(home, away, seed=42)


@pytest.fixture(scope="session")
def many_matches(league):
    """200 matches across rotating pairings, for statistical realism tests."""
    clubs = [c.id for c in league.clubs]
    out = []
    for seed in REALISM_SEEDS:
        home = clubs[seed % len(clubs)]
        away = clubs[(seed + 1 + seed // len(clubs)) % len(clubs)]
        if away == home:
            away = clubs[(seed + 2) % len(clubs)]
        out.append(generate_match(home, away, seed=seed))
    return out
