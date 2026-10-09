"""Simulate a 380-match season and print every realism metric next to its real target
(docs/REALISM.md). Use when tuning the generator: python scripts/calibrate.py"""
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from premier_analytics.engine import MatchEngine  # noqa: E402
from premier_analytics.generator import generate_match  # noqa: E402
from premier_analytics.league import load_league  # noqa: E402

BOX_X, BOX_Y = 105 - 16.5, (34 - 20.16, 34 + 20.16)
lg = load_league()
clubs = [c.id for c in lg.clubs]
pairings = [(h, a) for h in clubs for a in clubs if h != a]
season = [generate_match(*pairings[s % len(pairings)], seed=s) for s in range(380)]
teams = [(m, t) for m in season for t in (m.meta.home_id, m.meta.away_id)]


def cnt(m, t, ty, **kw):
    return sum(1 for e in m.events if e.type == ty and e.team_id == t and all(getattr(e, k) == v for k, v in kw.items()))


ps = [e for m in season for e in m.events if e.type == "pass"]
ss = [e for m in season for e in m.events if e.type == "shot"]
inside = [s for s in ss if s.x >= BOX_X and BOX_Y[0] <= s.y <= BOX_Y[1]]
inside_ids = {s.id for s in inside}
outside = [s for s in ss if s.id not in inside_ids]
res = defaultdict(int)
for m in season:
    f = m.events[-1]
    res["home" if f.score_home > f.score_away else "draw" if f.score_home == f.score_away else "away"] += 1
xg_total = 0.0
for m in season:
    eng = MatchEngine(m.meta.home_id, m.meta.away_id)
    for e in m.events:
        eng.apply(e)
    xg_total += sum(t.xg for t in eng.snapshot().teams.values())
goals = sum(e.type == "goal" for m in season for e in m.events)

rows = [
    ("goals/match", goals / 380, 2.93),
    ("passes/team", mean(cnt(m, t, "pass") for m, t in teams), 447),
    ("pass completion", sum(p.outcome == "complete" for p in ps) / len(ps), 0.834),
    ("shots/team", mean(cnt(m, t, "shot") for m, t in teams), 13.1),
    ("outside-box shot share", len(outside) / len(ss), 0.317),
    ("conversion", sum(s.outcome == "goal" for s in ss) / len(ss), 0.112),
    ("conversion inside box", sum(s.outcome == "goal" for s in inside) / len(inside), 0.147),
    ("conversion outside box", sum(s.outcome == "goal" for s in outside) / len(outside), 0.042),
    ("fouls/team", mean(cnt(m, t, "foul") for m, t in teams), 11.1),
    ("yellows/team", mean(cnt(m, t, "card", card="yellow") for m, t in teams), 2.04),
    ("reds/match", sum(e.type == "card" and e.card != "yellow" for m in season for e in m.events) / 380, 0.137),
    ("home win", res["home"] / 380, 0.408),
    ("draw", res["draw"] / 380, 0.245),
    ("away win", res["away"] / 380, 0.347),
    ("xG / goals", xg_total / goals, 1.0),
]
for name, actual, target in rows:
    print(f"{name:<24} {actual:>8.3f}   real {target}")

print("\nclub               passes  completion  goals/match")
for c in lg.clubs:
    mine = [(m, t) for m, t in teams if t == c.id]
    cp = [e for m, t in mine for e in m.events if e.type == "pass" and e.team_id == t]
    print(f"{c.name:<20} {mean(cnt(m, t, 'pass') for m, t in mine):>6.0f}  "
          f"{sum(p.outcome == 'complete' for p in cp) / len(cp):>9.1%}  {mean(cnt(m, t, 'goal') for m, t in mine):>8.2f}")
