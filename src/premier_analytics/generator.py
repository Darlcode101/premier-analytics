"""Synthetic match generator.

A possession-by-possession simulation: the ball carrier passes, gets pressed, tackled or
fouled, and shoots when in range. Club ratings, player attributes, weather, red cards and a
drifting momentum term shape the probabilities, so matches have storylines (spells of
pressure, comebacks) rather than uniform noise. Same seed, same match, byte for byte.

See schema.py for the coordinate and time conventions.
"""
from __future__ import annotations

import math
import random

from .league import Club, League, Player, load_league
from .schema import PITCH_LENGTH as L
from .schema import PITCH_WIDTH as W
from .schema import Event, Lineup, Match, MatchMeta, Weather

SEC = 1000
MIN = 60 * SEC
GOAL_Y = (W / 2 - 3.66, W / 2 + 3.66)

# Who tends to be on the ball in each third (own, middle, final), by position.
_ZONE_WEIGHTS = {
    "GK": (3.0, 0.02, 0.0),
    "CB": (4.0, 1.2, 0.2),
    "FB": (2.5, 2.2, 1.2),
    "DM": (2.5, 3.0, 0.8),
    "CM": (1.5, 3.5, 1.8),
    "AM": (0.6, 3.0, 3.0),
    "W": (0.4, 2.0, 3.5),
    "ST": (0.2, 1.2, 4.0),
}

_REFEREES = ["Morgan Ashby", "Priya Kendal", "Tomasz Rivet", "Helen Okoro", "Dev Castell", "Iain Muir"]
_WEATHER = [("clear", 0.35), ("cloudy", 0.3), ("light_rain", 0.15), ("heavy_rain", 0.06), ("windy", 0.1), ("fog", 0.04)]


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _zone(x: float) -> int:
    return 0 if x < 35 else 1 if x < 70 else 2


