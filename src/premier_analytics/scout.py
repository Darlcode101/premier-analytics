"""Moment Scout: decides which events matter, scores them 0-1, and attaches evidence.

Deterministic rules over the statistics engine. Each Moment carries Facts with stable IDs
and the source events they came from, so every number a downstream agent writes can be
traced back (E-2, E-3). Viewers filter by severity: fans see less, analysts see more.
"""
from __future__ import annotations

from pydantic import BaseModel

from .engine import MIN, MatchEngine, PassMetrics, ShotMetrics
from .schema import Event

FAN_THRESHOLD = 0.5
ANALYST_THRESHOLD = 0.3

BIG_CHANCE_XG = 0.3
ROCKET_KMH = 110.0
DOMINANCE = 0.5
MOMENTUM_COOLDOWN = 8 * MIN
MOMENTUM_MIN_SHOTS = 2  # territory without shots isn't momentum
PRESSURE_COOLDOWN = 10 * MIN
TREND_WARMUP = 5 * MIN
TREND_EVERY = 15_000

# E-4: what a spell means for the team on top, by goal difference (no digits: nothing for the Critic to misread).
# E-6: what a missed shot would have meant, from the shooting team's side.
IF_SCORED = {
    "opener": "would have opened the scoring",
    "ahead": "would have put them ahead",
    "equalise": "would have equalised",
    "back": "would have pulled one back",
    "extend": "would have extended their lead",
}

STAKES = {
    "opener": "goalless, pushing for the opening goal",
    "level": "level, pushing to go ahead",
    "one_down": "one goal down, chasing an equaliser",
    "behind": "two or more goals down, chasing the game",
    "one_up": "one goal up, looking for a second to make it safer",
    "ahead": "two or more goals up, in control",
}


class Fact(BaseModel):
    id: str
    label: str
    value: bool | int | float | str
    subject: str | None = None
    source_event_ids: list[str]


class Moment(BaseModel):
    id: str
    kind: str
    severity: float
    event_id: str
    period: int
    clock_ms: int
    elapsed_ms: int
    team_id: str | None = None
    player_id: str | None = None
    facts: list[Fact]


