"""Pattern detectors for the Pattern Analyst (PA-2, PA-3).

Watches the event stream and keeps, per team: final-third entries by channel and passer, where they win
the ball back, where their shots come from, and counter-attacks. A pattern is only reported when it is
real: enough actions and an exact binomial test against chance (or against the club's own season
style). Entries come in correlated chains, so the significance level is strict (tuned by the season
check in tests/test_patterns.py: strong styles found in most matches, balanced clubs flagged in no more
than 5 % of matches).
"""
from __future__ import annotations

from collections import Counter
from math import comb

from pydantic import BaseModel, Field

from .schema import PITCH_LENGTH, PITCH_WIDTH, Event

W, L = PITCH_WIDTH, PITCH_LENGTH
FINAL_THIRD_X = 70.0
BOX_X = L - 16.5
CHANNELS = ("left", "centre", "right")
MIRROR = {"left": "right", "centre": "centre", "right": "left"}  # their left is the defending side's right

# Thresholds (PA-3). Baselines are league-wide shares from the simulated season.
FLANK_MIN, FLANK_SHARE, FLANK_ALPHA = 15, 0.42, 0.01  # 380-match check: strong styles 56 %, false alarms 3.8 %
HALF_MIN, HALF_ALPHA = 10, 0.01
REGAIN_MIN, REGAIN_SHARE, REGAIN_BASE, REGAIN_ALPHA = 12, 0.35, 0.22, 0.001
LONG_MIN, LONG_SHARE, LONG_BASE, LONG_ALPHA = 6, 0.5, 0.27, 0.01
HUB_MIN, HUB_SHARE, HUB_BASE, HUB_ALPHA = 15, 0.33, 0.18, 0.001
COUNTER_MIN, COUNTER_SHARE, COUNTER_BASE, COUNTER_ALPHA, COUNTER_MS = 3, 0.4, 0.15, 0.01, 15_000
USUAL_MIN, USUAL_ALPHA = 15, 0.001


def binomial_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    return min(1.0, sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(max(k, 0), n + 1)))


def binomial_lower(k: int, n: int, p: float) -> float:
    """P(X <= k)."""
    return min(1.0, sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(0, k + 1)))


def channel_of(y: float) -> str:
    """Channel from the attacking team's point of view (its own frame: the low-y third is its left)."""
    return "left" if y < W / 3 else "centre" if y < 2 * W / 3 else "right"


def third_of(x: float) -> str:
    return "defensive" if x < L / 3 else "middle" if x < 2 * L / 3 else "attacking"


class Pattern(BaseModel):
    id: str
    team_id: str
    kind: str        # flank | high_regains | long_shots | hub | counters | switch | unusual
    scope: str       # match | second_half
    value: str       # channel, third, player id …
    count: int
    total: int
    share: float
    p_value: float
    numbers: dict = Field(default_factory=dict)


class _Team:
    def __init__(self):
        self.entries: list[tuple[int, int, str, str]] = []  # (elapsed_ms, period, channel, passer)
        self.regains: list[tuple[int, str]] = []           # (elapsed_ms, third)
        self.shots: list[tuple[int, float, float, bool]] = []  # (elapsed_ms, x, y, counter)
        self.last_regain_ms: int | None = None


