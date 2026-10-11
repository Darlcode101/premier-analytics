# Evaluations (A-8)

How good is the AI text that reaches the screen? We play **3 fixed matches** (seeds 42, 9, 7) through the
real pipeline on Microsoft Foundry for **4 audiences** (English fan, English analyst, Spanish fan, Arabic
fan), keep every published AI overlay with the facts it was given, and score it two ways:

- **Deterministic checks** that need no model.
- **AI judges**: the Azure AI Evaluation SDK's groundedness, relevance, coherence and fluency evaluators
  (`gpt-4.1-mini`), plus a custom **"explains why"** rubric judged by a different model family
  (`gpt-5-mini`) to limit self-grading. Runs are logged to the Foundry project's **Evaluations** tab.

Reproduce: `python scripts/run_evals.py` (≈ 15 min, under $1). Raw rows: `evals/results.json`.

## Results (final configuration, 175 AI overlays)

| Metric | Result | Pass bar (TEST_PLAN §6) | |
|---|---|---|---|
| Critic re-check of published text (numbers, names, goal context) | **100 %** | 100 % | ✅ |
| Output in the requested language (en / es / ar) | **100 %** | 100 % | ✅ |
| Within on-screen length limits | **100 %** | 100 % | ✅ |
| Analyst version carries more numbers than the fan version (same moment) | **90 %** of 42 pairs | ≥ 90 % | ✅ |
| Fan text is plain (no jargon, ≤ 1 statistic; scores and minutes don't count) | **91 %** | — | ✅ |
| Groundedness (Azure AI Evaluation, 1–5) | **4.85** (98 % pass) | ≥ 4 | ✅ |
| Relevance (1–5) | **4.24** | — | ✅ |
| Coherence (1–5) | **3.98** | — | — |
| Fluency (1–5) | **3.35** | — | see notes |
| **Explains *why*, not just *what*** (custom rubric, 1–5) | **3.76** | ≥ 4 | ❌ |

Numbers per 100 characters: fans 2.0, analysts 3.4. Foundry run:
[Evaluations tab](https://ai.azure.com/resource/build/evaluation/fd26e4b4-3886-43ba-9b61-b0db2e83f180?wsid=/subscriptions/0931ac23-c5a6-489e-9082-0a3a4b1e504b/resourceGroups/rg-darling6-3123/providers/Microsoft.CognitiveServices/accounts/premieranalytics-resource/projects/premieranalytics&tid=9c9bcd11-977a-4e9c-a9a0-bc734090164a).

### "Explains why" by moment type

| Moment | Score | n |
|---|---|---|
| Half-time | 4.83 | 12 |
| Full-time | 4.60 | 10 |
| Goal | 4.21 | 24 |
| Big chance / rocket shot / red card | 4.00 | 28 |
| Momentum shift | 3.42 | 52 |
| Pressure spell | 3.36 | 42 |
| Woodwork | 3.14 | 7 |

Event moments clear the bar; **trend moments (momentum, pressure) don't**: the text tends to describe the
spell ("3 shots in 10 minutes") rather than what it changes. By audience the scores are even
(English fan 3.78, analyst 3.64, Spanish fan 3.81, Arabic fan 3.80), so translation doesn't cost quality.

## What the evaluations changed

| Round | Change | Explains why | Groundedness |
|---|---|---|---|
| Baseline (1 match) | — | 3.09 | 4.74 |
| **Round 2 (kept)** | Every moment carries score and minute (trend moments both teams' shots); explainer told to lead with the consequence; fans get ≤ 1 statistic | **3.76** (same match: 3.09 → 3.64) | 4.85 |
| Round 3 (rejected) | Added "shots before the spell" facts and asked for before/after comparisons | 3.45 | 4.84 |

Round 3 was reverted: the model mostly listed the extra numbers instead of drawing a conclusion, and the one
place it did compare it wrote "double what they managed earlier" for 3 vs 3, a false comparison that neither
the Critic nor the judge caught. More facts invited exactly the error that is hardest to police.

The first run also exposed problems in the evaluation itself, fixed before round 2: the custom judge
shared a model client across worker threads (half its scores were silently missing), the evaluation
question was artificial (relevance scored 2.3 against it, 4.2 against a natural question), and the
fan-plainness metric counted minutes and scorelines as statistics.

## Limitations

- One run per configuration; judge scores vary run to run, so differences of ±0.2 are within noise.
- The SDK evaluators use `gpt-4.1-mini`, the same model that writes the live text; only the "explains why"
  rubric uses a different family.
- Fluency and coherence evaluators are designed for paragraphs and mark down 1–2 sentence graphics.
- The Critic checks numbers, names, clubs and goal context, not comparative words ("double", "best ever").

## Next step if time allows

Trend moments are the weak spot. The most promising fix is structural rather than more prompting: have the
Moment Scout compute the comparison itself ("first shot in 25 minutes", "3 shots after 0 in the previous 10")
as a single verified fact, so the AI only has to phrase it.