class _Sim:
    def __init__(self, league: League, home: Club, away: Club, seed: int):
        self.lg = league
        self.rng = random.Random(seed)
        self.seed = seed
        self.home, self.away = home, away
        self.clubs = {home.id: home, away.id: away}
        self.match_id = f"{home.id}-{away.id}-{seed}"
        self.events: list[Event] = []
        self.period = 1
        self.clock = 0
        self.elapsed = 0
        self.score = {home.id: 0, away.id: 0}
        self.on_pitch = {c.id: list(c.starting_xi) for c in (home, away)}
        self.bench = {c.id: list(c.bench) for c in (home, away)}
        self.subs_made = {home.id: 0, away.id: 0}
        self.booked: set[str] = set()
        self.momentum = 0.0  # > 0 favours home
        self.next_momentum_tick = MIN
        self.sub_plan = {c.id: self._plan_subs() for c in (home, away)}

        cond = self.rng.choices([w for w, _ in _WEATHER], [p for _, p in _WEATHER])[0]
        temp = round(self.rng.uniform(2, 24) - (4 if cond in ("heavy_rain", "fog") else 0), 1)
        self.weather = Weather(condition=cond, temp_c=temp)
        self.wet = cond in ("light_rain", "heavy_rain")
        self.meta = MatchMeta(
            match_id=self.match_id, seed=seed, home_id=home.id, away_id=away.id,
            venue=home.stadium, referee=self.rng.choice(_REFEREES),
            kickoff_local=self.rng.choice(["12:30", "15:00", "17:30", "20:00"]),
            weather=self.weather,
            lineups={c.id: Lineup(starting=list(c.starting_xi), bench=list(c.bench)) for c in (home, away)},
        )

    # ---------- helpers ----------

    def other(self, team: str) -> str:
        return self.away.id if team == self.home.id else self.home.id

    def player(self, pid: str) -> Player:
        return self.lg.player(pid)

    def strength(self, team: str) -> float:
        """Multiplier from momentum and numbers on the pitch (red cards hurt)."""
        m = self.momentum if team == self.home.id else -self.momentum
        home_adv = 0.04 if team == self.home.id else -0.04
        return math.exp(0.22 * m + home_adv) * (len(self.on_pitch[team]) / 11) ** 1.5

    def pick(self, team: str, x: float, exclude: str | None = None) -> str:
        z = _zone(x)
        cands = [p for p in self.on_pitch[team] if p != exclude]
        weights = [_ZONE_WEIGHTS[self.player(p).position][z] + 0.01 for p in cands]
        return self.rng.choices(cands, weights)[0]

    def emit(self, etype: str, **fields) -> Event:
        seq = len(self.events)
        for k in ("x", "end_x"):
            if fields.get(k) is not None:
                fields[k] = round(_clamp(fields[k], 0.0, L), 1)
        for k in ("y", "end_y"):
            if fields.get(k) is not None:
                fields[k] = round(_clamp(fields[k], 0.0, W), 1)
        e = Event(
            id=f"{self.match_id}-{seq:05d}", match_id=self.match_id, seq=seq, period=self.period,
            clock_ms=self.clock, elapsed_ms=self.elapsed, type=etype, **fields,
        )
        self.events.append(e)
        return e

    def tick(self, ms: float) -> None:
        ms = int(ms)
        self.clock += ms
        self.elapsed += ms
        while self.elapsed >= self.next_momentum_tick:
            # Mean-reverting random walk, with occasional sudden swings: the "storylines".
            self.momentum += -0.08 * self.momentum + self.rng.gauss(0, 0.12)
            if self.rng.random() < 0.012:
                self.momentum = self.rng.choice([-1, 1]) * self.rng.uniform(0.6, 0.9)
            self.momentum = _clamp(self.momentum, -1.0, 1.0)
            self.next_momentum_tick += MIN

    def _plan_subs(self) -> list[int]:
        n = self.rng.choices([2, 3, 4, 5], [0.1, 0.25, 0.35, 0.3])[0]
        return sorted(self.rng.randint(55, 88) * MIN for _ in range(n))

    # ---------- stoppages ----------

    def do_subs(self, team: str) -> None:
        plan = self.sub_plan[team]
        while plan and plan[0] <= self.clock and self.subs_made[team] < 5:
            plan.pop(0)
            outs = [p for p in self.on_pitch[team] if self.player(p).position != "GK"]
            ins = [p for p in self.bench[team] if self.player(p).position != "GK"]
            if not outs or not ins:
                return
            out = self.rng.choice(outs)
            pos = self.player(out).position
            same = [p for p in ins if self.player(p).position == pos]
            inn = self.rng.choice(same or ins)
            self.on_pitch[team].remove(out)
            self.on_pitch[team].append(inn)
            self.bench[team].remove(inn)
            self.subs_made[team] += 1
            self.emit("substitution", team_id=team, player_out_id=out, player_in_id=inn)
            self.tick(self.rng.uniform(15, 35) * SEC)

    def foul(self, fouler_team: str, fouler: str, victim: str, x: float, y: float) -> bool:
        """Emit a foul and maybe a card. x, y are from the fouler's perspective.
        Returns True if the fouler was sent off."""
        self.emit("foul", team_id=fouler_team, player_id=fouler, x=x, y=y, fouled_player_id=victim)
        self.tick(self.rng.uniform(20, 45) * SEC)
        disc = self.clubs[fouler_team].discipline
        r = self.rng.random()
        if r < 0.003:
            card = "red"
        elif r < 0.003 + 0.24 * (1.25 - disc) * (0.5 if fouler in self.booked else 1.0):
            card = "second_yellow" if fouler in self.booked else "yellow"
        else:
            return False
        self.emit("card", team_id=fouler_team, player_id=fouler, card=card)
        self.tick(self.rng.uniform(20, 40) * SEC)
        if card == "yellow":
            self.booked.add(fouler)
            return False
        self.on_pitch[fouler_team].remove(fouler)
        return True

    def change(self, team: str, cause: str, x: float, y: float) -> None:
        self.emit("possession_change", team_id=team, cause=cause, x=x, y=y)

    # ---------- play ----------

    def kickoff(self, team: str) -> tuple[str, float, float, str]:
        taker = self.pick(team, 52.5)
        self.emit("kickoff", team_id=team, player_id=taker)
        return team, 52.5, W / 2, taker

    def play_period(self, end_clock: int, first_team: str) -> None:
        self.emit("period_start")
        state = self.kickoff(first_team)
        while self.clock < end_clock:
            state = self.possession(*state, end_clock=end_clock)
        self.emit("period_end", score_home=self.score[self.home.id], score_away=self.score[self.away.id])

    def possession(self, team: str, x: float, y: float, carrier: str, end_clock: int):
        """Play until the ball changes hands, a goal, or the period ends.
        Returns the next (team, x, y, carrier)."""
        rng = self.rng
        opp = self.other(team)
        club, opp_club = self.clubs[team], self.clubs[opp]
        last_pass: Event | None = None
        while self.clock < end_clock:
            s = self.strength(team) / self.strength(opp)
            c = self.player(carrier)

            # Pressing: more in the opponent's attacking zones and by pressing teams.
            pressed = rng.random() < (0.12 + 0.35 * opp_club.pressing) * (0.6 + 0.5 * x / L)
            if pressed:
                presser = self.pick(opp, L - x)
                self.emit("pressure", team_id=opp, player_id=presser, x=L - x, y=W - y)

            # Defensive duel: tackle, or a foul.
            duel = rng.random() < 0.085 * (1.4 if pressed else 1.0)
            if duel:
                defender = self.pick(opp, L - x)
                dplayer = self.player(defender)
                if rng.random() < 0.16 * (1.3 - opp_club.discipline) / 0.7:
                    sent_off = self.foul(opp, defender, carrier, L - x, W - y)
                    if x > 70:
                        x = min(x, 88)  # free kick: play restarts a little back from the box
                    if sent_off and carrier not in self.on_pitch[team]:
                        carrier = self.pick(team, x)
                    last_pass = None
                    continue
                p_win = _clamp(0.42 + 0.35 * (dplayer.tackling - c.pace * 0.6) + 0.08 * (opp_club.defence - club.attack), 0.15, 0.8)
                won = rng.random() < p_win / s ** 0.5
                self.emit("tackle", team_id=opp, player_id=defender, x=L - x, y=W - y, outcome="won" if won else "lost")
                self.tick(rng.uniform(0.6, 1.6) * SEC)
                if won:
                    self.change(opp, "tackle", L - x, W - y)
                    return opp, L - x, W - y, defender
                last_pass = None

            # Shoot?
            if x >= 76:
                centrality = 1 - min(abs(y - W / 2) / (W / 2), 1)
                depth = (x - 76) / (L - 76)
                p_shot = (0.011 + 0.17 * depth ** 1.4) * (0.4 + 1.2 * centrality) * (0.2 + 1.4 * club.attack) * s ** 0.5
                if rng.random() < p_shot:
                    return self.shoot(team, x, y, carrier, last_pass, pressed)

            # Occasional offensive foul by the carrier.
            if rng.random() < 0.006 * (1.3 - club.discipline) / 0.7:
                victim = self.pick(opp, L - x)
                self.foul(team, carrier, victim, x, y)
                self.change(opp, "foul", L - x, W - y)
                return opp, L - x, W - y, self.pick(opp, L - x)

            # Pass.
            directness = 1 - club.possession
            dx = rng.gauss(3.0 + 9.0 * directness - (4 if x > 85 else 0), 10.0)
            if x < 20 and c.position == "GK":
                dx = abs(dx) + rng.uniform(10, 45 * directness + 10)
            dy = rng.gauss(0, 11.0)
            # Wide players cross towards the box.
            if x > 80 and abs(y - W / 2) > 18 and rng.random() < 0.35:
                dx, dy = rng.uniform(L - 2 - x - 12, L - 2 - x), (W / 2 - y) * rng.uniform(0.6, 1.0)
            ex, ey = x + dx, y + dy
            length = math.hypot(dx, dy)
            progress = max(0.0, ex - x) / 30
            p_ok = (
                1.08
                - 0.0045 * max(0.0, length - 12)
                - 0.10 * progress * (1.5 - club.attack)
                - (0.08 if pressed else 0.0)
                - (0.10 if ex > 88 else 0.0)
                - (0.025 if self.wet else 0.0)
                + 0.10 * (c.passing - 0.65)
                + 0.14 * (club.possession - 0.55)
                - 0.06 * (opp_club.defence - 0.65)
            ) * s ** 0.25
            out = ex < 0 or ex > L or ey < 0 or ey > W
            self.tick((0.9 + length / 15 + rng.uniform(0, 1.0)) * SEC)
            if not out and rng.random() < _clamp(p_ok, 0.25, 0.97):
                receiver = self.pick(team, ex, exclude=carrier)
                last_pass = self.emit(
                    "pass", team_id=team, player_id=carrier, x=x, y=y, end_x=ex, end_y=ey,
                    outcome="complete", receiver_id=receiver, under_pressure=pressed,
                )
                x, y, carrier = _clamp(ex, 0.5, L - 0.5), _clamp(ey, 0.5, W - 0.5), receiver
                continue

            ex, ey = _clamp(ex, 0, L), _clamp(ey, 0, W)
            if out or rng.random() < 0.12:
                self.emit("pass", team_id=team, player_id=carrier, x=x, y=y, end_x=ex, end_y=ey,
                          outcome="out", under_pressure=pressed)
                self.change(opp, "out_of_play", L - ex, W - ey)
                self.tick(rng.uniform(6, 18) * SEC)
                self.do_subs(team)
                self.do_subs(opp)
                return opp, L - ex, W - ey, self.pick(opp, L - ex)
            self.emit("pass", team_id=team, player_id=carrier, x=x, y=y, end_x=ex, end_y=ey,
                      outcome="incomplete", under_pressure=pressed)
            if rng.random() < 0.55:
                interceptor = self.pick(opp, L - ex)
                self.emit("interception", team_id=opp, player_id=interceptor, x=L - ex, y=W - ey)
                self.change(opp, "interception", L - ex, W - ey)
                return opp, L - ex, W - ey, interceptor
            self.change(opp, "incomplete_pass", L - ex, W - ey)
            return opp, L - ex, W - ey, self.pick(opp, L - ex)
        return team, x, y, carrier

    def shoot(self, team, x, y, shooter, last_pass, pressed):
        rng = self.rng
        opp = self.other(team)
        p = self.player(shooter)
        dist = math.hypot(L - x, W / 2 - y)
        angle = math.atan2(7.32 * (L - x), (L - x) ** 2 + (W / 2 - y) ** 2 - 3.66 ** 2)
        if angle < 0:
            angle += math.pi
        header = last_pass is not None and abs(last_pass.y - W / 2) > 18 and dist < 14 and rng.random() < 0.55
        body = "head" if header else rng.choices(["right_foot", "left_foot"], [0.7, 0.3])[0]

        base = 1 / (1 + math.exp(-(-1.0 + 1.6 * angle - 0.11 * dist)))
        if header:
            base *= 0.55
        s = self.strength(team) / self.strength(opp)
        p_goal = _clamp(
            base * 0.76 * (0.90 + 0.75 * (p.shooting - 0.6)) * (1.15 - 0.6 * (self.clubs[opp].defence - 0.5))
            * (0.45 + 1.0 * self.clubs[team].attack)
            * (0.85 if pressed else 1.0) * s ** 0.3,
            0.005, 0.85,
        )
        speed = rng.gauss(58, 7) if header else rng.gauss(78 + 25 * p.shooting - 0.4 * dist, 11)
        speed = round(_clamp(speed, 35, 135), 1)

        r = rng.random()
        if r < p_goal:
            outcome = "goal"
        else:
            r = rng.random()
            outcome = "blocked" if r < 0.27 else "off_target" if r < 0.68 else "woodwork" if r < 0.71 else "saved"

        if outcome in ("goal", "saved"):
            ex, ey = L, rng.uniform(GOAL_Y[0] + 0.2, GOAL_Y[1] - 0.2)
        elif outcome == "woodwork":
            ex, ey = L, rng.choice([GOAL_Y[0], GOAL_Y[1]])
        elif outcome == "off_target":
            ex, ey = L, _clamp(W / 2 + rng.choice([-1, 1]) * rng.uniform(4.5, 14), 0, W)
        else:
            ex, ey = min(L, x + rng.uniform(1, 4)), _clamp(y + rng.uniform(-2, 2), 0, W)

        shot = self.emit(
            "shot", team_id=team, player_id=shooter, x=x, y=y, end_x=ex, end_y=ey, outcome=outcome,
            shot_speed_kmh=speed, body_part=body, under_pressure=pressed,
        )
        self.tick(rng.uniform(0.8, 1.5) * SEC)

        if outcome == "goal":
            self.score[team] += 1
            assist = last_pass.player_id if last_pass is not None and last_pass.receiver_id == shooter else None
            self.emit(
                "goal", team_id=team, player_id=shooter, assist_id=assist,
                score_home=self.score[self.home.id], score_away=self.score[self.away.id],
                related_event_id=shot.id,
            )
            # The conceding side rallies.
            self.momentum += (-0.25 if team == self.home.id else 0.25)
            self.momentum = _clamp(self.momentum, -1, 1)
            self.tick(rng.uniform(55, 95) * SEC)
            self.do_subs(team)
            self.do_subs(opp)
            return self.kickoff(opp)

        if outcome == "saved":
            if rng.random() < 0.3:  # parried for a corner: attackers keep the ball
                self.tick(rng.uniform(20, 35) * SEC)
                cy = rng.choice([0.5, W - 0.5])
                return team, L - 0.5, cy, self.pick(team, 80)
            gk = next((q for q in self.on_pitch[opp] if self.player(q).position == "GK"), None) or self.pick(opp, 5)
            self.change(opp, "save", 6.0, W / 2)
            self.tick(rng.uniform(4, 12) * SEC)
            return opp, 6.0, W / 2, gk
        if outcome == "off_target":
            self.change(opp, "goal_kick", 5.5, W / 2 + rng.uniform(-9, 9))
            self.tick(rng.uniform(15, 30) * SEC)
            self.do_subs(team)
            self.do_subs(opp)
            gk = next((q for q in self.on_pitch[opp] if self.player(q).position == "GK"), None) or self.pick(opp, 5)
            return opp, 5.5, W / 2, gk
        # blocked or woodwork: a scramble for the loose ball
        if rng.random() < 0.45:
            return team, max(60.0, x - rng.uniform(3, 12)), _clamp(y + rng.uniform(-8, 8), 1, W - 1), self.pick(team, x)
        lx, ly = L - x + rng.uniform(0, 6), _clamp(W - y + rng.uniform(-6, 6), 1, W - 1)
        self.change(opp, "blocked_shot" if outcome == "blocked" else "rebound", lx, ly)
        return opp, lx, ly, self.pick(opp, lx)

    def run(self) -> Match:
        first = self.rng.choice([self.home.id, self.away.id])
        self.play_period(45 * MIN + self.rng.randint(1, 5) * MIN, first)
        self.period = 2
        self.clock = 45 * MIN
        self.play_period(90 * MIN + self.rng.randint(3, 7) * MIN, self.other(first))
        return Match(meta=self.meta, events=self.events)


def generate_match(home_id: str, away_id: str, seed: int, league: League | None = None) -> Match:
    lg = league or load_league()
    if home_id == away_id:
        raise ValueError("a club cannot play itself")
    return _Sim(lg, lg.club(home_id), lg.club(away_id), seed).run()
