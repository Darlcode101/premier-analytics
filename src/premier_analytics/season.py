"""A simulated season for commentator context (CD-14): table, form and players' season goals.

Every club plays every other home and away, scheduled by the circle method so each club plays once
per matchday. Each fixture is played by the same generator as the live matches, from a fixed seed,
so the season is identical on every start.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .generator import generate_match
from .league import League
from .patterns import BOX_X, FINAL_THIRD_X, binomial_tail, channel_of

SEASON_ALPHA = 0.005  # with a clear margin over the league too; open-play shot samples are small

SEASON_SEED = 2025
HISTORY_SEASONS = 3  # earlier seasons pooled to decide what a club is known for (one 14-match season is too few)


@dataclass(frozen=True)
class Result:
    matchday: int
    home: str
    away: str
    seed: int
    home_goals: int
    away_goals: int


@dataclass
class TableRow:
    club_id: str
    position: int = 0
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0

    @property
    def points(self) -> int:
        return 3 * self.won + self.drawn


@dataclass
class Season:
    results: list[Result]
    goals: Counter = field(default_factory=Counter)
    assists: Counter = field(default_factory=Counter)
    entries: dict = field(default_factory=dict)  # club -> Counter of final-third entries by channel (PA-3)
    passers: dict = field(default_factory=dict)  # club -> Counter of final-third entries by passer
    regains: dict = field(default_factory=dict)  # club -> [won in the attacking third, all ball wins]
    shots: dict = field(default_factory=dict)    # club -> [outside the box, all shots]
    history: list = field(default_factory=list)  # earlier seasons: evidence for "known for", not shown

    def _pooled(self, attr: str, club: str):
        """A style count over this season and its history."""
        parts = [getattr(s, attr).get(club) for s in (self, *self.history)]
        parts = [p for p in parts if p is not None]
        if isinstance(parts[0], Counter):
            return sum(parts, Counter())
        return [sum(p[0] for p in parts), sum(p[1] for p in parts)]

    def profiles(self) -> dict:
        """Each club's style this season, measured from its matches (not read from its settings), plus the
        styles it is known for (PA-3: significant and by a clear margin over this season and the earlier ones in
        `history`, so one short season's luck neither invents nor hides a style). Shares shown are this season's."""
        clubs = sorted(self.entries)

        def league_share(attr: str, pooled: bool) -> float:
            rows = [self._pooled(attr, c) if pooled else getattr(self, attr)[c] for c in clubs]
            return sum(r[0] for r in rows) / sum(r[1] for r in rows)

        league = {"high_regain_share": league_share("regains", False), "long_shot_share": league_share("shots", False)}
        base = {"high_regain_share": league_share("regains", True), "long_shot_share": league_share("shots", True)}
        out: dict = {"_league": league}
        for club in clubs:
            counts = self.entries[club]
            n = sum(counts.values()) or 1
            flank = {c: counts[c] / n for c in ("left", "centre", "right")}
            playmaker, pm_count = self.passers[club].most_common(1)[0]
            reg_k, reg_n = self.regains[club]
            sh_k, sh_n = self.shots[club]
            p = {
                "flank_shares": flank,
                "high_regain_share": reg_k / reg_n,
                "long_shot_share": sh_k / sh_n,
                "playmaker": playmaker,
                "playmaker_share": pm_count / n,
            }
            styles = []
            all_entries = self._pooled("entries", club)
            all_n = sum(all_entries.values()) or 1
            side = max(("left", "right"), key=lambda c: all_entries[c])
            k = all_entries[side]
            if k / all_n >= 0.42 and 3 * binomial_tail(k, all_n, 1 / 3) < SEASON_ALPHA:
                styles.append({"kind": "flank", "value": side, "share": flank[side], "league": 1 / 3})
            reg_k, reg_n = self._pooled("regains", club)
            if reg_k / reg_n >= base["high_regain_share"] + 0.04 and \
                    binomial_tail(reg_k, reg_n, base["high_regain_share"]) < SEASON_ALPHA:
                styles.append({"kind": "high_regains", "value": "attacking", "share": p["high_regain_share"],
                               "league": league["high_regain_share"]})
            sh_k, sh_n = self._pooled("shots", club)
            if sh_k / sh_n >= base["long_shot_share"] + 0.05 and \
                    binomial_tail(sh_k, sh_n, base["long_shot_share"]) < SEASON_ALPHA:
                styles.append({"kind": "long_shots", "value": "outside_box", "share": p["long_shot_share"],
                               "league": league["long_shot_share"]})
            styles.append({"kind": "playmaker", "value": playmaker, "share": p["playmaker_share"], "league": None})
            p["styles"] = styles
            out[club] = p
        return out

    def table(self) -> list[TableRow]:
        rows: dict[str, TableRow] = {}
        for r in self.results:
            for club, mine, theirs in ((r.home, r.home_goals, r.away_goals), (r.away, r.away_goals, r.home_goals)):
                row = rows.setdefault(club, TableRow(club))
                row.played += 1
                row.goals_for += mine
                row.goals_against += theirs
                if mine > theirs:
                    row.won += 1
                elif mine == theirs:
                    row.drawn += 1
                else:
                    row.lost += 1
        table = sorted(rows.values(), key=lambda t: (-t.points, -(t.goals_for - t.goals_against), -t.goals_for, t.club_id))
        for i, row in enumerate(table, 1):
            row.position = i
        return table

    def form(self, club_id: str, n: int = 5) -> list[str]:
        """Last n results, oldest first: W, D or L."""
        out = []
        for r in self.results:
            if club_id in (r.home, r.away):
                mine, theirs = (r.home_goals, r.away_goals) if r.home == club_id else (r.away_goals, r.home_goals)
                out.append("W" if mine > theirs else "D" if mine == theirs else "L")
        return out[-n:]


def schedule(club_ids: list[str]) -> list[list[tuple[str, str]]]:
    """Double round robin: matchdays of (home, away) pairs; the second half reverses the first."""
    clubs = list(club_ids)
    if len(clubs) % 2:
        raise ValueError("an even number of clubs is needed")
    n = len(clubs)
    first_half = []
    rot = clubs[1:]
    for day in range(n - 1):
        ring = [clubs[0]] + rot
        pairs = []
        for i in range(n // 2):
            a, b = ring[i], ring[n - 1 - i]
            # the fixed club alternates by matchday, the rest by position in the ring: 3 or 4 home games each
            home_first = day % 2 == 0 if i == 0 else i % 2 == 1
            pairs.append((a, b) if home_first else (b, a))
        first_half.append(pairs)
        rot = rot[-1:] + rot[:-1]
    return first_half + [[(a, h) for h, a in day] for day in first_half]


def simulate_season(league: League, seed: int = SEASON_SEED, history: int = 0) -> Season:
    """history: how many earlier seasons to simulate as evidence for each club's known styles."""
    season = Season(results=[], history=[simulate_season(league, seed - i) for i in range(1, history + 1)])
    for day, pairs in enumerate(schedule([c.id for c in league.clubs]), 1):
        for home, away in pairs:
            match_seed = seed * 1000 + len(season.results)
            m = generate_match(home, away, match_seed, league)
            hg = ag = 0
            for e in m.events:
                if e.type == "pass" and e.outcome == "complete" and e.x < FINAL_THIRD_X <= e.end_x:
                    season.entries.setdefault(e.team_id, Counter())[channel_of(e.end_y)] += 1
                    season.passers.setdefault(e.team_id, Counter())[e.player_id] += 1
                elif e.type == "interception" or (e.type == "tackle" and e.outcome == "won"):
                    r = season.regains.setdefault(e.team_id, [0, 0])
                    r[0] += e.x >= FINAL_THIRD_X
                    r[1] += 1
                elif e.type == "shot" and e.set_piece is None:  # long-shot habit: open play only
                    sh = season.shots.setdefault(e.team_id, [0, 0])
                    sh[0] += e.x < BOX_X
                    sh[1] += 1
                if e.type == "goal":
                    hg, ag = e.score_home, e.score_away
                    season.goals[e.player_id] += 1
                    if e.assist_id:
                        season.assists[e.assist_id] += 1
            season.results.append(Result(day, home, away, match_seed, hg, ag))
    return season


def club_context(season: Season, league: League, club_id: str) -> dict:
    row = next(r for r in season.table() if r.club_id == club_id)
    squad = league.squad(club_id)
    players = {p.id: {"goals": season.goals[p.id], "assists": season.assists[p.id]} for p in squad}
    scorers = sorted(({"player_id": p.id, "goals": season.goals[p.id]} for p in squad if season.goals[p.id]),
                     key=lambda s: (-s["goals"], s["player_id"]))
    return {
        "position": row.position, "played": row.played, "won": row.won, "drawn": row.drawn, "lost": row.lost,
        "goals_for": row.goals_for, "goals_against": row.goals_against, "points": row.points,
        "form": season.form(club_id), "players": players, "top_scorers": scorers[:3],
    }


def season_summary(season: Season, league: League, home: str, away: str) -> dict:
    """What the desk's hello carries."""
    return {
        "matches": len(season.results),
        "table": [{"club_id": r.club_id, "short_name": league.club(r.club_id).short_name, "position": r.position,
                   "played": r.played, "points": r.points, "goal_difference": r.goals_for - r.goals_against}
                  for r in season.table()],
        "home": club_context(season, league, home),
        "away": club_context(season, league, away),
    }
