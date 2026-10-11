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
| `test_realism.py` (380-match synthetic season) | D-4 | every metric within tolerance of the **real 2024/25 Premier League average**: goals, passes, completion, shots, outside-box share, conversion (inside/outside box), fouls, cards, home/draw/away split, club spread. Targets + sources: [docs/REALISM.md](docs/REALISM.md) |
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
- xG: 6 m central > 0.35; penalty spot (open play, no penalty kicks are generated) 0.15–0.45; 30 m shot < 0.06; decreases with distance and narrower angle (property test); headers and pressure lower it.
- xG calibration: over 200 generated matches, total xG within 15 % of total goals.
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

**Status (2026-10-11, 3 matches × 4 audiences, 175 AI overlays; details in docs/EVALS.md):** grounding 100 % after critic, groundedness 4.85 ✅; language 100 % ✅; analyst more numbers 90 %, fan text plain 91 % ✅ (moment selection differs by design via thresholds, covered by unit tests); explains why 3.76 ❌ (event moments ≥ 4, momentum/pressure ≈ 3.4); favourite-club bias not yet measured live (unit-tested only).

## 7. E2E tests (Playwright)
- Load app → pick match → start → first overlay within 5 s.
- Switch Analyst ↔ Fan mid-match → overlay style + content changes.
- Set favourite club, player-focus, language ES → UI + narrative in Spanish.
- Language AR → `dir="rtl"`, overlays mirror correctly, no clipped text.
- Two browser contexts with different profiles watch simultaneously (P-6).
- Kill LLM (env flag) → overlays continue via templates (N-3).
- Full-time → recap appears (R-3).

### Redesign (R-2, R-7..R-10)
- Zone mapping (unit): every coordinate maps to exactly one of 9 zones; described relative to the possessing team (home attacks right in half 1, left in half 2).
- Possession (unit): kickoff, possession change, pass and shot events set the team in possession; other events don't.
- Animations (unit): goal / red card / big chance / woodwork / momentum / HT / FT overlays queue one animation each per moment; AI upgrades of the same moment never re-trigger.
- Fan app (e2e): background colour equals the possessing club's colour and changes after a turnover; zone card names a zone; goal animation appears with the scorer's club colour; Me tab switches language (Arabic → RTL); "Fictional league" label visible; no horizontal scroll at 375 px.
- Commentator desk (e2e): talking points appear with evidence; on-air preview shows graphics; agent trace and stats visible; language switch works.
- Landing (e2e): starting a match shows fan and desk links and a QR code for the fan link.

### Commentator desk v2 (CD-*)
| Test | Covers | Layer |
|---|---|---|
| No celebration element, no possession wash, no favourite star on the desk across a full match with goals and a red card | CD-1, CD-3 | e2e |
| Theme tokens: graphite background, contrast ≥ 4.5:1 for text, tabular numerals on stat cells; no page scroll at 1280×720 and 1920×1080 | CD-2, N-7 | e2e |
| Header lists scorers with minutes per team and the clock shows stoppage time (`45+2'`) | CD-4 | unit + e2e |
| Line-up reducer: goal, assist, yellow, second yellow → red, substitution update the right player; yellow-carded players flagged | CD-5, CD-7 | unit |
| Formation order matches GK, defence, midfield, attack for both teams; bench listed after | CD-5 | unit |
| Server sends per-player live stats; values equal the engine's (passes, accuracy, shots, xG, …) | CD-6 | pytest |
| Timeline contains every goal, card and substitution in the event stream exactly once, newest first, with AI disabled | CD-8, CD-17 | unit + e2e (`PA_AI=off`) |
| Ticking a talking point marks it used and survives reload | CD-9 | unit + e2e |
| Last-10-minutes column equals the engine's window values | CD-11 | pytest + unit |
| Top performers ranking and ties | CD-13 | unit |
| Simulated season: double round robin (56 matches, 3–4 home games per half-season), table points = 3W + D, form = last five results in date order, player season goals equal goal events; deterministic | CD-14 | pytest |
| Arabic desk renders right-to-left with Eastern Arabic digits, line-ups mirrored | CD-17 | e2e |

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
