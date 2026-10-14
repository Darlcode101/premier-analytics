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

from .engine import PENALTY_XG
from .engine import xg as expected_goals
from .league import Club, League, Player, load_league
from .schema import PITCH_LENGTH as L
from .schema import PITCH_WIDTH as W
from .schema import Event, Lineup, Match, MatchMeta, Weather

SEC = 1000
MIN = 60 * SEC
GOAL_Y = (W / 2 - 3.66, W / 2 + 3.66)
BOX_X = 105.0 - 16.5  # edge of the penalty area
SHOOTING_RANGE_X = 80.0  # 25 m out: speculative shots from further are rare
FINISHING = 0.97         # global finishing multiplier on xG (re-tuned with set pieces, D-10)
# D-10 set pieces, calibrated to 2024/25 (tests/test_set_pieces.py)
BOX_HALF_WIDTH = 20.16
BOX_FOUL = 0.13          # foul rate inside the box relative to elsewhere (a foul there is a penalty)
# Cards (F-6b). Booking reasons follow 2023/24 reporting (docs/REALISM.md): about 14 % dissent, 8 % time-wasting,
# a few % handball, the rest fouls; total yellows per team stay at the calibrated 2.04.
FOUL_CARD = 0.9          # share of the old foul-booking rate kept for fouls; off-ball cautions make up the rest
DISSENT_P = 0.027        # after a foul is given against them, someone in that side protests too much
TIME_WASTING_P = 0.05    # a side ahead in the second half dawdles over a free kick or a substitution
OFFENSIVE_P = 0.03       # share of dissent that is offensive language (a straight red)
CORNER_FIND = 0.38       # corner delivery reaches a team-mate
CORNER_SHOT = 0.6       # …who gets a shot away straight from it
CORNER_FROM_SAVE, CORNER_FROM_BLOCK, CORNER_FROM_CLEARANCE = 0.3, 0.35, 0.3

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
        # Style (PA-1): each club's playmaker, its best-passing central midfielder, sees more of the ball in midfield.
        self.playmaker = {
            c.id: max((p for p in c.starting_xi if league.player(p).position in ("CM", "AM")),
                      key=lambda p: league.player(p).passing)
            for c in (home, away)
        }
        self.bench = {c.id: list(c.bench) for c in (home, away)}
        self.subs_made = {home.id: 0, away.id: 0}
        self.came_on: set[str] = set()  # substitutes stay on
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
        home_adv = 0.0025 if team == self.home.id else -0.0025  # tuned over four seasons with styles and set pieces (D-10)
        return math.exp(0.22 * m + home_adv) * (len(self.on_pitch[team]) / 11) ** 1.5

    def pick(self, team: str, x: float, exclude: str | None = None, receiving: bool = False) -> str:
        pm = self.playmaker.get(team)
        if receiving and 35 < x < 72 and pm in self.on_pitch[team] and pm != exclude and self.rng.random() < 0.32:
            return pm
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
            outs = [p for p in self.on_pitch[team] if self.player(p).position != "GK" and p not in self.came_on]
            ins = [p for p in self.bench[team] if self.player(p).position != "GK"]
            if not outs or not ins:
                return
            out = self.rng.choice(outs)
            self.maybe_time_wasting(team, out)  # a slow walk off
            pos = self.player(out).position
            same = [p for p in ins if self.player(p).position == pos]
            inn = self.rng.choice(same or ins)
            self.on_pitch[team].remove(out)
            self.on_pitch[team].append(inn)
            self.bench[team].remove(inn)
            self.came_on.add(inn)
            self.subs_made[team] += 1
            self.emit("substitution", team_id=team, player_out_id=out, player_in_id=inn)
            self.tick(self.rng.uniform(15, 35) * SEC)

    def foul(self, fouler_team: str, fouler: str, victim: str, x: float, y: float, attacking: bool = False) -> bool:
        """Emit a foul and maybe a card, plus any protest or time-wasting it leads to. x, y are from the
        fouler's perspective; attacking: the ball carrier committed it. Returns True if the fouler was sent off."""
        rng = self.rng
        self.emit("foul", team_id=fouler_team, player_id=fouler, x=x, y=y, fouled_player_id=victim)
        self.tick(rng.uniform(20, 45) * SEC)
        disc = self.clubs[fouler_team].discipline
        r = rng.random()
        if r < 0.0012:
            reason = "denied_goal_chance" if x < 30 else rng.choices(["serious_foul_play", "violent_conduct"], [0.8, 0.2])[0]
            self.caution(fouler_team, fouler, reason, victim=victim, red=True)
        elif r < 0.0012 + FOUL_CARD * 0.27 * (1.25 - disc) * (0.2 if fouler in self.booked else 1.0):
            if attacking:
                weights = {"late_tackle": 0.35, "holding": 0.55, "handball": 0.1}
            elif x >= L / 2:  # stopping a break before it gets going
                weights = {"late_tackle": 0.38, "tactical_foul": 0.45, "holding": 0.13, "handball": 0.04}
            else:
                weights = {"late_tackle": 0.62, "tactical_foul": 0.15, "holding": 0.19, "handball": 0.04}
            reason = rng.choices(list(weights), list(weights.values()))[0]
            self.caution(fouler_team, fouler, reason, victim=victim)
        # Off the ball: protests from the side penalised, and a side ahead in the second half taking its time.
        if rng.random() < DISSENT_P:
            outfield = [p for p in self.on_pitch[fouler_team] if self.player(p).position != "GK"]
            if outfield:
                protester = rng.choice(outfield)
                if rng.random() < OFFENSIVE_P:
                    self.caution(fouler_team, protester, "offensive_language", red=True)
                else:
                    self.caution(fouler_team, protester, "dissent")
        victim_team = self.other(fouler_team)
        if victim in self.on_pitch[victim_team]:
            self.maybe_time_wasting(victim_team, victim)
        return fouler not in self.on_pitch[fouler_team]

    def maybe_time_wasting(self, team: str, player: str) -> None:
        other = self.other(team)
        if (self.period == 2 and self.score[team] > self.score[other] and player not in self.booked
                and self.rng.random() < TIME_WASTING_P):
            self.caution(team, player, "time_wasting")

    def caution(self, team: str, player: str, reason: str, victim: str | None = None, red: bool = False) -> bool:
        """Show a card. Returns True if the player is sent off."""
        card = "red" if red else "second_yellow" if player in self.booked else "yellow"
        self.emit("card", team_id=team, player_id=player, card=card, card_reason=reason, fouled_player_id=victim)
        self.tick(self.rng.uniform(20, 40) * SEC)
        if card == "yellow":
            self.booked.add(player)
            return False
        self.on_pitch[team].remove(player)
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
            # Style (PA-1): high-pressing sides also harass the ball deep in its own half.
            high_press = max(0.0, opp_club.pressing - 0.55) if x < 35 else 0.0
            pressed = rng.random() < (0.12 + 0.35 * opp_club.pressing) * (0.6 + 0.5 * x / L) + 0.9 * high_press
            if pressed:
                presser = self.pick(opp, L - x)
                self.emit("pressure", team_id=opp, player_id=presser, x=L - x, y=W - y)

            # Defensive duel: tackle, or a foul.
            duel = rng.random() < 0.085 * (1.4 if pressed else 1.0) * (1.0 + 3.0 * high_press)
            if duel:
                defender = self.pick(opp, L - x)
                dplayer = self.player(defender)
                in_box = x >= BOX_X and abs(y - W / 2) <= BOX_HALF_WIDTH
                if rng.random() < 0.16 * (1.3 - opp_club.discipline) / 0.7 * (BOX_FOUL if in_box else 1.0):
                    sent_off = self.foul(opp, defender, carrier, L - x, W - y)
                    if in_box:  # D-10: a foul in the box is a penalty
                        return self.penalty(team)
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
            if x >= SHOOTING_RANGE_X:
                centrality = 1 - min(abs(y - W / 2) / (W / 2), 1)
                depth = (x - SHOOTING_RANGE_X) / (L - SHOOTING_RANGE_X)
                p_shot = (0.069 + 0.074 * depth ** 0.5) * (0.1 + 1.8 * centrality ** 2) * (0.55 + 0.85 * club.attack) * 0.77 * s ** 0.5  # open play only: set pieces add the rest (D-10)
                # Style (PA-1): some sides shoot from distance more readily (0.5 = league norm).
                p_shot *= (0.3 + 1.9 * club.long_shots) if x < BOX_X else (1.18 - 0.36 * club.long_shots)
                if rng.random() < p_shot:
                    return self.shoot(team, x, y, carrier, last_pass, pressed)

            # Occasional offensive foul by the carrier.
            if rng.random() < 0.006 * (1.3 - club.discipline) / 0.7:
                victim = self.pick(opp, L - x)
                self.foul(team, carrier, victim, x, y, attacking=True)
                self.change(opp, "foul", L - x, W - y)
                return opp, L - x, W - y, self.pick(opp, L - x)

            # Pass.
            directness = 1 - club.possession
            dx = rng.gauss(3.0 + 9.0 * directness - (4 if x > 85 else 0), 10.0)
            if x < 20 and c.position == "GK":
                dx = abs(dx) + rng.uniform(10, 45 * directness + 10)
            dy = rng.gauss(0, 7.0 + 8.0 * directness)
            # Style (PA-1): building up through midfield, they steer play towards their favoured flank.
            if club.flank != "balanced" and 30 < x < 80 and rng.random() < 0.31 * club.flank_strength:
                target = W / 6 if club.flank == "left" else 5 * W / 6
                dy = (target - y) * rng.uniform(0.45, 0.85) + rng.gauss(0, 4.0)
            # Wide players cross towards the box.
            if x > 80 and abs(y - W / 2) > 18 and rng.random() < 0.35:
                dx, dy = rng.uniform(L - 14 - x, L - 6 - x), (W / 2 - y) * rng.uniform(0.6, 1.0)
            # Players aim inside the pitch; the ball only goes out when a pass fails.
            ex, ey = _clamp(x + dx, 1.0, L - 4.0), _clamp(y + dy, 1.0, W - 1.0)
            dx, dy = ex - x, ey - y
            length = math.hypot(dx, dy)
            progress = max(0.0, ex - x) / 30
            p_ok = (
                0.92
                - 0.0045 * max(0.0, length - 12)
                - 0.10 * progress * (1.5 - club.attack)
                - (0.08 + 0.35 * high_press if pressed else 0.0)  # a high press forces errors deep in their half
                - (0.10 if ex > 88 else 0.0)
                - (0.025 if self.wet else 0.0)
                + 0.10 * (c.passing - 0.65)
                + 0.20 * (club.possession - 0.55)
                - 0.06 * (opp_club.defence - 0.65)
            ) * s ** 0.25
            self.tick((1.9 + length / 11 + rng.uniform(0, 1.6)) * SEC)
            if rng.random() < _clamp(p_ok, 0.25, 0.985):
                receiver = self.pick(team, ex, exclude=carrier, receiving=True)
                last_pass = self.emit(
                    "pass", team_id=team, player_id=carrier, x=x, y=y, end_x=ex, end_y=ey,
                    outcome="complete", receiver_id=receiver, under_pressure=pressed,
                )
                x, y, carrier = _clamp(ex, 0.5, L - 0.5), _clamp(ey, 0.5, W - 0.5), receiver
                continue

            ex, ey = _clamp(ex, 0, L), _clamp(ey, 0, W)
            if rng.random() < 0.25:
                self.emit("pass", team_id=team, player_id=carrier, x=x, y=y, end_x=ex, end_y=ey,
                          outcome="out", under_pressure=pressed)
                self.change(opp, "out_of_play", L - ex, W - ey)
                self.tick(rng.uniform(6, 18) * SEC)
                self.do_subs(team)
                self.do_subs(opp)
                return opp, L - ex, W - ey, self.pick(opp, L - ex)
            self.emit("pass", team_id=team, player_id=carrier, x=x, y=y, end_x=ex, end_y=ey,
                      outcome="incomplete", under_pressure=pressed)
            if ex >= 94 and rng.random() < CORNER_FROM_CLEARANCE:  # D-10: cleared behind for a corner
                return self.corner(team)
            if rng.random() < 0.55:
                interceptor = self.pick(opp, L - ex)
                self.emit("interception", team_id=opp, player_id=interceptor, x=L - ex, y=W - ey)
                self.change(opp, "interception", L - ex, W - ey)
                return opp, L - ex, W - ey, interceptor
            self.change(opp, "incomplete_pass", L - ex, W - ey)
            return opp, L - ex, W - ey, self.pick(opp, L - ex)
        return team, x, y, carrier

    def penalty(self, team: str):
        """D-10: the best finisher on the pitch takes it from the spot."""
        taker = max(self.on_pitch[team], key=lambda pid: self.player(pid).shooting)
        self.emit("penalty", team_id=team, player_id=taker, x=L - 11, y=W / 2)
        self.tick(self.rng.uniform(60, 100) * SEC)
        return self.shoot(team, L - 11, W / 2, taker, None, False, set_piece="penalty")

    def corner(self, team: str):
        """D-10: a corner from the flag, delivered into the box."""
        rng = self.rng
        opp = self.other(team)
        self.tick(rng.uniform(20, 35) * SEC)
        taker = self.pick(team, 95)
        cy = rng.choice([0.5, W - 0.5])
        self.emit("corner", team_id=team, player_id=taker, x=L - 0.5, y=cy)
        self.tick(rng.uniform(4, 8) * SEC)
        ex, ey = rng.uniform(94, 101.5), rng.uniform(24, 44)
        if rng.random() < CORNER_FIND:
            receiver = self.pick(team, ex, exclude=taker)
            delivery = self.emit("pass", team_id=team, player_id=taker, x=L - 0.5, y=cy, end_x=ex, end_y=ey,
                                 outcome="complete", receiver_id=receiver, set_piece="corner")
            self.tick(rng.uniform(0.6, 1.2) * SEC)
            if rng.random() < CORNER_SHOT:
                return self.shoot(team, ex, ey, receiver, delivery, True, set_piece="corner")
            return team, ex, ey, receiver
        self.emit("pass", team_id=team, player_id=taker, x=L - 0.5, y=cy, end_x=ex, end_y=ey,
                  outcome="incomplete", set_piece="corner")
        self.change(opp, "incomplete_pass", L - ex, W - ey)
        return opp, L - ex, W - ey, self.pick(opp, L - ex)

    def shoot(self, team, x, y, shooter, last_pass, pressed, set_piece: str | None = None):
        rng = self.rng
        opp = self.other(team)
        p = self.player(shooter)
        dist = math.hypot(L - x, W / 2 - y)
        angle = math.atan2(7.32 * (L - x), (L - x) ** 2 + (W / 2 - y) ** 2 - 3.66 ** 2)
        if angle < 0:
            angle += math.pi
        header = set_piece != "penalty" and last_pass is not None and abs(last_pass.y - W / 2) > 18 and dist < 14 \
            and rng.random() < 0.55
        body = "head" if header else rng.choices(["right_foot", "left_foot"], [0.7, 0.3])[0]

        # Finishing = the engine's xG for this chance, adjusted for the shooter, the
        # defence, the attack and the current balance of play. Adjustments are centred on
        # a league-average player so total goals track total xG.
        s = self.strength(team) / self.strength(opp)
        skill = (
            (1 + 0.9 * (p.shooting - 0.62))
            * (1 - 0.8 * (self.clubs[opp].defence - 0.64))
            * (1 + 0.8 * (self.clubs[team].attack - 0.66))
            * s ** 0.3
        )
        p_goal = _clamp(expected_goals(x, y, header=header, under_pressure=pressed) * skill * FINISHING, 0.005, 0.9)
        if set_piece == "penalty":
            p_goal = _clamp(PENALTY_XG * (1 + 0.5 * (p.shooting - 0.62)), 0.6, 0.93)
        speed = rng.gauss(58, 7) if header else rng.gauss(78 + 25 * p.shooting - 0.4 * dist, 11)
        speed = round(_clamp(speed, 35, 135), 1)

        r = rng.random()
        if r < p_goal:
            outcome = "goal"
        else:
            r = rng.random()
            if set_piece == "penalty":
                outcome = "saved" if r < 0.6 else "off_target" if r < 0.88 else "woodwork"
            else:
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
            shot_speed_kmh=speed, body_part=body, under_pressure=pressed, set_piece=set_piece,
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
            if rng.random() < CORNER_FROM_SAVE:  # parried behind for a corner
                return self.corner(team)
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
        # blocked or woodwork: behind for a corner, or a scramble for the loose ball
        if outcome == "blocked" and rng.random() < CORNER_FROM_BLOCK:
            return self.corner(team)
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
