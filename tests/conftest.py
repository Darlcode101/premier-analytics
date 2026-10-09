import pytest

from premier_analytics.generator import generate_match
from premier_analytics.league import load_league

SEASON_SEEDS = range(380)


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
def season(league):
    """A synthetic 380-match season: every ordered pairing of clubs in turn, so home and
    away games are balanced. Used for realism tests against real league averages."""
    clubs = [c.id for c in league.clubs]
    pairings = [(h, a) for h in clubs for a in clubs if h != a]
    return [generate_match(*pairings[seed % len(pairings)], seed=seed) for seed in SEASON_SEEDS]


@pytest.fixture(scope="session")
def many_matches(season):
    return season[:200]
