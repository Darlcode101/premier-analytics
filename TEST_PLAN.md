# Test Plan — v0.3 (2026-10-09)

Principle: **tests are written before implementation.** Each test references the requirement IDs it covers ([REQUIREMENTS.md](REQUIREMENTS.md)).
Anything deterministic is tested exactly; anything LLM-generated is tested by **properties and evals**, not exact strings.

## 1. Test layers

| Layer | Tooling | What | Runs |
|---|---|---|---|
| Unit | pytest | Generator, schema, stats, pass difficulty, xG, moment detection | every commit |
| Property | hypothesis | Generator invariants over many seeds | every commit (100 seeds), nightly (10k) |
| Golden | pytest + fixture files | Hand-built mini-matches with known expected stats + moments | every commit |
| Agent (offline) | pytest + **fake LLM** | Orchestration, handoffs, routing, failure recovery — no network | every commit |
| Contract | jsonschema | Event schema, overlay schema, MCP tool schemas | every commit |
| LLM eval | Foundry evaluations + custom checks | Groundedness, personalisation difference, language correctness | on demand + before freeze |
| E2E | Playwright | Browser: start match → overlays appear → toggle mode → change language | CI + against deployed URL |
| Perf | script | Latency p95, cost per match | before freeze, after deploy |
| Live smoke | scheduled GitHub Action | Hit the public URL during judging; alert if down | daily 27 Oct → 10 Nov |

## 2. Synthetic data tests (D-*)

| Test | Covers | Check |
|---|---|---|
| `test_same_seed_identical` | D-3 | two runs, seed 42 ⇒ identical bytes |
| `test_different_seed_differs` | D-3 | seeds 1 vs 2 differ |
| `test_events_schema_valid` | D-2, R-1 | every event validates against JSON schema |
| `test_events_time_ordered` | D-1 | clock monotonic non-decreasing; covers ≥ 90:00 |
| `test_coordinates_in_bounds` | D-2 | 0≤x≤105, 0≤y≤68 |
| `test_score_matches_goals` | D-5 | final score == count of goal events per team |
| `test_players_on_pitch_only` | D-5 | no event by a player before sub-on / after sub-off / after red card |
| `test_sub_limits` | D-5 | ≤ 5 subs per team (modern rule), ≤ 11 on pitch |
| `test_possession_coherent` | D-5 | a pass's next event is by the receiving team, or a possession change event exists |
| `prop_realistic_ranges` (≥1k seeds, on averages) | D-4 | passes/team 350–650; pass completion 70–90 %; shots/team 8–18; goals/match mean 2.4–3.2; fouls/team 8–15; yellows 1–3 |
| `test_storyline_present` | D-6 | ≥ 1 momentum swing detected in ≥ 80 % of seeds |
| `test_no_real_names` | RC-2 | club/player names not in a blocklist of real PL clubs/players |

## 3. Ingest tests (I-*)
- Replay speed: 10 min of match at 20× takes 30 s ± 5 %.
- Malformed event (missing field, bad type, x=200) → rejected, logged, next event still processed.
- Duplicate id → processed once. Out-of-order within 2 s window → reordered.

## 4. Interpret tests (T-*) — golden fixtures
Hand-written mini-matches (5–30 events) with hand-calculated answers:
- Possession % on a fixture with known touch times.
- Pass distance: (0,0)→(30,40) = 50.0 m.
- Pass difficulty: monotonic — longer / under pressure / line-breaking ⇒ higher; bounded [0,1].
- xG: penalty ≈ 0.76; 30 m shot < 0.05; xG decreases with distance and narrower angle (property test).
- Momentum: fixture with 10 min of one-way pressure ⇒ momentum shift moment emitted at the right minute.
- Moment detection: goal ⇒ moment severity ≥ 0.9; routine back-pass ⇒ no moment.
- Stats are incrementally correct: computing live event-by-event equals computing in batch at the end.

## 5. Agent tests (A-*, E-*, P-*) — offline with fake LLM
- Orchestration: a goal event flows Scout → Orchestrator → (fast path ‖ Explainer → Critic → Personaliser → Translator) → Validator → overlay; trace shows each hop in order.
- Shared state: every agent reads the same state version for a given event.
- **Failure recovery (A-5)**: fake LLM times out / returns garbage / 429s ⇒ retry ⇒ fallback model ⇒ template overlay; stream never stalls > 3 s.
- MCP tools: each tool returns schema-valid output; agent calls tools rather than inventing stats (fake LLM asserts tool called).
- Critic (A-6): explanation containing a fabricated number ⇒ rejected and regenerated.

### Two-path + validator tests (R-4, R-6, N-1)
- Goal event → fast overlay emitted with evidence IDs before any LLM call returns (fake LLM delayed 2 s).
- AI overlay with same ID arriving in time → replaces fast overlay; arriving after 8 s → dropped, fast overlay stays.
- Critic rejects AI overlay twice → fast overlay stays, no stall.
- Validator rejects: missing evidence IDs, invalid schema, out-time before in-time, stale.
- Scheduler: N+1 simultaneous overlays → lowest priority dropped/queued; high severity pre-empts; no two overlays occupy the same slot.
- Moment Scout: routine events suppressed (≤ ~1 overlay/min average in fan mode); goals never suppressed.

## 6. LLM eval tests (live model, fixed seed match)
| Check | Covers | Pass bar |
|---|---|---|
| **Numeric grounding**: extract every number/name from outputs; each must appear in supplied facts | E-2 | ≥ 98 % of outputs fully grounded; 100 % of overlays after critic |
| Foundry groundedness evaluator | E-2 | mean ≥ 4/5 |
| **Mode difference**: Analyst vs Fan for same event — different moment selection, readability (Flesch) gap, analyst contains more stat tokens | P-1 | all three hold on ≥ 90 % of events |
| Favourite club bias: fan-mode for club A vs B surfaces different moments / framing | P-2 | measurable on ≥ 80 % |
| Language: output language detected == requested (EN/ES/AR) | P-4 | 100 % |
| Explains *why* (contains causal reasoning, not just restating) — LLM-judge rubric | E-1 | mean ≥ 4/5 |

## 7. E2E tests (Playwright)
- Load app → pick match → start → first overlay within 5 s.
- Switch Analyst ↔ Fan mid-match → overlay style + content changes.
- Set favourite club, player-focus, language ES → UI + narrative in Spanish.
- Language AR → `dir="rtl"`, overlays mirror correctly, no clipped text.
- Two browser contexts with different profiles watch simultaneously (P-6).
- Kill LLM (env flag) → overlays continue via templates (N-3).
- Full-time → recap appears (R-3).

## 8. Non-functional
- Latency at 1× over a full match: fast path p95 ≤ 0.5 s, AI upgrade p95 ≤ 4 s (N-1).
- Cost per full match logged; projected judging cost < budget (N-2).
- `docker compose up` on clean machine → app works (N-4) — run in CI.
- Secret scan (gitleaks) in CI (N-6).
- axe-core accessibility check in Playwright (N-7).

## 9. Submission checklist (manual, signed off 26 Oct)
- [ ] Registered on aka.ms/insidethegame (RC)
- [ ] Repo public, README with setup + architecture diagram + test instructions (RC-3)
- [ ] Video < 2:00, public, royalty-free music, shows live product (RC-4)
- [ ] Pitch names Foundry / Agent Framework / Azure services (RC-5)
- [ ] Public URL works from a fresh incognito browser on another network (RC-6)
- [ ] Everything shown in video reproducible on public URL (RC-7)
- [ ] Live smoke check scheduled through 10 Nov (RC-6)
