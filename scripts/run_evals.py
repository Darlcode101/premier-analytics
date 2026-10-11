"""Evaluate the AI path on fixed matches (A-8) and write docs/EVALS.md.

    python scripts/run_evals.py [--matches 3] [--no-project]

1. Plays fixed matches through the real pipeline (Foundry models) for four audiences and
   saves every published AI overlay with the facts it was given (evals/data.jsonl).
2. Deterministic checks: Critic re-check, language, length, analyst-vs-fan differences.
3. AI judges: Azure AI Evaluation SDK (groundedness, relevance, coherence, fluency) plus a
   custom "explains why" rubric judged by a different model family. The run is logged to the
   Foundry project (Evaluations tab) unless --no-project.
"""
import argparse
import asyncio
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from pydantic import BaseModel, Field  # noqa: E402

from premier_analytics.agents import AgentFrameworkLLM, CriticAgent, ResilientLLM  # noqa: E402
from premier_analytics.evals import (  # noqa: E402
    collect, detect_language, flesch_reading_ease, grounding_recheck, is_plain_for_fans, mode_gap, number_density,
)
from premier_analytics.league import load_league  # noqa: E402
from premier_analytics.overlay import MAX_BODY, MAX_HEADLINE, Audience  # noqa: E402

FIXTURES = [("har", "ngc", 42), ("kin", "oak", 9), ("sto", "iro", 7)]
AUDIENCES = [Audience(mode="fan", language="en"), Audience(mode="analyst", language="en"),
             Audience(mode="fan", language="es"), Audience(mode="fan", language="ar")]
OUT = ROOT / "evals"
ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
ACCOUNT = "https://" + ENDPOINT.split("//")[1].split(".")[0] + ".openai.azure.com"  # judges use the resource endpoint
LIVE, RECAP = os.environ["LIVE_MODEL_DEPLOYMENT"], os.environ["RECAP_MODEL_DEPLOYMENT"]


class WhyVerdict(BaseModel):
    score: int = Field(description="1-5")
    reason: str = Field(description="One sentence.")


class ExplainsWhyJudge:
    """Custom rubric: does the text explain WHY the moment matters, using only the facts?"""

    instructions = (
        "You grade on-screen football explanations. Score 1-5: 5 = clearly explains why the moment matters "
        "(consequence, context or pattern) using only the given facts; 3 = mostly restates what happened with "
        "a little context; 1 = only restates, or claims things the facts don't support. Reply with a score and "
        "one sentence."
    )

    def __call__(self, *, query: str, context: str, response: str):
        # The SDK calls evaluators from worker threads, each with its own event loop, and a model client
        # can't be shared across event loops, so each call gets its own (cheap) client.
        llm = AgentFrameworkLLM(RECAP, ENDPOINT, os.environ.get("AZURE_OPENAI_API_KEY") or None)
        prompt = f"{query}\n\nFacts:\n{context}\n\nText to grade:\n{response}"
        res = asyncio.run(llm.generate("judge", self.instructions, prompt, WhyVerdict))
        return {"explains_why": res.value.score, "explains_why_reason": res.value.reason}


def ai_judges(data_path: Path, use_project: bool) -> dict:
    from azure.ai.evaluation import CoherenceEvaluator, FluencyEvaluator, GroundednessEvaluator, RelevanceEvaluator, evaluate
    from azure.identity import DefaultAzureCredential

    cred = DefaultAzureCredential()
    model = {"azure_endpoint": ACCOUNT, "azure_deployment": LIVE, "api_version": "2024-10-21"}
    evaluators = {
        "groundedness": GroundednessEvaluator(model, credential=cred),
        "relevance": RelevanceEvaluator(model, credential=cred),
        "coherence": CoherenceEvaluator(model, credential=cred),
        "fluency": FluencyEvaluator(model, credential=cred),
        "why": ExplainsWhyJudge(),
    }
    kwargs = dict(data=str(data_path), evaluators=evaluators, evaluation_name=f"premier-analytics-{date.today()}",
                  output_path=str(OUT / "results.json"))
    if use_project:
        try:
            return evaluate(**kwargs, azure_ai_project=ENDPOINT)
        except Exception as err:  # still evaluate locally if logging to the project isn't permitted
            print(f"Foundry project logging failed ({type(err).__name__}: {str(err)[:200]}); running locally")
    return evaluate(**kwargs)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--matches", type=int, default=3)
    p.add_argument("--no-project", action="store_true")
    args = p.parse_args()

    league = load_league()
    critic = CriticAgent({pl.name for c in league.clubs for pl in league.squad(c.id)}, {c.short_name for c in league.clubs})
    key = os.environ.get("AZURE_OPENAI_API_KEY") or None
    llm = ResilientLLM(AgentFrameworkLLM(LIVE, ENDPOINT, key), AgentFrameworkLLM(RECAP, ENDPOINT, key), timeout_s=15, retries=1)

    records = asyncio.run(collect(league, FIXTURES[: args.matches], AUDIENCES, llm, critic))
    OUT.mkdir(exist_ok=True)
    data_path = OUT / "data.jsonl"
    with data_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r.row(), ensure_ascii=False) + "\n")
    print(f"collected {len(records)} AI overlays from {args.matches} matches")

    # ---- deterministic ----
    grounded = grounding_recheck(records, critic, league)
    lang_ok = statistics.mean(detect_language(r.headline + " " + r.body) == r.audience.language for r in records)
    length_ok = statistics.mean(len(r.headline) <= MAX_HEADLINE and len(r.body) <= MAX_BODY for r in records)
    by_moment = defaultdict(dict)
    for r in records:
        if r.audience.language == "en":
            by_moment[r.moment.id][r.audience.mode] = {"headline": r.headline, "body": r.body}
    pairs = [v for v in by_moment.values() if {"fan", "analyst"} <= set(v)]
    gaps = [mode_gap(v["fan"], v["analyst"]) for v in pairs]
    fan_en = [r for r in records if r.audience.mode == "fan" and r.audience.language == "en"]
    analyst_en = [r for r in records if r.audience.mode == "analyst"]

    def text(r):
        return f"{r.headline}. {r.body}"

    det = {
        "overlays": len(records), "matches": args.matches,
        "critic_recheck_pass": grounded, "language_correct": lang_ok, "within_length": length_ok,
        "pairs": len(pairs),
        "analyst_more_numbers": statistics.mean(g["more_numbers"] for g in gaps) if gaps else None,
        "fan_plain": statistics.mean(is_plain_for_fans(text(r)) for r in fan_en) if fan_en else None,
        "numbers_per_100_chars": {"fan": statistics.mean(number_density(text(r)) for r in fan_en),
                                  "analyst": statistics.mean(number_density(text(r)) for r in analyst_en)},
        "flesch": {"fan": statistics.mean(flesch_reading_ease(text(r)) for r in fan_en),
                   "analyst": statistics.mean(flesch_reading_ease(text(r)) for r in analyst_en)},
    }
    (OUT / "deterministic.json").write_text(json.dumps(det, indent=2))
    print(json.dumps(det, indent=2))

    # ---- AI judges ----
    result = ai_judges(data_path, use_project=not args.no_project)
    metrics = {k: v for k, v in result["metrics"].items() if isinstance(v, (int, float))}
    (OUT / "ai_metrics.json").write_text(json.dumps({"metrics": metrics, "studio_url": result.get("studio_url")}, indent=2))
    print(json.dumps(metrics, indent=2))
    print("Foundry:", result.get("studio_url"))


if __name__ == "__main__":
    main()
