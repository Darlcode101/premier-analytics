# Requirements — Microsoft × Premier League "Inside the Game" Hackathon

Status: **v0.4** (2026-10-09) · Owner: Alex (solo) · Target: **Best Multi-Agent System** + Grand Prize

Every requirement has an ID. Every ID must map to at least one test in [TEST_PLAN.md](TEST_PLAN.md).
Priority: **M** = must (disqualified / pipeline incomplete without it), **S** = should (scores points), **C** = could (only if ahead of schedule).

---

## 0. Key dates

| Date (PT) | UK | What |
|---|---|---|
| 2026-10-20 12:00 | 20:00 | Registration closes — **register early** |
| 2026-10-27 23:59 | 28 Oct 07:59 | Submission closes |
| 2026-10-27 → 11-10 | | Judging — live demo must stay up and free |

## 1. Problem statement (draft — refine together)

Broadcasters and fans get scorelines and raw stats, but not *why* a moment mattered, and everyone gets the same feed.
We build a multi-agent system that turns a live stream of synthetic match events into **explainable, personalised match intelligence**: on-screen overlays, live narrative, and automated recaps, different for an analyst vs a casual fan, in their language, centred on their club or player.

Product name: **Premier Analytics**. Fictional league/clubs/players only. No PL logo, lion, real club names or crests anywhere (incl. video).

## 2. Rule compliance (pass/fail gate — all **M**)

| ID | Requirement | Source |
|---|---|---|
| RC-1 | All code created after 2026-09-29; repo history shows this | §4.3 |
| RC-2 | Uses only synthetic data we generate; no real match data/footage, no real club/player names, no PL marks | §4.7, §4.4 |
| RC-3 | Public GitHub repo with README, setup steps, architecture, licence | §4.4 |
| RC-4 | Demo video < 2:00, public on YouTube/Vimeo, no copyrighted music/trademarks, shows the real running product | §4.4 |
| RC-5 | Pitch text: what, which Microsoft/Azure tech, problem solved | §4.4 |
| RC-6 | Public, free, working test link available until 2026-11-10 23:59 PT (with test instructions) | §4.8 |
| RC-7 | Product behaves exactly as shown in video ("runs consistently") | §4.3 |
| RC-8 | Uses Microsoft hero tech meaningfully: Microsoft Foundry models + Microsoft Agent Framework (min.); Azure hosting | §6.1 |
| RC-9 | All materials in English (multi-language output is a feature, not the submission language) | §4.9 |
| RC-10 | Open-source deps used within their licences | §4.11 |

## 3. Functional requirements

### 3.1 Synthetic data (Stage 0 — scores under "Technological Implementation: optimised synthetic data creation")
| ID | P | Requirement |
|---|---|---|
| D-1 | M | Generator produces a full 90-min (+stoppage) match as a time-ordered event stream: pass, shot, tackle, interception, possession change, pressure, foul, card, sub, goal, kickoff/half/full-time, plus match metadata (teams, line-ups, venue, weather) |
| D-2 | M | Events carry: id, match clock (ms), type, team, player, x/y start (+ end where relevant) on a 105×68 m pitch, outcome, and type-specific fields (e.g. shot speed) |
| D-3 | M | Deterministic: same seed ⇒ byte-identical match |
| D-4 | M | Football-realistic: a simulated season matches published real 2024/25 Premier League averages within stated tolerances ([docs/REALISM.md](docs/REALISM.md)). Aggregate published figures only; no third-party event data (StatsBomb licence rejected, see REALISM.md) |
| D-5 | M | Internally consistent: score equals goal events; players only act while on pitch; sent-off players never act again; possession sequences are coherent |
| D-6 | S | Matches have "storylines" (momentum swings, pressure spells, late winner) so there is something to explain |
| D-7 | S | Fictional league: ≥ 6 clubs, full squads with names, positions, attributes |
| D-8 | C | Player tracking samples (x/y at ~1–5 Hz) to support speed/distance |
| D-9 | M | Dataset + generator published in repo with a schema doc |
| D-10 | M | **Corners and penalties** (user, 10-12): explicit `corner` and `penalty` events, with the delivery and the resulting shot tagged `set_piece`. Calibrated to 2024/25 (Opta, The Analyst, mid-season figures): ≈ 10.8 corners per match, ≈ 3 % of corners leading to a goal, ≈ 0.23 penalties per match, ≈ 83 % scored. A penalty is worth ≈ 0.78 xG. Existing realism (goals, shots, results) still holds |

### 3.2 Ingest (Stage 1)
| ID | P | Requirement |
|---|---|---|
| I-1 | M | Replays a match as a live stream at configurable speed (1×, 5×, 20×, instant) |
| I-2 | M | Validates every event against the schema; malformed events are rejected + logged, stream continues |
| I-3 | S | Handles duplicate and out-of-order events (dedupe by id, reorder within a window) |
| I-4 | S | Ingest via an Azure event service (Event Hubs / Service Bus / Web PubSub) in the deployed version |

