"""Play a generated match through the full pipeline against the real Foundry models.

    python scripts/live_match.py [home] [away] [seed] [--speed 60]

Prints each AI upgrade next to its fast-path original, then latency and outcome stats.
"""
import argparse
import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from premier_analytics.agents import AgentFrameworkLLM, CriticAgent, ResilientLLM  # noqa: E402
from premier_analytics.generator import generate_match  # noqa: E402
from premier_analytics.league import load_league  # noqa: E402
from premier_analytics.orchestrator import Orchestrator  # noqa: E402
from premier_analytics.overlay import Audience, Names  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("home", nargs="?", default="har")
p.add_argument("away", nargs="?", default="ngc")
p.add_argument("seed", nargs="?", type=int, default=42)
p.add_argument("--speed", type=float, default=60.0, help="match seconds per real second")
args = p.parse_args()

load_dotenv(ROOT / ".env")
endpoint, key = os.environ["AZURE_OPENAI_ENDPOINT"], os.environ["AZURE_OPENAI_API_KEY"]
llm = ResilientLLM(
    AgentFrameworkLLM(os.environ["LIVE_MODEL_DEPLOYMENT"], endpoint, key),
    AgentFrameworkLLM(os.environ["RECAP_MODEL_DEPLOYMENT"], endpoint, key),
    timeout_s=4.0, retries=1,
)

league = load_league()
match = generate_match(args.home, args.away, args.seed)
names = Names.from_league(league, args.home, args.away)
star = next(p.id for p in league.squad(args.away) if p.position == "ST")
audiences = [
    Audience(mode="fan", language="en", club_id=args.home),
    Audience(mode="analyst", language="en"),
    Audience(mode="fan", language="es"),
    Audience(mode="fan", language="ar", player_id=star),
]
critic = CriticAgent(
    {p.name for c in league.clubs for p in league.squad(c.id)}, {c.short_name for c in league.clubs},
)
orch = Orchestrator(args.home, args.away, match.meta.match_id, names, audiences, llm=llm, critic=critic)


async def main():
    start = time.perf_counter()
    for e in match.events:
        target = e.elapsed_ms / 1000 / args.speed
        delay = target - (time.perf_counter() - start)
        if delay > 0:
            await asyncio.sleep(delay)
        await orch.handle(e)
    await orch.drain()


asyncio.run(main())

fast = {o.id: o for o in orch.published if o.source == "template"}
for o in orch.published:
    if o.source != "ai":
        continue
    f = fast[o.id]
    minute = o.clock_in_ms // 60000 + 1
    print(f"\n{minute:>3}' {o.kind:<15} [{o.audience}]  via {o.model}")
    print(f"     fast: {f.headline} | {f.body}")
    print(f"     AI:   {o.headline} | {o.body}")

attempted = {(t.moment_id, t.audience) for t in orch.trace if t.agent == "validator"}
published = [t for t in orch.trace if t.agent == "validator" and t.outcome == "published"]
stale = [t for t in orch.trace if t.outcome == "stale"]
rejected = [t for t in orch.trace if t.agent == "critic" and t.outcome == "rejected"]
errors = [t for t in orch.trace if t.outcome == "error"]
lat = sorted(t.ms for t in published)
calls = [t for t in orch.trace if t.agent in ("explainer", "personaliser", "translator") and t.outcome == "ok"]
print("\n=== summary ===")
print(f"fast overlays: {len(fast)}   AI upgrades published: {len(published)}   stale: {len(stale)}   "
      f"critic rejections: {len(rejected)}   model errors: {len(errors)}")
if lat:
    print(f"AI upgrade latency ms: p50 {statistics.median(lat):.0f}   p95 {lat[int(0.95 * (len(lat) - 1))]:.0f}   max {lat[-1]:.0f}")
print(f"model calls: {len(calls)}   by model: "
      + ", ".join(f"{m}={sum(c.model == m for c in calls)}" for m in sorted({c.model for c in calls})))
for r in rejected[:8]:
    print("  critic:", r.detail[:160])
for r in errors[:5]:
    print("  error:", r.agent, r.detail[:160])
print("per-agent latency ms (p50 / p95):")
for agent in ("explainer", "personaliser", "translator"):
    ms = sorted(t.ms for t in orch.trace if t.agent == agent and t.outcome == "ok")
    if ms:
        print(f"  {agent:<13} {statistics.median(ms):>6.0f} / {ms[int(0.95 * (len(ms) - 1))]:>6.0f}   n={len(ms)}")
for lang in ("en", "es", "ar"):
    ms = sorted(t.ms for t in published if f".{lang}." in t.audience)
    if ms:
        print(f"  upgrade [{lang}]   {statistics.median(ms):>6.0f} / {ms[int(0.95 * (len(ms) - 1))]:>6.0f}")
