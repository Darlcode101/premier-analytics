"""Fictional league: D-7 (clubs + squads) and RC-2 (no real clubs or players)."""
from premier_analytics.league import POSITIONS

# Real top-flight / well-known English clubs and star players. Substring match, case-insensitive.
REAL_CLUB_TOKENS = [
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "burnley", "chelsea",
    "crystal palace", "everton", "fulham", "ipswich", "leeds", "leicester", "liverpool",
    "luton", "manchester", "newcastle", "nottingham", "southampton", "sunderland",
    "tottenham", "spurs", "west ham", "wolverhampton", "wolves", "sheffield", "watford",
    "norwich", "premier league",
]
REAL_PLAYER_SURNAMES = {
    "haaland", "salah", "saka", "kane", "rashford", "de bruyne", "foden", "rice", "palmer",
    "odegaard", "fernandes", "van dijk", "alisson", "ederson", "son", "isak", "watkins",
    "gordon", "bellingham", "trent", "alexander-arnold", "rodri", "martinelli", "havertz",
}


def test_at_least_six_clubs(league):
    assert len(league.clubs) >= 6


def test_club_ids_unique(league):
    ids = [c.id for c in league.clubs]
    assert len(ids) == len(set(ids))


def test_squads_complete(league):
    for club in league.clubs:
        squad = league.squad(club.id)
        assert len(squad) >= 18, club.id
        assert sum(p.position == "GK" for p in squad) >= 2, club.id
        assert len(club.starting_xi) == 11
        assert len(club.bench) >= 7
        assert set(club.starting_xi).isdisjoint(club.bench)
        starters = [league.player(pid) for pid in club.starting_xi]
        assert sum(p.position == "GK" for p in starters) == 1, club.id


def test_shirt_numbers_unique_per_club(league):
    for club in league.clubs:
        numbers = [p.number for p in league.squad(club.id)]
        assert len(numbers) == len(set(numbers)), club.id


def test_player_ids_unique_across_league(league):
    ids = [p.id for c in league.clubs for p in league.squad(c.id)]
    assert len(ids) == len(set(ids))


def test_player_attributes_bounded(league):
    for club in league.clubs:
        for p in league.squad(club.id):
            assert p.position in POSITIONS
            for v in (p.passing, p.shooting, p.tackling, p.pace):
                assert 0.0 <= v <= 1.0


def test_league_is_deterministic():
    from premier_analytics.league import load_league

    a, b = load_league(), load_league()
    assert [p.name for c in a.clubs for p in a.squad(c.id)] == [
        p.name for c in b.clubs for p in b.squad(c.id)
    ]


def test_no_real_club_names(league):
    for club in league.clubs:
        text = " ".join([club.name, club.short_name, club.city, club.stadium]).lower()
        for token in REAL_CLUB_TOKENS:
            assert token not in text, (club.name, token)


def test_no_real_player_names(league):
    for club in league.clubs:
        for p in league.squad(club.id):
            surname = p.name.split(" ", 1)[1].lower()
            assert surname not in REAL_PLAYER_SURNAMES, p.name