class MomentScout:
    def __init__(self, home_id: str, away_id: str, match_id: str, engine: MatchEngine | None = None):
        self.home_id, self.away_id = home_id, away_id
        self.match_id = match_id
        self.engine = engine or MatchEngine(home_id, away_id)
        self._count = 0
        self._last_trend_check = -TREND_EVERY
        self._last_dominant: str | None = None
        self._last_shift = -MOMENTUM_COOLDOWN
        self._last_spell = {home_id: -PRESSURE_COOLDOWN, away_id: -PRESSURE_COOLDOWN}
        self._goal_times: dict[str, list[int]] = {home_id: [], away_id: []}
        self._spells: list[tuple[str, float]] = []  # (team, window xG) of each trend moment so far

    # ---------- construction helpers ----------

    def _moment(self, kind: str, severity: float, e: Event, facts: list[tuple], team=None, player=None) -> Moment:
        """facts: (label, value, subject, source_event_ids)"""
        mid = f"{self.match_id}-mo{self._count:04d}"
        self._count += 1
        # Context every explanation needs: the scoreline and the time, plus shot totals for trends.
        have = {f[0] for f in facts}
        context = [
            ("score_home", self.engine.score[0], None, [e.id]),
            ("score_away", self.engine.score[1], None, [e.id]),
            ("minute", e.clock_ms // MIN + 1, None, [e.id]),
        ]
        if kind in ("momentum_shift", "pressure_spell") and team:
            context += [
                ("team_shots", self.engine.teams[team].shots, team, [e.id]),
                ("opponent_shots", self.engine.teams[self.other(team)].shots, self.other(team), [e.id]),
            ] + self._meaning(team, e)
        facts = list(facts) + [c for c in context if c[0] not in have]
        return Moment(
            id=mid, kind=kind, severity=round(min(1.0, severity), 3), event_id=e.id,
            period=e.period, clock_ms=e.clock_ms, elapsed_ms=e.elapsed_ms,
            team_id=team, player_id=player,
            facts=[
                Fact(id=f"{mid}-f{i}", label=label, value=value, subject=subject, source_event_ids=sources)
                for i, (label, value, subject, sources) in enumerate(facts)
            ],
        )

    def _meaning(self, team: str, e: Event) -> list[tuple]:
        """E-4: the conclusions about a spell, computed here so the AI only has to phrase them."""
        eng = self.engine
        window = eng.window_ms
        now = eng.snapshot()
        before = eng.snapshot(at_ms=max(0, e.elapsed_ms - window)).teams[team].window.shots
        shots, xg = now.teams[team].window.shots, now.teams[team].window.xg
        mine, theirs = (eng.score[0], eng.score[1]) if team == self.home_id else (eng.score[1], eng.score[0])
        diff = mine - theirs
        stakes = ("opener" if mine == theirs == 0 else "level" if diff == 0 else "one_down" if diff == -1
                  else "behind" if diff < -1 else "one_up" if diff == 1 else "ahead")
        mine_before = [x for t, x in self._spells if t == team]
        rank = ("first spell on top" if not mine_before else "strongest spell so far" if xg >= max(mine_before)
                else "back on top" if self._spells[-1][0] != team else "another spell on top")
        self._spells.append((team, xg))
        trend = "more" if shots > before else "fewer" if shots < before else "as many"
        goals = sum(1 for t in self._goal_times[team] if e.elapsed_ms - t < window)
        return [
            ("stakes", STAKES[stakes], team, [e.id]),
            ("spell_rank", rank, team, [e.id]),
            ("window_shots_before", before, team, [e.id]),
            ("shots_trend", f"{trend} shots than the 10 minutes before" if trend != "as many"
             else "as many shots as the 10 minutes before", team, [e.id]),
            ("opponent_window_shots", now.teams[self.other(team)].window.shots, self.other(team), [e.id]),
            ("goals_in_spell", goals, team, [e.id]),
        ]

    def other(self, team: str) -> str:
        return self.away_id if team == self.home_id else self.home_id

    # ---------- observation ----------

    def observe(self, e: Event) -> list[Moment]:
        metrics = self.engine.apply(e)
        out: list[Moment] = []
        handler = getattr(self, f"_on_{e.type}", None)
        if handler is not None:
            out += handler(e, metrics)
        if e.elapsed_ms >= TREND_WARMUP and e.elapsed_ms - self._last_trend_check >= TREND_EVERY:
            self._last_trend_check = e.elapsed_ms
            out += self._trends(e)
        return out

    def _on_goal(self, e: Event, _) -> list[Moment]:
        eng = self.engine
        self._goal_times[e.team_id].append(e.elapsed_ms)
        shot = eng.metrics.get(e.related_event_id)
        team = eng.teams[e.team_id]
        scorer_goals = eng.players[e.player_id].goals
        diff = (e.score_home - e.score_away) * (1 if e.team_id == self.home_id else -1)
        late_decisive = e.clock_ms >= 80 * MIN and diff in (0, 1)
        before = diff - 1  # the scoring side's margin just before this goal
        context = (
            "equaliser" if before == -1 else "takes_lead" if before == 0
            else "extends_lead" if before >= 1 else "pulls_one_back"
        )
        src = [e.id, e.related_event_id]
        facts = [
            ("score_home", e.score_home, None, [e.id]),
            ("score_away", e.score_away, None, [e.id]),
            ("scorer", e.player_id, e.team_id, [e.id]),
            ("minute", e.clock_ms // MIN + 1, None, [e.id]),
            ("goal_context", context, e.team_id, [e.id]),
            ("team_shots", team.shots, e.team_id, src),
            ("team_xg", round(team.xg, 2), e.team_id, src),
        ]
        if isinstance(shot, ShotMetrics):
            facts += [
                ("shot_xg", round(shot.xg, 2), e.player_id, [e.related_event_id]),
                ("shot_distance_m", round(shot.distance_m, 1), e.player_id, [e.related_event_id]),
            ]
        if e.assist_id:
            facts.append(("assist", e.assist_id, e.team_id, [e.id]))
        out = [self._moment("goal", 1.0 if late_decisive else 0.95, e, facts, e.team_id, e.player_id)]
        if scorer_goals >= 2:
            out.append(self._moment(
                "milestone", 1.0 if scorer_goals >= 3 else 0.9, e,
                [("player_goals", scorer_goals, e.player_id, [e.id]),
                 ("milestone", "hat_trick" if scorer_goals == 3 else "brace" if scorer_goals == 2 else "goals", e.player_id, [e.id])],
                e.team_id, e.player_id,
            ))
        return out

    def _on_shot(self, e: Event, m: ShotMetrics) -> list[Moment]:
        if e.outcome == "goal":
            return []  # the goal event that follows carries this
        mine, theirs = self.engine.score if e.team_id == self.home_id else self.engine.score[::-1]
        diff = mine - theirs
        if_scored = ("opener" if mine == theirs == 0 else "ahead" if diff == 0 else "equalise" if diff == -1
                     else "back" if diff < -1 else "extend")
        base = [
            ("shot_xg", round(m.xg, 2), e.player_id, [e.id]),
            ("shot_distance_m", round(m.distance_m, 1), e.player_id, [e.id]),
            ("outcome", e.outcome, e.player_id, [e.id]),
            ("if_scored", IF_SCORED[if_scored], e.team_id, [e.id]),
        ]
        out = []
        if m.xg >= BIG_CHANCE_XG:
            sev = 0.6 + 0.25 * min(1.0, (m.xg - BIG_CHANCE_XG) / 0.4)
            out.append(self._moment("big_chance", sev, e, base, e.team_id, e.player_id))
        elif e.outcome == "woodwork":
            out.append(self._moment("woodwork", 0.6, e, base, e.team_id, e.player_id))
        elif e.outcome == "saved" and m.xg >= 0.08:
            out.append(self._moment("shot_on_target", 0.4, e, base, e.team_id, e.player_id))
        if e.shot_speed_kmh >= ROCKET_KMH and e.outcome in ("saved", "woodwork"):
            out.append(self._moment(
                "rocket_shot", 0.5, e,
                [("shot_speed_kmh", e.shot_speed_kmh, e.player_id, [e.id])] + base, e.team_id, e.player_id,
            ))
        return out

    def _on_card(self, e: Event, _) -> list[Moment]:
        facts = [("card", e.card, e.player_id, [e.id])]
        if e.card == "yellow":
            return [self._moment("yellow_card", 0.35, e, facts, e.team_id, e.player_id)]
        reds = self.engine.teams[e.team_id].red_cards
        facts.append(("players_remaining", 11 - reds, e.team_id, [e.id]))
        return [self._moment("red_card", 0.9, e, facts, e.team_id, e.player_id)]

    def _on_pass(self, e: Event, m: PassMetrics) -> list[Moment]:
        if e.outcome == "complete" and m.difficulty >= 0.75:
            return [self._moment(
                "great_pass", 0.3, e,
                [("pass_difficulty", round(m.difficulty, 2), e.player_id, [e.id]),
                 ("pass_distance_m", round(m.distance_m, 1), e.player_id, [e.id])],
                e.team_id, e.player_id,
            )]
        return []

    def _on_substitution(self, e: Event, _) -> list[Moment]:
        return [self._moment(
            "substitution", 0.3, e,
            [("player_in", e.player_in_id, e.team_id, [e.id]), ("player_out", e.player_out_id, e.team_id, [e.id])],
            e.team_id, e.player_in_id,
        )]

    def _on_period_end(self, e: Event, _) -> list[Moment]:
        snap = self.engine.snapshot()
        h, a = snap.teams[self.home_id], snap.teams[self.away_id]
        src = [e.id]
        facts = [
            ("score_home", e.score_home, None, src),
            ("score_away", e.score_away, None, src),
            ("possession_home_pct", round(h.possession_pct, 1), self.home_id, src),
            ("shots_home", h.shots, self.home_id, src),
            ("shots_away", a.shots, self.away_id, src),
            ("xg_home", round(h.xg, 2), self.home_id, src),
            ("xg_away", round(a.xg, 2), self.away_id, src),
        ]
        kind = "half_time" if e.period == 1 else "full_time"
        return [self._moment(kind, 0.8, e, facts)]

    # ---------- trends ----------

    def _trends(self, e: Event) -> list[Moment]:
        snap = self.engine.snapshot()
        out = []
        m_home = snap.teams[self.home_id].window.momentum
        dominant = self.home_id if m_home >= DOMINANCE else self.away_id if m_home <= -DOMINANCE else None
        if (
            dominant is not None
            and dominant != self._last_dominant
            and snap.teams[dominant].window.shots >= MOMENTUM_MIN_SHOTS
            and e.elapsed_ms - self._last_shift >= MOMENTUM_COOLDOWN
        ):
            w = snap.teams[dominant].window
            out.append(self._moment(
                "momentum_shift", 0.6, e,
                [
                    ("momentum", round(w.momentum, 2), dominant, [e.id]),
                    ("field_tilt", round(w.field_tilt, 2), dominant, [e.id]),
                    ("window_shots", w.shots, dominant, [e.id]),
                    ("window_xg", round(w.xg, 2), dominant, [e.id]),
                    ("window_minutes", self.engine.window_ms // MIN, None, [e.id]),
                ],
                dominant,
            ))
            self._last_dominant = dominant
            self._last_shift = e.elapsed_ms
        for team in (self.home_id, self.away_id):
            w = snap.teams[team].window
            if w.field_tilt >= 0.75 and w.shots >= 3 and e.elapsed_ms - self._last_spell[team] >= PRESSURE_COOLDOWN:
                facts = [
                    ("field_tilt", round(w.field_tilt, 2), team, [e.id]),
                    ("window_shots", w.shots, team, [e.id]),
                    ("tempo_passes_per_min", round(w.tempo, 1), team, [e.id]),
                    ("window_minutes", self.engine.window_ms // MIN, None, [e.id]),
                ]
                if w.ppda is not None:
                    facts.append(("ppda", round(w.ppda, 1), team, [e.id]))
                out.append(self._moment("pressure_spell", 0.5, e, facts, team))
                self._last_spell[team] = e.elapsed_ms
        return out
