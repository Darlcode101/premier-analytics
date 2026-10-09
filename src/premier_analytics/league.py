"""A fictional league: clubs, squads and player attributes, built deterministically.

Every name here is invented. Nothing refers to a real club, stadium or player (rule RC-2).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import cache

POSITIONS = ("GK", "FB", "CB", "DM", "CM", "AM", "W", "ST")

# 4-3-3: shirt numbers follow the traditional layout.
STARTING_SHAPE = [
    (1, "GK"), (2, "FB"), (5, "CB"), (6, "CB"), (3, "FB"), (4, "DM"),
    (8, "CM"), (10, "CM"), (7, "W"), (9, "ST"), (11, "W"),
]
BENCH_SHAPE = [(13, "GK"), (15, "CB"), (12, "FB"), (14, "CM"), (17, "AM"), (19, "W"), (18, "ST")]

# How strongly each position leans on each skill (passing, shooting, tackling, pace).
_POSITION_PROFILE = {
    "GK": (0.45, 0.05, 0.30, 0.30),
    "FB": (0.62, 0.30, 0.68, 0.78),
    "CB": (0.60, 0.25, 0.80, 0.55),
    "DM": (0.75, 0.40, 0.75, 0.55),
    "CM": (0.80, 0.55, 0.60, 0.62),
    "AM": (0.82, 0.70, 0.40, 0.68),
    "W": (0.70, 0.68, 0.35, 0.85),
    "ST": (0.62, 0.85, 0.30, 0.75),
}

_FIRST_NAMES = [
    "Aaron", "Abel", "Adrian", "Alfie", "Amadou", "Anders", "Arlo", "Bastian", "Bram", "Caleb",
    "Callum", "Cian", "Corin", "Dario", "Dawit", "Declan", "Elias", "Emeka", "Enzo", "Ewan",
    "Fabian", "Felix", "Finlay", "Gael", "Hamza", "Hugo", "Idris", "Ilan", "Ivo", "Jaden",
    "Jonas", "Kai", "Kenji", "Kofi", "Lars", "Leandro", "Levi", "Lorcan", "Luca", "Malik",
    "Marek", "Mateo", "Milo", "Nils", "Noel", "Obi", "Oren", "Oskar", "Pablo", "Quinn",
    "Rafael", "Reuben", "Rhys", "Rory", "Sami", "Santi", "Silas", "Soren", "Tariq", "Teo",
    "Theo", "Tobias", "Umar", "Viktor", "Wilf", "Yannick", "Yusuf", "Zane", "Ezra", "Joel",
]
_SURNAMES = [
    "Abernathy", "Achterberg", "Adeyemi-Cole", "Albrecht", "Ashdown", "Balogun-Reid", "Barraclough",
    "Beaumont", "Blackwood", "Brannigan", "Castellano", "Cavendish", "Delacroix", "Drummond",
    "Eastwick", "Ellery", "Faulkner", "Fenwick", "Gallardo", "Garside", "Halloran", "Hartigan",
    "Holmgren", "Ingleby", "Ivesdale", "Jarrow", "Kavanagh", "Kettering", "Lindqvist", "Lockhart",
    "Marchetti", "Merriweather", "Montague", "Nakamura-Ross", "Northcott", "Okonkwo-Hale", "Oyelaran",
    "Pemberton", "Penhaligon", "Quarrie", "Radcliffe", "Ravenscroft", "Rinaldi", "Saltmarsh",
    "Sandoval", "Sherwood", "Stanhope", "Thackeray", "Thornbury", "Underhill", "Vasquez-Doyle",
    "Varga", "Vinter", "Wakefield-Ames", "Whitlock", "Winterbourne", "Yardley", "Zielinski",
    "Asante", "Bergstrom", "Coldwell", "Dunmore", "Esposito", "Fairhurst", "Greaves", "Hollins",
    "Ishikawa", "Jessop", "Kilbride", "Larkspur", "Maddox", "Novak", "Ormsby", "Prendergast",
    "Quintero", "Rookwood", "Stavros", "Tennant", "Uzoma", "Valcourt", "Westerling", "Yewdall",
    "Aldous", "Brightwell", "Corrigan", "Dobrev", "Eldridge", "Fontaine", "Gilchrist", "Hensley",
    "Ilves", "Jovanovic", "Kerrigan", "Lowther", "Moncrieff", "Nightingale", "Oakes", "Pellow",
    "Rasmussen", "Strand", "Tolliver", "Ulrich", "Vance", "Wolstenholme", "Ashworth", "Brooksby",
    "Calloway", "Devereux", "Ekwueme", "Fitzwalter", "Grimaldi", "Haverford", "Inchbald", "Jansen",
    "Kowalczyk", "Lindahl", "Mbanefo-Shaw", "Nordin", "Okafor-Price", "Pryce", "Rowntree", "Sutcliffe",
    "Treloar", "Upton", "Vermeulen", "Whitcombe", "Yorath", "Zubiri", "Arbuthnot", "Bellweather",
    "Crossley", "Danvers", "Everard", "Fairclough", "Gowan", "Hesketh", "Ivanov", "Jakeman",
    "Kirkland", "Llewellyn", "Mayhew", "Nunez-Ward", "Ottaway", "Pickering", "Rourke", "Sefton",
    "Tremayne", "Vale", "Wetherby", "Yelland",
]


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    club_id: str
    number: int
    position: str
    passing: float
    shooting: float
    tackling: float
    pace: float


@dataclass(frozen=True)
class Club:
    id: str
    name: str
    short_name: str
    city: str
    stadium: str
    colors: tuple[str, str]
    attack: float      # 0-1: chance creation and finishing
    defence: float     # 0-1: stopping chances, winning duels
    possession: float  # 0-1: preference for keeping the ball with short passing
    pressing: float    # 0-1: how often they press the ball carrier
    discipline: float  # 0-1: higher = fewer fouls and cards
    starting_xi: tuple[str, ...] = field(default=())
    bench: tuple[str, ...] = field(default=())


_CLUBS = [
    # id, name, short, city, stadium, colours, attack, defence, possession, pressing, discipline
    ("har", "Harbourside Athletic", "Harbourside", "Harbourside", "The Quayside", ("#0B3D91", "#F2C14E"), 0.80, 0.76, 0.70, 0.70, 0.60),
    ("ngc", "Northgate City", "Northgate", "Northgate", "Northgate Arena", ("#7FB7E8", "#FFFFFF"), 0.86, 0.72, 0.78, 0.76, 0.65),
    ("kin", "Kingsmere Rovers", "Kingsmere", "Kingsmere", "Mere Park", ("#B3001B", "#FFFFFF"), 0.72, 0.70, 0.60, 0.55, 0.55),
    ("sil", "Silverlake FC", "Silverlake", "Silverlake", "The Silverlake Bowl", ("#8A8D91", "#1C1C1C"), 0.68, 0.62, 0.56, 0.66, 0.50),
    ("sto", "Stormfield Wanderers", "Stormfield", "Stormfield", "The Gale Ground", ("#3A6B35", "#E3B23C"), 0.64, 0.60, 0.48, 0.80, 0.40),
    ("oak", "Oakhaven United", "Oakhaven", "Oakhaven", "Acorn Lane", ("#5C3317", "#F5E6C8"), 0.58, 0.74, 0.44, 0.50, 0.62),
    ("iro", "Ironmoor Town", "Ironmoor", "Ironmoor", "Forge Road", ("#2F2F2F", "#D35400"), 0.54, 0.64, 0.40, 0.60, 0.45),
    ("elm", "Elmstead Rangers", "Elmstead", "Elmstead", "The Elms", ("#1E5631", "#A4DE02"), 0.50, 0.56, 0.50, 0.45, 0.58),
]


class League:
    def __init__(self, clubs: list[Club], players: list[Player]):
        self.clubs = clubs
        self._clubs = {c.id: c for c in clubs}
        self._players = {p.id: p for p in players}
        self._squads: dict[str, list[Player]] = {c.id: [] for c in clubs}
        for p in players:
            self._squads[p.club_id].append(p)

    def club(self, club_id: str) -> Club:
        try:
            return self._clubs[club_id]
        except KeyError:
            raise ValueError(f"unknown club {club_id!r}") from None

    def squad(self, club_id: str) -> list[Player]:
        return list(self._squads[club_id])

    def player(self, player_id: str) -> Player:
        return self._players[player_id]


def _attr(rng: random.Random, base: float, quality: float) -> float:
    value = base * (0.75 + 0.35 * quality) + rng.gauss(0, 0.06)
    return round(min(1.0, max(0.05, value)), 3)


@cache
def load_league() -> League:
    rng = random.Random("premier-analytics-league-v1")
    first, last = _FIRST_NAMES[:], _SURNAMES[:]
    rng.shuffle(first)
    rng.shuffle(last)
    used_names: set[str] = set()

    clubs: list[Club] = []
    players: list[Player] = []
    for i, (cid, name, short, city, stadium, colours, att, dfn, poss, press, disc) in enumerate(_CLUBS):
        quality = (att + dfn) / 2
        xi, bench = [], []
        for slot, (number, position) in enumerate(STARTING_SHAPE + BENCH_SHAPE):
            # Walk the name lists so every player in the league gets a unique name.
            k = i * 18 + slot
            pname = f"{first[k % len(first)]} {last[k % len(last)]}"
            while pname in used_names:
                k += 7
                pname = f"{first[k % len(first)]} {last[(k * 3) % len(last)]}"
            used_names.add(pname)
            starter = slot < len(STARTING_SHAPE)
            q = quality if starter else quality - 0.08
            pas, sho, tac, pac = _POSITION_PROFILE[position]
            pid = f"{cid}-{number:02d}"
            players.append(Player(
                id=pid, name=pname, club_id=cid, number=number, position=position,
                passing=_attr(rng, pas, q), shooting=_attr(rng, sho, q),
                tackling=_attr(rng, tac, q), pace=_attr(rng, pac, q),
            ))
            (xi if starter else bench).append(pid)
        clubs.append(Club(
            id=cid, name=name, short_name=short, city=city, stadium=stadium, colors=colours,
            attack=att, defence=dfn, possession=poss, pressing=press, discipline=disc,
            starting_xi=tuple(xi), bench=tuple(bench),
        ))
    return League(clubs, players)
