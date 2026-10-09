"""Print a generated match's key moments, e.g.: python scripts/show_match.py har ngc 42 [--analyst]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from premier_analytics.generator import generate_match  # noqa: E402
from premier_analytics.league import load_league  # noqa: E402
from premier_analytics.scout import ANALYST_THRESHOLD, FAN_THRESHOLD, MomentScout  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
home, away, seed = (args + ["har", "ngc", "42"][len(args):])[:3]
threshold = ANALYST_THRESHOLD if "--analyst" in sys.argv else FAN_THRESHOLD
lg = load_league()
match = generate_match(home, away, int(seed))
scout = MomentScout(home, away, match.meta.match_id)


def name(pid):
    try:
        return lg.player(pid).name
    except KeyError:
        return pid


m = match.meta
print(f"{lg.club(home).name} v {lg.club(away).name} at {m.venue}  ({m.weather.condition}, {m.weather.temp_c}°C)\n")
for e in match.events:
    for mo in scout.observe(e):
        if mo.severity < threshold:
            continue
        minute = mo.clock_ms // 60000 + 1
        team = lg.club(mo.team_id).short_name if mo.team_id else ""
        facts = ", ".join(
            f"{f.label}={name(f.value) if isinstance(f.value, str) and '-' in f.value else f.value}" for f in mo.facts
        )
        who = name(mo.player_id) if mo.player_id else ""
        print(f"{minute:>3}'  {mo.severity:.2f}  {mo.kind:<15} {team:<12} {who:<24} {facts}")
