"""Full-time recap, end to end: the Recap agent queries the match MCP server over HTTP.

    python scripts/live_recap.py [home] [away] [seed]

Plays the match instantly (no AI overlays), serves the live match state over MCP on
localhost, then asks the Recap Producer for half-time and full-time recaps in English,
Spanish and Arabic. Prints which MCP tools the agent called.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402
from agent_framework import MCPStreamableHTTPTool  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from premier_analytics.agents import AgentFrameworkLLM, CriticAgent, ResilientLLM  # noqa: E402
from premier_analytics.generator import generate_match  # noqa: E402
from premier_analytics.league import load_league  # noqa: E402
from premier_analytics.mcp_server import MatchState, build_server  # noqa: E402
from premier_analytics.overlay import Names  # noqa: E402
from premier_analytics.recap import RecapProducer  # noqa: E402
from premier_analytics.scout import MomentScout  # noqa: E402

home, away, seed = (sys.argv[1:] + ["har", "ngc", "42"][len(sys.argv[1:]):])[:3]
load_dotenv(ROOT / ".env")
endpoint, key = os.environ["AZURE_OPENAI_ENDPOINT"], os.environ["AZURE_OPENAI_API_KEY"]
PORT = 8765

league = load_league()
match = generate_match(home, away, int(seed))
names = Names.from_league(league, home, away)
scout = MomentScout(home, away, match.meta.match_id)
state = MatchState(names=names, scout=scout)
for e in match.events:
    state.add_moments(scout.observe(e))

called: list[str] = []
server = build_server(state, on_call=lambda name, args: called.append(f"{name}({args})"))
critic = CriticAgent({p.name for c in league.clubs for p in league.squad(c.id)}, {c.short_name for c in league.clubs})
# The recap is off the live path, so the stronger reasoning model leads and the fast one backs it up.
llm = ResilientLLM(
    AgentFrameworkLLM(os.environ["RECAP_MODEL_DEPLOYMENT"], endpoint, key),
    AgentFrameworkLLM(os.environ["LIVE_MODEL_DEPLOYMENT"], endpoint, key),
    timeout_s=60, retries=0,
)


async def main():
    web = uvicorn.Server(uvicorn.Config(server.streamable_http_app(), port=PORT, log_level="warning"))
    serving = asyncio.create_task(web.serve())
    while not web.started:
        await asyncio.sleep(0.05)
    async with MCPStreamableHTTPTool(name="match", url=f"http://127.0.0.1:{PORT}/mcp") as mcp_tool:
        producer = RecapProducer(llm, critic, state, tools=[mcp_tool])
        for language in ("en", "es", "ar"):
            recap = await producer.run("full_time", language)
            print(f"\n=== full-time recap [{language}] ===")
            if recap is None:
                print("(rejected by the critic; template overlay stays)")
                continue
            print(recap.headline)
            print(recap.summary)
            for p in recap.key_points:
                print(" •", p)
            print(f"(model: {recap.model})")
    print("\nMCP tool calls made by the agent:")
    for c in called:
        print("  ", c)
    web.should_exit = True
    await serving


asyncio.run(main())