### 3.3 Interpret (Stage 2) — **deterministic code, not LLM**
| ID | P | Requirement |
|---|---|---|
| T-1 | M | Running match state: score, clock, possession %, shots (on target), passes (completed %), tackles, fouls, cards, per team and per player |
| T-2 | M | Pass quality: distance, success, **difficulty rating 0–1** (from distance, pressure, progression, line-breaking) |
| T-3 | M | Shot metrics: speed, distance, angle, **xG** |
| T-4 | S | Rolling windows (last 5/10/15 min): momentum, field tilt, pressure intensity (PPDA-like), tempo/game rhythm |
| T-5 | M | **Key-moment detection**: goals, big chances, momentum shifts, pressure spells, player milestones, threshold triggers (e.g. sprint > X km/h if D-8) — each with a severity score |
| T-6 | S | "Control vs chaos" index (possession stability vs turnover rate) |

### 3.4 Explain (Stage 3)
| ID | P | Requirement |
|---|---|---|
| E-1 | M | For every key moment, produce an explanation of **why it matters**, citing the stats that support it |
| E-2 | M | **Grounded**: every number/player/team in an explanation exists in the facts supplied to the agent (no hallucinated stats) |
| E-3 | S | Each explanation carries its evidence (list of fact IDs) so the UI can show "why we think this" |
| E-4 | M | **Trend moments come with their meaning** (momentum and pressure scored 3.4 for "explains why"; target ≥ 4): the Moment Scout computes the conclusions as facts, so the AI only phrases them: what the spell means for the score (looking for an opener, chasing an equaliser, protecting a lead…), where it ranks (first spell on top, strongest so far, back on top), how it compares with the previous 10 minutes (shots up, down or the same), whether the opponent has been shut out, and that it hasn't produced a goal yet |
| E-5 | M | **Comparisons are checked**: "double", "twice", "three times" and similar are rejected unless two facts in the moment support that ratio; "strongest/best spell" and "first time on top" only when the spell fact says so |
| E-6 | M | **Missed chances come with their meaning** (woodwork scored 2.9): shots that didn't go in (big chances, woodwork, saves, long-range strikes) carry what they would have meant ("would have opened the scoring", "would have equalised", "would have put them ahead", "would have pulled one back", "would have extended the lead"), computed from the score; captions that contradict it are rejected |
| E-7 | S | **Goals come with how they fit the game** (goals scored 3.8–4.0, marked down for restating): whether the goal rewards the scoring side's pressure, came against the run of play, or arrived in an even game (from both sides' xG), how many shots it took since their last goal, and how long the match had waited for a goal; captions that contradict the run of play are rejected |
| E-8 | M | **Nothing meaningless early on** (user, 10-12): before 15' no judgements about how the match is going ("tight", "scoreless", "deadlock", "cagey", "still 0-0"); before 20' no comparison with "the 10 minutes before" (there aren't two full windows yet); fans never get "final third" (obvious and jargon) |

### 3.5 Render (Stage 4)
| ID | P | Requirement |
|---|---|---|
| R-1 | M | Overlay output is **machine-readable JSON** with a published schema: type, match-clock in/out timestamps, priority, text, data payload |
| R-2 | M | **Two surfaces for one live match** (replaces the single pitch view): **Fan app** (phone-first, fan audience) and **Commentator desk** (laptop, analyst audience). No pitch drawing: ball location is shown as one of **9 zones** (defensive/middle/final third × left/centre/right), described from the possessing team's point of view |
| R-7 | M | **Fan app**: Premier League app-family look (deep purple, neon accents, match-centre header, card timeline, bottom tab bar). Possession is shown **low-key, as other sports apps do**: the header colour stays fixed; a small ball marker sits beside the club with the ball and moves on every turnover, and the possession line's dot takes that club's kit colour (the mini pitch keeps its local glow). Tabs: Live (zones + moments), Stats, Recap, Me (language, club, followed player). "Fictional league · synthetic data" shown. No PL logo, wordmark or proprietary font |
| R-8 | M | **Moment animations** in the fan app: goal takeover in the scorer's club colour (score flip, scorer), red-card flash, big-chance/woodwork near-miss, momentum-swing colour sweep, half-time/full-time whistle with the recap card. Each fires once per moment; respects reduced-motion |
| R-9 | M | *(superseded by §3.9)* **Commentator desk**: analyst talking points (AI explanations with evidence), "on air" broadcast overlay preview, zone map, momentum chart, full stats, agent trace, recaps; language selectable |
| R-10 | S | Landing page starts a match and links both surfaces, with a QR code to open the fan app on a phone |
| R-3 | M | Automated recaps: half-time and full-time, as text |
| R-4 | M | **Overlay Validator + Scheduler**: every overlay (fast or AI) passes through it. Rejects overlays that fail schema, have no evidence IDs, or are stale; assigns match-clock in/out times and duration; enforces max N on screen, priority pre-emption, and no collisions |
| R-5 | C | Recap as audio (Azure AI Speech) |
| R-6 | M | **Two-path overlays**: a *fast path* emits a verified template overlay immediately from engine facts; an *AI path* (Explainer → Critic → Personaliser → Translator) produces an enriched overlay that **upgrades** the fast one in place (same overlay ID) if it arrives in time, otherwise is dropped |

### 3.6 Personalise (Stage 5)
| ID | P | Requirement |
|---|---|---|
| P-1 | M | **Analyst mode** vs **Fan mode**: measurably different output from the same events (density, vocabulary, which moments surface, stats shown) |
| P-2 | M | Favourite club: fan-mode framing and moment selection favour that club |
| P-3 | S | Player-focus mode: follow one player all match (their events, their stats, their story) |
| P-4 | M | Multi-language: **English, Spanish, Arabic** for narrative, overlays and recaps; Arabic renders right-to-left correctly |
| P-5 | C | "One metric I care about" mode |
| P-6 | M | Multiple viewers with different profiles can watch the same match at the same time |

### 3.7 Multi-agent system (category requirement)
Judges assess: distinct roles, shared state, effective handoffs, **failure recovery**, end-to-end outcome a single agent couldn't match.

| ID | P | Requirement |
|---|---|---|
| A-1 | M | Built with **Microsoft Agent Framework** on **Microsoft Foundry**-hosted models |
| A-2 | M | Distinct agents with single roles: **Moment Scout** (scores events, suppresses noise; deterministic score + LLM tie-break for borderline moments), **Orchestrator** (routes each selected moment to fast path and/or AI path, and to the right agents), **Explainer**, **Critic**, **Personaliser**, **Translator**, **Recap Producer** (runs at HT/FT off the live path). The stats engine is code exposed via MCP, not an agent |
| A-3 | M | Shared state: a match-state store all agents read; agents hand off through typed messages |
| A-4 | M | Stats are exposed to agents as tools via an **MCP server** (match-state MCP) |
| A-5 | M | Failure recovery: timeouts, retry, fallback model, and a deterministic template fallback so the overlay stream never stalls |
| A-6 | M | **Critic/fact-check agent** verifies E-2 before an AI overlay can upgrade a fast one; reject → one regenerate attempt → else keep the fast overlay |
| A-7 | S | Observability: trace every agent run (Foundry tracing / App Insights) and show the trace in the demo |
| A-8 | S | Foundry evaluations for groundedness/fluency on a fixed match |

### 3.8 Architecture

```
Synthetic Match Stream (timestamped passes, tackles, shots, positions)
        │
Deterministic Statistics Engine + MCP server (verified facts, each with an ID)
        │
Moment Scout (scores events, suppresses noise)
        │
Orchestrator (routes selected moments)
   ┌────┴─────────────────────────┐
Fast path                      AI path
verified templates,            Explainer → Critic → Personaliser → Translator
immediate overlay              (upgrades the fast overlay by ID)
   └────┬─────────────────────────┘
Overlay Validator + Scheduler (schema, timing, duration, evidence, priority)
        │
Live Broadcast / Fan Interface (overlays, Analyst mode, Fan mode)

Off the live path: Recap Producer at HT/FT
```

### 3.9 Commentator desk v2 (signed off 2026-10-11, replaces R-9)

Sources: broadcast practice (a commentator works from a *spotting board*: both line-ups in formation with
numbers, names, positions and notes, plus team stats, standings and form) and live data services built for
commentators (live dashboard of player/team data, xG and momentum, automatic talking points, alerts). What a
commentator needs live: who scored and when, who is on a booking, who has been subbed, what the numbers say
right now and over the last few minutes, and short verified talking points to use in a pause.

| ID | P | Requirement |
|---|---|---|
| CD-1 | M | **Neutral**: no favourite club, no celebrations or confetti, no possession colour wash. Home always left, away right, both treated identically. Club colour appears only as a small identifier (swatch or bar). Analyst wording only |
| CD-2 | M | **Professional broadcast look**: dark graphite theme (low glare in a booth), one accent for "live" and alerts, tabular numerals, no fan-app purple branding. Readable at arm's length (body ≥ 14 px, score ≥ 32 px). Main view fits 1280×720 to 1920×1080 without page scroll |
| CD-3 | M | Motion only to signal new information (brief highlight ≤ 1 s); respects reduced motion |
| CD-4 | M | **Match header**, always visible: score, clock with period and stoppage time, goalscorers with minutes under each team, red cards; venue, referee, kick-off and weather in a details strip |
| CD-5 | M | **Line-ups (spotting board)**: both XIs in formation order with shirt number, name, position, then the bench. Live markers per player: goals, assists, yellow, red, subbed off/on with minute. Players **on a yellow** stand out |
| CD-6 | S | Select a player to see their live match line: passes (accuracy), shots, xG, goals, assists, tackles won, interceptions, fouls, cards |
| CD-7 | M | Substitutions used per team (n of 5) |
| CD-8 | M | **Timeline**: every key event (goals with assist, cards, substitutions, big chances, woodwork) for both teams, one line each, newest first. Built from match data, never from AI |
| CD-9 | M | **Talking points** (AI, analyst mode) with evidence behind "Why?", marked AI or Instant, newest first. The commentator can tick a point as **used** (remembered in this browser) |
| CD-10 | S | Filter talking points by team; the highest-severity open point is highlighted |
| CD-11 | M | **Team stats**, full match and **last 10 minutes** side by side: goals, xG, shots, on target, big chances, possession, passes, pass accuracy, final-third passes, tackles won, interceptions, fouls, cards |
| CD-12 | M | Attack momentum chart with its explanations (existing) |
| CD-13 | S | Top performers: top 3 by xG, by passes completed, by defensive actions (tackles won + interceptions) |
| CD-14 | S | **Season context** from a simulated season (every club home and away, 56 matches): table position and points, last-5 form, each player's season goals and assists, top scorers. Labelled "simulated season" |
| CD-15 | M | On-air preview of the graphics currently on screen (smaller than today) |
| CD-16 | S | Agent trace and recaps on secondary tabs, out of the main view |
| CD-17 | M | EN / ES / AR with right-to-left Arabic; everything except talking points and recaps works with AI off or down |
| CD-18 | C | Keyboard shortcuts: switch panels, mark the newest point used |

Not included: pronunciation guides (fictional names), real head-to-head history, corners and offsides (not in
the event data; shown as unavailable rather than invented).

### 3.10 Real-world context for commentators (signed off 2026-10-11)

The clubs and players are fictional, so outside context is **comparison and explanation**, never news about them:
real Premier League benchmarks ("2.3 xG is well above the real PL average per team per match") and tactics
explainers (what PPDA or field tilt means, with a well-known example). Proven feasible: Foundry `gpt-4.1-mini`
with the web search tool returns sourced answers on this subscription (test 10-11).

| ID | P | Requirement |
|---|---|---|
| CX-1 | M | **Researcher agent** (Agent Framework + Foundry web search) builds a **context library** offline with a script: real PL benchmark facts (2024/25 averages and published distributions: goals, shots, xG, conversion, possession, cards, home wins, comebacks…) and tactics explainers (xG, field tilt, PPDA, momentum, pressing, low block…). Every entry stores its numbers, a source URL and title, and the retrieval date. Committed to the repo and reviewed by a person |
| CX-2 | M | **Automatic context cards** beside big moments on the desk: a **Context agent** picks at most one relevant library entry and writes one sentence linking the moment to it. Real-world numbers must come from that entry and match numbers from the moment's facts (checked by the Critic); the source link is shown. No live web call, so it is fast and costs nothing extra |
| CX-3 | M | **Ask box**: the commentator types a question, the Researcher searches the web live and answers in 1–3 sentences with at least one source link. Limited to football benchmarks and tactics (other topics politely declined). Labelled "From the web, not checked against match data". Answers cached; at most 15 searches per match; 15 s timeout with a clear message |
| CX-4 | M | Real and fictional never mix: real-world facts are only ever comparisons. Automatic cards use league-wide benchmarks only, with no real club or player names |
| CX-5 | M | Cards and answers in the desk's language (EN / ES / AR); sources stay as links |
| CX-6 | M | Everything else on the desk works if web search or the models are unavailable; context simply doesn't appear |
| CX-7 | S | Traced like the other agents (searches counted); an evaluation spot-checks that card numbers match their sources |
| CX-8 | S | Tactics explainers open from the stat labels on the desk (e.g. select "PPDA") |

### 3.11 Fan app polish (signed off 2026-10-11, from a full live run on a phone)

| ID | P | Requirement |
|---|---|---|
| F-1 | M | **Fewer trend cards for fans**: at most one momentum or pressure card per team every 15 match minutes, unless the other team takes over. Commentators still get every one. Late joiners see the same cards as viewers who were there |
| F-2 | M | **Story first**: the ball map is compact so the latest moment is visible on a phone without scrolling |
| F-3 | M | **Fan recap**: fans get their own recap in plain words (whole numbers, no xG or other analytics jargon); commentators keep the detailed one |
| F-4 | S | **Keep AI cards on a settings change**: a viewer who changes club, player or language mid-match keeps AI versions of earlier moments where one fits (same mode and language, and the other version wasn't written for a different club or player); otherwise the instant version |
| F-5 | M | **Following a player is visible**: when a player is followed, the match header says so (name), the settings confirm it, and cards about that player are marked |

### 3.12 Pattern Analyst (signed off 2026-10-11, fan card included)

Commentators look for how a team is playing: which flank they attack, where they win the ball, where their shots
come from, who makes them tick, where the opponent is hurting them. A pattern is only worth saying if it is real:
in one match, a 45/55 split is usually chance. Checked 10-11: in the simulation every club currently attacks
about a third each down the left, centre and right, so styles must exist before patterns can.

| ID | P | Requirement |
|---|---|---|
| PA-1 | M | **Club playing styles** in the simulation: each club has a favoured attacking flank (or central), a long-shot tendency and a pressing height (exists); the generator honours them. League realism (D-*, docs/REALISM.md) still passes |
| PA-2 | M | **Pattern detectors** (deterministic), per team, for the match so far and since half-time: attacking channel of final-third entries; where they win the ball back; where their shots come from (inside/outside the box, channel); who makes them tick (share of entries or shots through one player); where the opponent attacks them (their exposed flank); counter-attacks (shots within 15 s of winning the ball) |
| PA-3 | M | **Only real patterns**: a minimum number of actions and a significance test against chance (e.g. a third per channel) or against the club's own season style (from the simulated season); each pattern carries its numbers and the events behind it |
| PA-3b | M | **Known styles with today's numbers** (added 10-11 after measuring): one match is too little evidence for most tendencies (≈15 shots can't show a long-shot habit; a single-match detector finds it < 10 % of the time). So the panel also shows each club's distinctive styles from the simulated season (significant over the season and by a clear margin from the league: flank, long shots, high press, playmaker) next to today's numbers, worded as "known for", never as today's finding |
| PA-4 | M | **Pattern Analyst agent** picks the most useful 1–3 per team and writes one-line commentator notes ("Northgate keep going down the left: 9 of their 14 attacks"); numbers checked by the Critic; plain deterministic wording if the AI is off or fails |
| PA-5 | M | **Desk "Patterns" panel**: notes per team; selecting one shows it on the pitch (flank arrows with shares, ball-winning zones, shot origins as a heatmap) |
| PA-6 | S | **Pattern alerts**: a new pattern, or one that changes ("Harbourside switched to the right since half-time"; "unusually for them, Northgate aren't using the left today"), appears as a talking point |
| PA-7 | S | **Fan app**: one plain card on Stats, "How they're playing", e.g. "Northgate attack mostly down the left", with the mini pitch; no statistics jargon |
| PA-8 | M | EN / ES / AR; everything except the AI wording works with the AI off |
| PA-9 | S | **Detector check over the simulated season**: it finds each club's configured favoured flank in most matches, and reports a flank pattern for a balanced club in no more than 5 % of matches (false alarms) |

### 3.13 On-screen overlay (user request 10-12)

| ID | P | Requirement |
|---|---|---|
| OV-1 | M | A broadcast overlay page (`/overlay?match=…`) with a **transparent background**, usable as a browser source over video (e.g. OBS) |
| OV-2 | M | **Lower third**: the latest new graphic slides up at the bottom: moment type, headline, one line of body, team colour stripe; it upgrades in place when the AI version arrives, stays 7 s of real time (readable at any replay speed), then slides away; if several arrive meanwhile it skips to the newest |
| OV-3 | S | **Scorebug** top-left: club codes, score, clock with seconds and red stoppage time; `?bug=0` hides it. Language and fan/analyst wording from the URL |
| OV-4 | S | Opened from the landing page and from the desk's Production tab |

### 3.16 Known styles from more than one season (2026-10-14)

| ID | P | Requirement |
|---|---|---|
| PA-3c | M | Whether a club is **known for** a style is judged over this season plus the three before (pooled, same significance test and margin); the figures shown stay this season's. One 14-match season was too few: random variation could hide a real style or invent one |

### 3.15 Fan app: cards list and plain-words "Why?" (signed off 2026-10-14)

| ID | P | Requirement |
|---|---|---|
| F-6 | M | **Cards in Stats**: each team's bookings and sendings-off (card, player, minute) under the stat rows, following the full match / half switch (no "on a yellow" notes; user request 10-14) |
| F-6a | M | Each card has a **› on the right** that opens why it was shown, in plain words (EN/ES/AR): "Late tackle on Kai Greaves", "Fouled X to stop a counter-attack", "Handball", "Dissent towards the referee", "Time-wasting"; second yellows say so. The desk timeline and the fan "Why?" show the same reason |
| F-6b | M | **Reasons come from the simulation** (never AI): foul cards follow that player's foul and name the fouled player; dissent after a foul given against a side; time-wasting only by a side ahead in the second half (slow free kicks, slow walk off when substituted); straight reds: dangerous tackle, denying a clear chance (near goal), violent conduct, offensive language. Mix calibrated to real bookings (docs/REALISM.md) with total cards unchanged |
| F-7 | M | **"Why?" in plain words**: 1-3 short sentences built from the moment's facts in code (no AI), EN/ES/AR; chance quality as everyday odds ("about 1 time in 8"), what a goal does to the game, what a missed chance would have made the score, what a card means, what a spell on top looked like; no xG or percentages |
| F-8 | S | The raw facts stay one tap away behind "See the numbers" |

### 3.14 Substitution cards (signed off 2026-10-13)

Built only from match facts (no AI): instant, free, and nothing can be invented. Why a manager made a change (injury, tactics) is out of scope: we don't know it.

| ID | P | Requirement |
|---|---|---|
| SB-1 | M | **Desk card** when a substitution happens. Player off: minutes played, today's line (passes completed/attempted and %, shots, xG, goals, assists, tackles + interceptions, fouls), a "was on a yellow" flag, season goals and assists. Player on: number, position, season goals and assists. Context: subs used (e.g. 3 of 5), the score and minute of the change |
| SB-2 | M | **Change type** from the two players' positions: like-for-like, more attacking or more defensive |
| SB-3 | M | The desk card stays until dismissed or the next substitution; changes at the same stoppage share one card; clicking a substitution in the timeline reopens its card |
| SB-4 | M | **Fan card** in the live feed in plain words (no xG, no percentages): who came on for whom, one line on what the player going off did today, one on the player coming on's season; English, Spanish and Arabic |
| SB-5 | S | A fan **following** the player going off or coming on sees the card marked as their player |
| SB-6 | M | Works with the AI off; late joiners get the substitutions already made |
| SB-7 | S | The broadcast overlay's substitution graphic adds one key stat for the player going off (e.g. "1 goal, 34 passes") |

## 4. Non-functional requirements

| ID | P | Requirement |
|---|---|---|
| N-1 | M | Latency at 1× speed: **fast-path overlay ≤ 0.5 s p95** after the event; **AI upgrade ≤ 4 s p95 for English, ≤ 6 s p95 for translated audiences**; AI results older than 8 s are discarded |
| N-2 | M | Cost: total Azure spend ≤ **$100** credit. Azure budget alerts at $25/$50/$75. Target ≤ $0.50 LLM cost per full match; measured and documented |
| N-3 | M | Judge-proof: rate-limited, cached; demo works even if the LLM is down (pre-computed replay mode) |
| N-4 | M | One-command local run (`make dev` or `docker compose up`) |
| N-5 | S | Test coverage ≥ 80 % on data + interpret layers; CI on GitHub Actions |
| N-6 | S | No secrets in repo; managed identity / Key Vault in Azure |
| N-7 | S | Accessible UI: keyboard nav, contrast, readable overlay sizes |

## 5. Out of scope (explicitly)
- Real match data, real clubs/players, video ingestion / computer vision auto-eventing (§4.1 lists it, but out of scope solo in 18 days)
- User accounts / auth (profiles live in browser)
- Mobile app (responsive web is enough)

## 6. Proposed stack (to confirm)
- **Python 3.12**: generator, stats engine, agents (Agent Framework Python), FastAPI + WebSocket
- **Microsoft Foundry** (switzerlandnorth, Global Standard): tracing, evals, and two model deployments (student subscription = quota Tier 0, which only offers gpt-4.1-mini, gpt-5-mini, o4-mini):
  - `gpt-4.1-mini`: live agents (non-reasoning, so lowest latency). Tier 0 quota 200K TPM
  - `gpt-5-mini`: recaps + critic (better reasoning). Tier 0 quota 500K TPM
  - Fallback (A-5): each model is the other's fallback, then deterministic templates
  - Model names come from config, so if a quota request for `gpt-6-luna` is approved it's a config swap
- **MCP**: match-state MCP server (Python MCP SDK)
- **Frontend**: React + Vite (TypeScript), WebSocket client
- **Azure**: Container Apps (API + agents), Static Web Apps (UI), maybe Web PubSub for fan-out
- **Tests**: pytest, hypothesis (property tests on generator), Playwright (e2e)

## 7. Decisions log
| Date | Decision |
|---|---|
| 10-09 | Category: Best Multi-Agent System. Solo. Demo balances Analyst + Fan modes |
| 10-09 | Registered ✅. Azure: $100 credit |
| 10-09 | Languages: EN, ES, AR. ES = huge PL audience; AR = huge PL audience + proves RTL rendering |
| 10-09 | Frontend: React. Name: Premier Analytics |
| 10-09 | Azure region: subscription policy allows only italynorth, switzerlandnorth, denmarkeast, spaincentral, norwayeast. **All resources go in switzerlandnorth** (Foundry, Container Apps, etc.) |
| 10-09 | Models: gpt-6-luna blocked (Azure for Students = quota Tier 0). Using gpt-4.1-mini (live) + gpt-5-mini (recaps/critic), each the other's fallback. Estimated ~$0.35 per full match. Quota request for gpt-6-luna submitted later if needed |
| 10-09 | Architecture adopted (from Alex): stream → stats engine + MCP → Moment Scout → Orchestrator → fast path (templates) ‖ AI path (Explainer → Critic → Personaliser → Translator) → Overlay Validator + Scheduler → UI. Analyst agent removed (the engine + MCP does that job) |
| 10-09 | N-1 split after live runs: English upgrades p95 3.5 s, translated ~5.0 s (third sequential call). Kept a separate Translator agent (multi-agent roles) and relaxed the translated target to 6 s; fast overlay covers the gap |
| 10-10 | Hosting: Container Apps provider registration stuck in 'Registering' for 2h+ (reset didn't help). Deployed to **App Service B1 Linux** (switzerlandnorth, ~$13/mo from credit, WebSockets + Always On, 1 instance) at https://premier-analytics-0931.azurewebsites.net. Same image; move to Container Apps when the provider registers |
| 10-10 | UI redesign (Alex): phone fan app + laptop commentator desk, PL-app look "as close as possible" without logo/wordmark/font, 9-zone ball location instead of a pitch, possession colour wash, animations for goals, red cards, big chances, momentum, HT/FT |
| 10-11 | **Production moved to Azure Container Apps**: the CLI was blocked by a provider stuck in 'Registering', but the ARM API accepted the environment and app directly (`az rest`). Keyless via managed identity; verified 13 AI overlays, 0 errors. App Service kept as fallback for now |
| 10-11 | Container Apps runs in **Express** mode (Standard unavailable in switzerlandnorth for this subscription), with a **user-assigned identity** for Foundry and image pulls. URL https://premier-analytics.salmondune-d779c5b4.switzerlandnorth.azurecontainerapps.io |
| 10-11 | App Service fallback deleted (saves ~$13/month); Container Apps is the only production host |
| 10-11 | Removed the 'control vs chaos' indicator from the UI (Alex: doesn't read clearly); T-6 stays as an internal engine metric only |
| 10-11 | Arabic UI shows Eastern Arabic digits (٠-٩, ٫, ٪) at display time only; data, AI text and the Critic keep Western digits. AI tag shows just 'AI' |
| 10-11 | A-7 done: OpenTelemetry trace per AI moment (agent steps, critic verdicts, recaps, outcomes) exported to the Foundry project's Application Insights; verified live |
| 10-12 | Mini pitch: the coloured possession glow replaced by a plain football at the ball's position (user) |
| 10-12 | Ball movement (user: "prioritise fluidity"): the ball follows the events' real coordinates (passes travel passer → receiver over roughly the simulator's pass time at match speed; restarts snap), eased at 60 fps outside React, at most 1 s behind the live match; drawn solid on top of the pitch lines. Measured: 121 frames in 2 s, steps ≤ 2.9 m |
| 10-12 | Stats by half (user): Match · 1st half · 2nd half switch on the desk and in the fan app; first half frozen exactly at the half-time whistle, second half = match − first half (possession and pass accuracy recomputed for the half) |
| 10-12 | D-10 corners and penalties built and calibrated; open play re-tuned (shot rate, finishing, home advantage, long-shot style, press strength) using four-season averages rather than the fixed test season, after single-season tuning kept flipping borderline checks. Season-style significance relaxed to 0.005 (with the margin rule) because open-play shot samples per club are small. Penalty moment, set-piece facts on goals and chances, corners in the stats, penalties in the timeline |
| 10-12 | OV-1..OV-4 built: transparent /overlay page with scorebug and lower third (latest graphic for 7 s, skips to the newest). Pattern pitch arrows redrawn (user: "blobby"): fixed-length arrows that stop before the final third, the most-used flank solid, labels in pills |
| 10-11 | PA-4..PA-8 built: Pattern Analyst agent (notes checked by the Critic; plain wording in EN/ES/AR if the AI is off or a note fails); checks every 5 match minutes, notes every 10 and at half-time/full-time; alerts once a pattern holds at two checks; desk Patterns tab with flank arrows, ball-winning thirds and shot maps; fan "How they're playing" card. Live check (har v kin, seed 42): alerts at 61' (Harbourside down the left, 16 of 26), 76' (Kingsmere down the right), 81' (Zielinski 12 of 24). A note that called a playmaker "remains key" on 2 of 12 today led to a check: known styles that today's numbers contradict can't be worded as confirmed |
| 10-11 | PA-2/3 detectors tuned on 380 matches: flank at α 0.01 finds strong styles 56 % and flags balanced clubs 3.8 % (α 0.001: 37 % / 0.7 %; α 0.02: 66 % / 4.8 %). Other single-match tendencies are rarely detectable (press ≈ 19 %, long shots < 10 %), which led to PA-3b. The simulation gained a high press (pressing sides harass deep and force errors), a stronger long-shot style and a playmaker per club; realism re-checked (goals, results, xG calibration) after rebalancing |
| 10-11 | PA-1 club styles: favoured flank (har left 0.7, kin right 0.7, sto right 0.5, oak left 0.5, elm left 0.4; ngc/sil/iro balanced) and long-shot tendency. Tuned to realistic levels (favoured flank 44–57 % of entries over a season, like strongly one-sided real teams) after a first version gave 69 %. Finding: balanced clubs reach 51–54 % down one side in single matches (entries come in correlated chains), so the detector's test must be strict. Home advantage retuned 0.012 → 0.007 (home wins 42 % on two seasons vs 40.8 % real) after the styles reshuffled results |
| 10-11 | E-7 (evaluation round 6, kept): goals 3.79 → 4.03 (re-scored); explains why 4.07 overall. Replaying the matches and counting Critic rejection reasons found three over-strict rules ("doubles their lead", "would have made it 2-1", "cut the lead"), corrected with tests. The strict run scored 4.37 only because false rejections held captions back: a stricter checker is not better captions. Run-to-run noise ≈ ±0.2 overall |
| 10-11 | E-6 (evaluation round 5, kept): explains why **4.21** (bar 4 met); 3.92 → 4.27 when rounds 4 and 5 are re-scored together; missed chances 3.66 → 4.46. Language detector fixed (an accent-free Spanish caption was misread as English); all rounds 100 % |
| 10-11 | E-4/E-5 (evaluation round 4, kept): explains why 3.76 → 3.92; momentum and pressure 3.39 → 4.09 (3.27 → 4.04 when both rounds were re-scored by the same judge); other moments within noise; Critic 100 %, analyst more numbers 97 %, fan plain 97 %. Woodwork (2.9) is now the weakest type |
| 10-11 | Fan clock shows seconds (user): "mm:ss" ticking smoothly between events at match speed (never more than 10 s ahead of the data, never backwards); stoppage time as "45:00" or "90:00" plus a red "+m:ss"; HT at half-time |
| 10-11 | Fan pitch (user): just the pitch, centred, no attack arrow and no "Where's the ball" text; the zone sentence is kept as the pitch's accessible label. Scoreline centred in its box |
| 10-11 | Fan header restyled (user) after the Premier League match-centre layout: flat purple, no glow; minute directly above a white score box, plain (no green marker), stoppage time as a red "+n"; scorers with minutes under each team; light grey page with flat white cards |
| 10-11 | R-7 changed (user): no whole-header possession wash; a ball marker beside the team in possession instead, the scorebug convention in other sports apps |
| 10-11 | Fan polish (§3.11) checked live on a phone with real models: trend cards in a full match 10 → 5, latest moment above the fold, fan recap in whole numbers without xG, followed player marked on its cards |
| 10-11 | N-2: spend to date £0.66 (Cost Management, 1–11 Oct). The user confirms budget alerts are set up (not at subscription scope, so presumably on the billing account) |
| 10-11 | Live: the app identity needed *Foundry User* on the Foundry resource for web search (403 with OpenAI User only); granted with the user's approval, scoped to that resource. Seen live: a card applied the stoppage-time-goals benchmark to an 88th-minute goal ("late goals"), a misuse the number checks can't catch |
| 10-11 | Real-world context (§3.10) built. Library: 16 entries (7 benchmarks, 9 tactics explainers) from the Researcher's web search. Every number had to appear on a cited page; benchmarks also had to agree with the independently sourced figures in docs/REALISM.md and be full-season league figures. The checks rejected wrong figures the search returned (home wins 39 % and 43 %, conversion 8.5 %), partial-season and projected numbers, and sums the model calculated itself. Two calibration figures of ours were also rejected because the sources don't state them directly (we had derived them). **For the user to review:** big-chance conversion "30–37 %" and stoppage-time goals "96" (an earlier run said 93) |
| 10-11 | N-1 measured live (sto-iro seed 7, 50 AI captions): AI version arrives after the instant one at p95 3.1 s English fan, 4.3 s analyst, 4.0 s Spanish (targets 4 s / 6 s). Explainer ~1.5 s, Personaliser and Translator ~0.9 s each. Decided **not** to merge Personaliser and Translator: saves ~0.9 s only for translated viewers, who are already well inside 6 s, and would lose the name masking that stops names being transliterated. Simple moments (saves, cards, subs) were already template-only |
| 10-11 | Commentator desk v2 (§3.9) signed off: neutral dark graphite console (user chose dark over light), spotting-board line-ups, deterministic incident timeline, match vs last-10' stats, season context from a simulated 56-match season (user: include). Line-up names shown as initial + surname, as on spotting boards |
| 10-11 | A-8 evaluations (docs/EVALS.md): groundedness 4.85, relevance 4.24, critic/language/length 100%; 'explains why' 3.76 vs bar 4 (trend moments weak, event moments pass). Round 3 prompt change reverted after it scored worse |
| 10-09 | Effort: heavy this weekend (10–11 Oct), lower after, so the riskiest, core work goes first |

## 8. Milestones
Scope cut line: if behind on 17 Oct, drop all **C** items and S items D-8, I-4, T-6, P-5, A-8.

| By | Milestone |
|---|---|
| Fri 9 Oct | Requirements + test plan signed off; repo created; Azure Foundry project + model deployed; budget alerts set |
| **Sat 10 Oct** | Event schema + generator + stats engine + moment detection: tests written first, all green (no LLM) |
| **Sun 11 Oct** | Agents + MCP server + orchestration end-to-end locally with fake LLM, then real Foundry model; fallbacks working |
| Wed 14 Oct | React UI: live view, overlays, Analyst/Fan toggle |
| Sat 17 Oct | Personalisation + 3 languages + recaps; **scope cut decision** |
| Tue 20 Oct | Deployed on Azure, CI green, latency + cost measured |
| Sat 24 Oct | **Feature freeze**; evals, polish, README |
| Mon 26 Oct | Video recorded + uploaded; submission drafted |
| Tue 27 Oct | Submit, UK daytime, well before 07:59 UK on 28 Oct |
