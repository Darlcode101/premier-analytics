# Evaluations (A-8)

How good is the AI text that reaches the screen? We play **3 fixed matches** (seeds 42, 9, 7) through the
real pipeline on Microsoft Foundry for **4 audiences** (English fan, English analyst, Spanish fan, Arabic
fan), keep every published AI overlay with the facts it was given, and score it two ways:

- **Deterministic checks** that need no model.
- **AI judges**: the Azure AI Evaluation SDK's groundedness, relevance, coherence and fluency evaluators
  (`gpt-4.1-mini`), plus a custom **"explains why"** rubric judged by a different model family
  (`gpt-5-mini`) to limit self-grading. Runs are logged to the Foundry project's **Evaluations** tab.

Reproduce: `python scripts/run_evals.py` (≈ 15 min, under $1). Raw rows: `evals/results.json`.

## Results (final configuration, round 5, 147 AI overlays)

| Metric | Result | Pass bar (TEST_PLAN §6) | |
|---|---|---|---|
| Critic re-check of published text (numbers, names, goal context, comparisons) | **100 %** | 100 % | ✅ |
| Output in the requested language (en / es / ar) | **100 %** (see note) | 100 % | ✅ |
| Within on-screen length limits | **100 %** | 100 % | ✅ |
| Analyst version carries more numbers than the fan version (same moment) | **91 %** of 34 pairs | ≥ 90 % | ✅ |
| Fan text is plain (no jargon, ≤ 1 statistic; scores and minutes don't count) | **94 %** | — | ✅ |
| Groundedness (Azure AI Evaluation, 1–5) | **4.84** | ≥ 4 | ✅ |
| Relevance (1–5) | **4.29** | — | ✅ |
| **Explains *why*, not just *what*** (custom rubric, 1–5) | **4.21** | ≥ 4 | ✅ |

Language note: the first computation said 99.3 %. The one "wrong" caption was correct Spanish without accents
("Gol de Zielinski da a Kingsmere ventaja 3-1…"); our detector counted "a" as English and didn't know "de" or
"tras". The detector was fixed (with that sentence as a test) and all rounds re-checked: 100 % each.

Foundry run: [Evaluations tab](https://ai.azure.com/resource/build/evaluation/0ca943a6-9f76-479e-8a8d-1d25b05fc92f?wsid=/subscriptions/0931ac23-c5a6-489e-9082-0a3a4b1e504b/resourceGroups/rg-darling6-3123/providers/Microsoft.CognitiveServices/accounts/premieranalytics-resource/projects/premieranalytics&tid=9c9bcd11-977a-4e9c-a9a0-bc734090164a).

### "Explains why" by moment type

| Moment | Round 2 | Round 4 | Round 5 | n (round 5) |
|---|---|---|---|---|
| Momentum shift | 3.42 | 4.14 | **4.12** | 50 |
| Pressure spell | 3.36 | 3.94 | **4.06** | 17 |
| Goal | 4.21 | 3.79 | 3.92 | 24 |
| Big chance | 4.00 | 4.00 | **4.30** | 20 |
| Half-time | 4.83 | 3.83 | 4.50 | 12 |
| Full-time | 4.60 | 4.50 | 4.67 | 12 |
| Woodwork | 3.14 | 2.88 | **5.00** | 4 |
| Long-range strike | 4.00 | 3.50 | **4.75** | 4 |

**Re-scored together** (one judge run over both rounds' captions, to separate real change from judge noise):
round 2 → round 4: trend moments 3.27 → 4.04, others 3.89 → 3.77; round 4 → round 5: all 3.92 → **4.27**, missed
chances (big chance 3.9 → 4.6, woodwork 3.4 → 4.5, long-range 3.0 → 4.75). Goals stay just under 4 in every
scoring (3.8–4.0): the goal facts already carry their context, and the judge most often marks them down for
"mostly restating" the goal.

## What the evaluations changed

| Round | Change | Explains why | Groundedness |
|---|---|---|---|
| Baseline (1 match) | — | 3.09 | 4.74 |
| **Round 2 (kept)** | Every moment carries score and minute (trend moments both teams' shots); explainer told to lead with the consequence; fans get ≤ 1 statistic | **3.76** (same match: 3.09 → 3.64) | 4.85 |
| Round 3 (rejected) | Added "shots before the spell" facts and asked for before/after comparisons | 3.45 | 4.84 |
| Round 4 (superseded) | The Moment Scout computes each spell's meaning as facts (what it means for the score, how it ranks, shots up or down on the previous 10 minutes, opponent shut out, no goal yet); the Critic rejects "double"/"three times" unless two facts have that ratio, and "strongest"/"first time" unless the spell fact says so | **3.92** (trend moments 3.39 → 4.09) | 4.83 |
| **Round 5 (kept)** | Missed chances carry what they would have meant ("would have opened the scoring / equalised / put them ahead …"), with captions that contradict it rejected; score wording checked against the spell's stakes ("trail 0-0") | **4.21** (missed chances 3.66 → 4.46) | 4.84 |

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

Goals (3.8–4.0) are the one large group below 4: the judge marks them down for restating the goal. A computed
consequence fact like the other moment types have ("first goal of the match after 60 goalless minutes", "ends a
run of N shots without scoring") is the obvious next step.
