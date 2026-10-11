# Evaluations (A-8)

How good is the AI text that reaches the screen? We play **3 fixed matches** (seeds 42, 9, 7) through the
real pipeline on Microsoft Foundry for **4 audiences** (English fan, English analyst, Spanish fan, Arabic
fan), keep every published AI overlay with the facts it was given, and score it two ways:

- **Deterministic checks** that need no model.
- **AI judges**: the Azure AI Evaluation SDK's groundedness, relevance, coherence and fluency evaluators
  (`gpt-4.1-mini`), plus a custom **"explains why"** rubric judged by a different model family
  (`gpt-5-mini`) to limit self-grading. Runs are logged to the Foundry project's **Evaluations** tab.

Reproduce: `python scripts/run_evals.py` (≈ 15 min, under $1). Raw rows: `evals/results.json`.

## Results (final configuration, round 4, 151 AI overlays)

| Metric | Result | Pass bar (TEST_PLAN §6) | |
|---|---|---|---|
| Critic re-check of published text (numbers, names, goal context, comparisons) | **100 %** | 100 % | ✅ |
| Output in the requested language (en / es / ar) | **100 %** | 100 % | ✅ |
| Within on-screen length limits | **100 %** | 100 % | ✅ |
| Analyst version carries more numbers than the fan version (same moment) | **97 %** of 34 pairs | ≥ 90 % | ✅ |
| Fan text is plain (no jargon, ≤ 1 statistic; scores and minutes don't count) | **97 %** | — | ✅ |
| Groundedness (Azure AI Evaluation, 1–5) | **4.83** (98 % pass) | ≥ 4 | ✅ |
| Relevance (1–5) | **4.23** | — | ✅ |
| Coherence (1–5) | **3.99** | — | — |
| Fluency (1–5) | **3.28** | — | see notes |
| **Explains *why*, not just *what*** (custom rubric, 1–5) | **3.92** | ≥ 4 | ≈ (momentum and pressure now ≥ 4) |

Fewer overlays than round 2 (151 vs 175) because fans now get at most one trend card per team every 15 minutes
(F-1). Numbers per 100 characters: fans 1.8, analysts 3.1. Foundry run:
[Evaluations tab](https://ai.azure.com/resource/build/evaluation/81858da4-9b4b-4ac9-a650-203b2a6a1be8?wsid=/subscriptions/0931ac23-c5a6-489e-9082-0a3a4b1e504b/resourceGroups/rg-darling6-3123/providers/Microsoft.CognitiveServices/accounts/premieranalytics-resource/projects/premieranalytics&tid=9c9bcd11-977a-4e9c-a9a0-bc734090164a).

### "Explains why" by moment type

| Moment | Round 2 | Round 4 | n (round 4) |
|---|---|---|---|
| Momentum shift | 3.42 | **4.14** | 50 |
| Pressure spell | 3.36 | **3.94** | 17 |
| Goal | 4.21 | 3.79 | 24 |
| Big chance | 4.00 | 4.00 | 20 |
| Half-time | 4.83 | 3.83 | 12 |
| Full-time | 4.60 | 4.50 | 12 |
| Woodwork | 3.14 | 2.88 | 8 |

**Re-scored together** (the same judge run over both rounds' captions, to separate real change from judge noise):
momentum and pressure moments **3.27 → 4.04**, all other moments 3.89 → 3.77, overall 3.55 → 3.89. The gain on
trend moments is the same under both scorings; the other moments move within noise (goals 3.83 → 4.00 when
re-scored, the opposite direction to the first scoring). Half-time explanations are shared by all four audiences,
so its 12 rows are only 3 distinct texts; one weak one ("the goalkeeper is keeping them out", not in the facts)
pulls it down.

## What the evaluations changed

| Round | Change | Explains why | Groundedness |
|---|---|---|---|
| Baseline (1 match) | — | 3.09 | 4.74 |
| **Round 2 (kept)** | Every moment carries score and minute (trend moments both teams' shots); explainer told to lead with the consequence; fans get ≤ 1 statistic | **3.76** (same match: 3.09 → 3.64) | 4.85 |
| Round 3 (rejected) | Added "shots before the spell" facts and asked for before/after comparisons | 3.45 | 4.84 |
| **Round 4 (kept)** | The Moment Scout computes each spell's meaning as facts (what it means for the score, how it ranks, shots up or down on the previous 10 minutes, opponent shut out, no goal yet); the Critic rejects "double"/"three times" unless two facts have that ratio, and "strongest"/"first time" unless the spell fact says so | **3.92** (trend moments 3.39 → 4.09) | 4.83 |

Round 3 was reverted: the model mostly listed the extra numbers instead of drawing a conclusion, and the one
place it did compare it wrote "double what they managed earlier" for 3 vs 3, a false comparison that neither
the Critic nor the judge caught. More facts invited exactly the error that is hardest to police. Round 4 fixed
both halves of that: the conclusions are computed rather than left to the model, and comparison words are now
checked against the facts.

The first run also exposed problems in the evaluation itself, fixed before round 2: the custom judge
shared a model client across worker threads (half its scores were silently missing), the evaluation
question was artificial (relevance scored 2.3 against it, 4.2 against a natural question), and the
fan-plainness metric counted minutes and scorelines as statistics.

## Limitations

- One run per configuration; judge scores vary run to run, so differences of ±0.2 are within noise.
- The SDK evaluators use `gpt-4.1-mini`, the same model that writes the live text; only the "explains why"
  rubric uses a different family.
- Fluency and coherence evaluators are designed for paragraphs and mark down 1–2 sentence graphics.
- The Critic checks ratio words and spell superlatives (round 4), but not every comparative ("best ever", "rarely").

## Next step if time allows

Woodwork (2.9) is now the weakest moment type: like trend moments before round 4, its facts say what happened
but not what it means. The same approach (a computed "what it means" fact, e.g. still level / would have
equalised) should carry over.
