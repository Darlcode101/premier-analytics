# Evaluations (A-8)

> The "fan" audience below is the plain wording now used by the broadcast overlay; the separate fan app was retired on 18 Oct (REQUIREMENTS §3.18). The "analyst" audience is the commentator desk.

How good is the AI text that reaches the screen? We play **3 fixed matches** (seeds 42, 9, 7) through the
real pipeline on Microsoft Foundry for **4 audiences** (English fan, English analyst, Spanish fan, Arabic
fan), keep every published AI overlay with the facts it was given, and score it two ways:

- **Deterministic checks** that need no model.
- **AI judges**: the Azure AI Evaluation SDK's groundedness, relevance, coherence and fluency evaluators
  (`gpt-4.1-mini`), plus a custom **"explains why"** rubric judged by a different model family
  (`gpt-5-mini`) to limit self-grading. Runs are logged to the Foundry project's **Evaluations** tab.

Reproduce: `python scripts/run_evals.py` (≈ 15 min, under $1). Raw rows: `evals/results.json`.

## Results (final check of the submitted version, round 7, 142 AI overlays, 15 Oct)

| Metric | Result | Pass bar (TEST_PLAN §6) | |
|---|---|---|---|
| Critic re-check of published text (numbers, names, goal context, comparisons) | **100 %** | 100 % | ✅ |
| Output in the requested language (en / es / ar) | **100 %** | 100 % | ✅ |
| Within on-screen length limits | **100 %** | 100 % | ✅ |
| Analyst version carries more numbers than the fan version (same moment) | **94 %** of 34 pairs | ≥ 90 % | ✅ |
| Fan text is plain (no jargon, ≤ 1 statistic; scores and minutes don't count) | **91 %** | — | ✅ |
| Groundedness (Azure AI Evaluation, 1–5) | **4.85** | ≥ 4 | ✅ |
| Relevance (1–5) | **4.52** | — | ✅ |
| **Explains *why*, not just *what*** (custom rubric, 1–5) | **4.22** | ≥ 4 | ✅ (see noise) |

Round 7 has no AI changes since round 6. The generator did change (substitutes stay on, every card has a reason,
dissent and time-wasting), so the same seeds now play different matches with a different mix of moments: a check of
the version being submitted rather than a like-for-like comparison. Round 6 rows are kept in `evals/*_round6.json`.

Foundry run: [Evaluations tab](https://ai.azure.com/resource/build/evaluation/3628df41-59f8-4404-a33c-783a6f8a6c57?wsid=/subscriptions/0931ac23-c5a6-489e-9082-0a3a4b1e504b/resourceGroups/rg-darling6-3123/providers/Microsoft.CognitiveServices/accounts/premieranalytics-resource/projects/premieranalytics&tid=9c9bcd11-977a-4e9c-a9a0-bc734090164a).

**Noise.** Two runs of the same prompts and facts (round 6 with the strict and the corrected Critic) scored 4.37
and 4.07, and single moment types moved by up to ±0.6 between them (some are one explanation shared by four
audiences). Read differences under about 0.2 overall as noise. Every configuration from round 4 on lies between
3.9 and 4.4, including round 7 (4.22).

### "Explains why" by moment type (one judge run over all three, so directly comparable)

| Moment | Round 5 | Round 6, strict Critic | Round 6, final | Round 7 (own judge run, different matches) |
|---|---|---|---|---|
| Momentum shift | 4.26 | 4.11 | 4.08 | 4.24 |
| Pressure spell | 3.76 | 4.19 | 3.82 | 4.31 |
| Goal | 3.79 | 4.52 | **4.03** | 4.29 |
| Big chance | 4.15 | 4.58 | 3.95 | 4.21 |
| Half-time | 4.67 | 4.25 | 4.08 | 4.08 |
| Full-time | 4.42 | 4.50 | 4.25 | 3.92 |
| Woodwork | 5.00 | 5.00 | 4.00 | 4.08 |
| Long-range strike | 5.00 | 4.50 | 3.25 | 4.00 |
| Brace / hat-trick | — | — | — | 5.00 (4 captions) |
| **All** | 4.20 | 4.37 | 4.03 | **4.22** |

**A stricter checker is not better captions.** Round 6 first ran with three over-strict Critic rules, found by
replaying the matches and counting rejection reasons: "doubles their lead" (football for 2-0) treated as a ratio
claim, "would have made it 2-1" rejected because that score wasn't a fact, and "cut the lead" rejected for a
consolation goal. That run scored higher (4.37) because the false rejections forced rewrites or held captions
back, so fewer, cleaner captions were scored (142 against 154). The rules were corrected (with tests for each
phrase) and the corrected run is the one reported. What carried over between the two runs is the goal gain
(3.79 → 4.0–4.5).

## What the evaluations changed

| Round | Change | Explains why | Groundedness |
|---|---|---|---|
| Baseline (1 match) | — | 3.09 | 4.74 |
| **Round 2 (kept)** | Every moment carries score and minute (trend moments both teams' shots); explainer told to lead with the consequence; fans get ≤ 1 statistic | **3.76** (same match: 3.09 → 3.64) | 4.85 |
| Round 3 (rejected) | Added "shots before the spell" facts and asked for before/after comparisons | 3.45 | 4.84 |
| Round 4 (superseded) | The Moment Scout computes each spell's meaning as facts (what it means for the score, how it ranks, shots up or down on the previous 10 minutes, opponent shut out, no goal yet); the Critic rejects "double"/"three times" unless two facts have that ratio, and "strongest"/"first time" unless the spell fact says so | **3.92** (trend moments 3.39 → 4.09) | 4.83 |
| Round 5 (superseded) | Missed chances carry what they would have meant ("would have opened the scoring / equalised / put them ahead …"), with captions that contradict it rejected; score wording checked against the spell's stakes ("trail 0-0") | **4.21** (missed chances 3.66 → 4.46) | 4.84 |
| **Round 6 (kept)** | Goals carry how they fit the game (run of play from both sides' xG, shots it took, how long the match waited) and captions contradicting the run of play are rejected; three over-strict Critic rules corrected | **4.07** (goals 3.79 → 4.03 re-scored) | 4.81 |
| **Round 7 (final check)** | No AI changes; re-run on the submitted version after the generator changes (different matches from the same seeds) | **4.22** | 4.85 |

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
- The Critic checks *which* players, clubs and numbers appear, not *who did what*. Round 7 found one such slip in
  142 captions: a blocked shot captioned as "Thackeray's block" when Thackeray was the shooter. Groundedness caught
  it (scored 2/5); the Critic did not. Two other low groundedness scores (a woodwork caption, English and Spanish)
  were mostly the judge's error: 3-2 to 4-2 is "doubling the lead" in football terms; the only flaw was giving the
  leading side's score first.

## Next step if time allows

Overall scores sit within run-to-run noise of each other (3.9–4.4), and the final configuration has been
re-checked (round 7). The one error type left is role confusion (shooter written as blocker or keeper); a Critic
rule tying shot-moment verbs to the moment's player would close it.