class PatternTracker:
    def __init__(self, home_id: str, away_id: str, season_profiles: dict | None = None):
        self.home_id, self.away_id = home_id, away_id
        self.teams = {home_id: _Team(), away_id: _Team()}
        self.profiles = season_profiles or {}

    def observe(self, e: Event) -> None:
        t = self.teams.get(e.team_id) if e.team_id else None
        if t is None:
            return
        if e.type == "pass" and e.outcome == "complete" and e.x < FINAL_THIRD_X <= e.end_x:
            t.entries.append((e.elapsed_ms, e.period, channel_of(e.end_y), e.player_id))
        elif e.type == "interception" or (e.type == "tackle" and e.outcome == "won"):
            t.regains.append((e.elapsed_ms, third_of(e.x)))
            t.last_regain_ms = e.elapsed_ms
        elif e.type == "shot":
            counter = t.last_regain_ms is not None and e.elapsed_ms - t.last_regain_ms <= COUNTER_MS
            t.shots.append((e.elapsed_ms, e.x, e.y, counter))

    # ---------- raw counts (heatmaps, fan card) ----------

    def summary(self, team_id: str) -> dict:
        t = self.teams[team_id]
        return {
            "entries": {c: sum(ch == c for _, _, ch, _ in t.entries) for c in CHANNELS},
            "regains": {th: sum(x == th for _, x in t.regains) for th in ("defensive", "middle", "attacking")},
            "shots": [{"x": round(x, 1), "y": round(y, 1), "counter": c} for _, x, y, c in t.shots],
        }

    # ---------- detectors ----------

    def patterns(self) -> list[Pattern]:
        out: list[Pattern] = []
        for team_id in (self.home_id, self.away_id):
            out += self._team_patterns(team_id)
        return sorted(out, key=lambda p: (p.p_value, p.id))

    def _team_patterns(self, team_id: str) -> list[Pattern]:
        t = self.teams[team_id]
        out = []

        def make(kind, scope, value, k, n, p, **numbers):
            return Pattern(id=f"{team_id}:{kind}:{scope}:{value}", team_id=team_id, kind=kind, scope=scope, value=value,
                           count=k, total=n, share=k / n, p_value=p,
                           numbers={"count": k, "total": n, "share_pct": round(100 * k / n), **numbers})

        # Favoured flank, match so far.
        flank = self._flank([ch for _, _, ch, _ in t.entries], FLANK_MIN, FLANK_SHARE, FLANK_ALPHA)
        if flank:
            ch, k, n, p = flank
            out.append(make("flank", "match", ch, k, n, p, opponent_side=MIRROR[ch]))

        # A change of flank since half-time.
        first = [ch for _, period, ch, _ in t.entries if period == 1]
        second = [ch for _, period, ch, _ in t.entries if period == 2]
        half = self._flank(second, HALF_MIN, FLANK_SHARE, HALF_ALPHA)
        if half and first:
            first_main = Counter(first).most_common(1)[0][0]
            if half[0] != first_main:
                ch, k, n, p = half
                out.append(make("switch", "second_half", ch, k, n, p, first_half_channel=first_main))

        # Winning the ball high up the pitch.
        n = len(t.regains)
        k = sum(th == "attacking" for _, th in t.regains)
        if n >= REGAIN_MIN and k / n >= REGAIN_SHARE and (p := binomial_tail(k, n, REGAIN_BASE)) < REGAIN_ALPHA:
            out.append(make("high_regains", "match", "attacking", k, n, p))

        # Shooting from distance.
        n = len(t.shots)
        k = sum(x < BOX_X for _, x, _, _ in t.shots)
        if n >= LONG_MIN and k / n >= LONG_SHARE and (p := binomial_tail(k, n, LONG_BASE)) < LONG_ALPHA:
            out.append(make("long_shots", "match", "outside_box", k, n, p))

        # One player making them tick.
        n = len(t.entries)
        if n >= HUB_MIN:
            player, k = Counter(passer for _, _, _, passer in t.entries).most_common(1)[0]
            if k / n >= HUB_SHARE and (p := binomial_tail(k, n, HUB_BASE)) < HUB_ALPHA:
                out.append(make("hub", "match", player, k, n, p))

        # Counter-attacks.
        n = len(t.shots)
        k = sum(c for _, _, _, c in t.shots)
        if k >= COUNTER_MIN and k / n >= COUNTER_SHARE and (p := binomial_tail(k, n, COUNTER_BASE)) < COUNTER_ALPHA:
            out.append(make("counters", "match", "counter", k, n, p, seconds=COUNTER_MS // 1000))

        # Not using their usual flank (against the club's own season style).
        usual = self.profiles.get(team_id, {}).get("flank_shares")
        n = len(t.entries)
        if usual and n >= USUAL_MIN:
            ch = max(usual, key=usual.get)
            if ch != "centre" and usual[ch] >= 0.42:
                k = sum(c == ch for _, _, c, _ in t.entries)
                if (p := binomial_lower(k, n, usual[ch])) < USUAL_ALPHA:
                    out.append(make("unusual", "match", ch, k, n, p, season_share_pct=round(100 * usual[ch])))
        return out

    # ---------- known styles (season) with today's numbers ----------

    def style_notes(self) -> list[Pattern]:
        """The styles each club is known for this season, with how today compares (not today's own patterns)."""
        out = []
        for team_id in (self.home_id, self.away_id):
            profile = self.profiles.get(team_id)
            if not profile:
                continue
            t = self.teams[team_id]
            for style in profile.get("styles", []):
                kind, value = style["kind"], style["value"]
                if kind == "flank":
                    k, n = sum(c == value for _, _, c, _ in t.entries), len(t.entries)
                elif kind == "high_regains":
                    k, n = sum(th == "attacking" for _, th in t.regains), len(t.regains)
                elif kind == "long_shots":
                    k, n = sum(x < BOX_X for _, x, _, _ in t.shots), len(t.shots)
                else:  # playmaker
                    k, n = sum(passer == value for _, _, _, passer in t.entries), len(t.entries)
                numbers = {"season_share_pct": round(100 * style["share"]), "today_count": k, "today_total": n}
                if style.get("league") is not None:
                    numbers["league_share_pct"] = round(100 * style["league"])
                out.append(Pattern(id=f"{team_id}:{kind}:season:{value}", team_id=team_id, kind=kind, scope="season",
                                   value=value, count=k, total=n, share=k / n if n else 0.0, p_value=1.0,
                                   numbers=numbers))
        return out

    @staticmethod
    def _flank(channels: list[str], minimum: int, share: float, alpha: float):
        n = len(channels)
        if n < minimum:
            return None
        ch, k = Counter(channels).most_common(1)[0]
        p = min(1.0, 3 * binomial_tail(k, n, 1 / 3))  # three channels tested: Bonferroni
        return (ch, k, n, p) if k / n >= share and p < alpha else None
