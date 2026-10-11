"""Build the real-world context library (CX-1) with the Researcher agent and Foundry web search.

    python scripts/build_context_library.py [--only id1,id2]

For each topic the Researcher searches the web and answers with citations. An entry is kept only if
it has https sources, passes entry_problems, and every number appears on a cited page
(verify_against_source). Kept entries are translated into Spanish and Arabic and written to
src/premier_analytics/data/context_library.json; rejected ones are listed for a person to look at.
Review the file before committing it.
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import httpx  # noqa: E402

from premier_analytics.agents import AgentFrameworkLLM, Personalised, TranslatorAgent  # noqa: E402
from premier_analytics.context import (  # noqa: E402
    LIBRARY_PATH, AgentFrameworkWebSearch, ContextEntry, ResearcherAgent, Source, TopicSpec, entry_problems,
    verify_against_source,
)

B, T = "benchmark", "tactic"
TOPICS = [
    TopicSpec(id="goals-per-match", kind=B, topic="Goals per match", tags=["goal", "half_time", "full_time"],
              question="What was the average number of goals per match in the 2024/25 Premier League season?"),
    TopicSpec(id="home-wins", kind=B, topic="Home wins", tags=["full_time", "half_time"],
              question="Across the full 2024/25 Premier League season (all 380 matches), what percentage of matches were won by the home team?"),
    TopicSpec(id="draws", kind=B, topic="Draws", tags=["full_time"],
              question="In the completed 2024/25 Premier League season, how many of the 380 matches ended in a draw?"),
    TopicSpec(id="shots-per-match", kind=B, topic="Shots per match", tags=["pressure_spell", "momentum_shift", "full_time"],
              question="League-wide, how many shots did a Premier League team average per match over the full 2024/25 season?"),
    TopicSpec(id="xg-per-match", kind=B, topic="xG per match", tags=["goal", "big_chance", "half_time", "full_time"],
              question="League-wide, what was the average expected goals (xG) per team per match over the full 2024/25 Premier League season?"),
    TopicSpec(id="big-chance-conversion", kind=B, topic="Big chance conversion", tags=["big_chance", "goal"],
              question="What percentage of big chances (Opta definition) are converted into goals in the Premier League, league-wide?"),
    TopicSpec(id="shot-conversion", kind=B, topic="Shot conversion", tags=["goal", "rocket_shot"],
              question="Over the full 2024/25 Premier League season, what was the league-wide shot conversion rate (goals divided by all shots)?"),
    TopicSpec(id="outside-box-goals", kind=B, topic="Goals from outside the box", tags=["rocket_shot", "goal"],
              question="In the completed 2024/25 Premier League season, how many goals in total were scored from outside the penalty area?"),
    TopicSpec(id="headed-goals", kind=B, topic="Headed goals", tags=["goal"],
              question="In the completed 2024/25 Premier League season, how many headed goals were scored in total?"),
    TopicSpec(id="red-cards", kind=B, topic="Red cards", tags=["red_card"],
              question="How many red cards were shown in the 2024/25 Premier League season?"),
    TopicSpec(id="woodwork", kind=B, topic="Woodwork", tags=["woodwork"],
              question="How many times did teams hit the woodwork in the 2024/25 Premier League season in total?"),
    TopicSpec(id="scoring-first", kind=B, topic="Scoring first", tags=["goal", "full_time"],
              question="In the Premier League, what percentage of matches does the team that scores first go on to win?"),
    TopicSpec(id="comebacks", kind=B, topic="Comebacks", tags=["goal", "full_time"],
              question="How many points did Premier League teams win from losing positions in the 2024/25 season in total?"),
    TopicSpec(id="late-goals", kind=B, topic="Late goals", tags=["goal"], requires=["stoppage_time"],
              question="How many goals were scored in stoppage time in the 2024/25 Premier League season?"),
    TopicSpec(id="added-time", kind=B, topic="Added time", tags=["half_time", "full_time"],
              question="What was the average added (stoppage) time per Premier League match in 2024/25?"),
    TopicSpec(id="clean-sheets", kind=B, topic="Clean sheets", tags=["full_time"],
              question="How many clean sheets were kept in total in the 2024/25 Premier League season?"),
    TopicSpec(id="explain-xg", kind=T, topic="Expected goals (xG)", tags=["goal", "big_chance", "stat:xg"],
              question="What is expected goals (xG) in football and how is it calculated?"),
    TopicSpec(id="explain-big-chance", kind=T, topic="Big chance", tags=["big_chance", "stat:big_chances"],
              question="What is a 'big chance' in Opta football data?"),
    TopicSpec(id="explain-field-tilt", kind=T, topic="Field tilt", tags=["momentum_shift", "pressure_spell", "stat:field_tilt"],
              question="What is field tilt in football analytics?"),
    TopicSpec(id="explain-ppda", kind=T, topic="PPDA", tags=["pressure_spell", "stat:ppda"],
              question="What is PPDA (passes per defensive action) in football and what does a low PPDA mean?"),
    TopicSpec(id="explain-momentum", kind=T, topic="Momentum", tags=["momentum_shift"],
              question="How do football data providers measure match momentum, such as Opta's momentum or threat charts?"),
    TopicSpec(id="explain-pressing", kind=T, topic="High press and counter-press", tags=["pressure_spell", "momentum_shift"],
              question="What are the high press and counter-pressing (gegenpressing) in football?"),
    TopicSpec(id="explain-low-block", kind=T, topic="Low block", tags=["pressure_spell"],
              question="What is a low block in football defending?"),
    TopicSpec(id="explain-final-third", kind=T, topic="Final third entries", tags=["pressure_spell", "stat:final_third"],
              question="What are final third entries or passes into the final third in football analytics, and why do they matter?"),
    TopicSpec(id="explain-pass-accuracy", kind=T, topic="Pass accuracy", tags=["stat:pass_accuracy"],
              question="What does pass completion percentage tell you in football, and what are its limits?"),
    TopicSpec(id="explain-red-card-impact", kind=T, topic="Playing with ten men", tags=["red_card"],
              question="How does a red card typically affect a football team's chances of winning, according to research or data?"),
]


# Real 2024/25 figures already sourced for the simulation's calibration (docs/REALISM.md). They go through the
# same checks (numbers stated on the cited page) and are labelled with their origin. Figures that were derived
# there (home-win %, shots per team) fail that check and are deliberately left out.
SEEDS = [
    ContextEntry(id="outside-box-shots", kind=B, topic="Shots from outside the box", tags=["rocket_shot"],
                 origin="calibration sources", numbers=[31.7, 4.2], retrieved="",
                 text="In 2024/25, 31.7% of Premier League shots came from outside the box, and only 4.2% of those were scored.",
                 sources=[Source(url="https://theanalyst.com/articles/premier-league-2024-25-shot-data", title="Premier League 2024-25 shot data (The Analyst)")]),
]


def fetch(url: str) -> str | None:
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (research script)"})
        return r.text if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


async def translate(translator: TranslatorAgent, text: str, language: str) -> str:
    out = await translator.run(Personalised(headline="-", body=text), language)
    return out.body


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", default="")
    args = p.parse_args()
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    researcher = ResearcherAgent(AgentFrameworkWebSearch(os.environ["LIVE_MODEL_DEPLOYMENT"], endpoint))
    translator = TranslatorAgent(AgentFrameworkLLM(os.environ["LIVE_MODEL_DEPLOYMENT"], endpoint))
    only = set(filter(None, args.only.split(",")))
    existing = {e["id"]: e for e in json.loads(LIBRARY_PATH.read_text())} if LIBRARY_PATH.exists() else {}
    today = date.today().isoformat()

    kept, rejected = dict(existing), []
    for seed in SEEDS:
        if only and seed.id not in only:
            continue
        seed = seed.model_copy(update={"retrieved": today})
        problems = entry_problems(seed) + verify_against_source(seed, fetch)
        if problems:
            rejected.append((seed.id, "; ".join(problems)))
            continue
        seed.translations = {lang: await translate(translator, seed.text, lang) for lang in ("es", "ar")}
        if entry_problems(seed):
            rejected.append((seed.id, f"translation: {entry_problems(seed)}"))
            continue
        kept[seed.id] = json.loads(seed.model_dump_json())
        print(f"kept {seed.id} (calibration sources): {seed.text}")
    for spec in TOPICS:
        if only and spec.id not in only:
            continue
        entry = None
        for _ in range(2):
            try:
                entry = await researcher.build_entry(spec, retrieved=today)
            except Exception as err:
                rejected.append((spec.id, f"search failed: {err!r}"[:200]))
                break
            if entry:
                break
        if entry is None:
            rejected.append((spec.id, researcher.last_rejection))
            continue
        problems = verify_against_source(entry, fetch)
        if problems:
            rejected.append((spec.id, f"{'; '.join(problems)} | {entry.text} | {[s.url for s in entry.sources]}"))
            continue
        entry.translations = {lang: await translate(translator, entry.text, lang) for lang in ("es", "ar")}
        if entry_problems(entry):
            rejected.append((spec.id, f"translation: {entry_problems(entry)}"))
            continue
        kept[spec.id] = json.loads(entry.model_dump_json())
        print(f"kept {spec.id}: {entry.text[:110]}")

    LIBRARY_PATH.parent.mkdir(exist_ok=True)
    LIBRARY_PATH.write_text(json.dumps(list(kept.values()), ensure_ascii=False, indent=2) + "\n")
    print(f"\n{len(kept)} entries in {LIBRARY_PATH.relative_to(ROOT)}")
    for rid, why in rejected:
        print(f"REJECTED {rid}: {why}")


if __name__ == "__main__":
    asyncio.run(main())
