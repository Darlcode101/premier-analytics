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

### 3.5 Render (Stage 4)
| ID | P | Requirement |
|---|---|---|
| R-1 | M | Overlay output is **machine-readable JSON** with a published schema: type, match-clock in/out timestamps, priority, text, data payload |
| R-2 | M | **Two surfaces for one live match** (replaces the single pitch view): **Fan app** (phone-first, fan audience) and **Commentator desk** (laptop, analyst audience). No pitch drawing: ball location is shown as one of **9 zones** (defensive/middle/final third × left/centre/right), described from the possessing team's point of view |
| R-7 | M | **Fan app**: Premier League app-family look (deep purple, neon accents, match-centre header, card timeline, bottom tab bar). Screen colour **washes to the team in possession** and changes on every turnover. Tabs: Live (zones + moments), Stats, Recap, Me (language, club, followed player). "Fictional league · synthetic data" shown. No PL logo, wordmark or proprietary font |
| R-8 | M | **Moment animations** in the fan app: goal takeover in the scorer's club colour (score flip, scorer), red-card flash, big-chance/woodwork near-miss, momentum-swing colour sweep, half-time/full-time whistle with the recap card. Each fires once per moment; respects reduced-motion |
| R-9 | M | **Commentator desk**: analyst talking points (AI explanations with evidence), "on air" broadcast overlay preview, zone map, momentum chart, full stats, agent trace, recaps; language selectable |
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
