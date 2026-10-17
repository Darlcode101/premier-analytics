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

**Status (2026-10-15, round 7 final check: 3 matches × 4 audiences, 142 AI overlays; details in docs/EVALS.md):** grounding 100 % after critic, groundedness 4.85 ✅; language 100 % ✅; analyst more numbers 94 %, fan text plain 91 % ✅; **explains why 4.22 ✅** (run-to-run noise ≈ ±0.2; every configuration since round 4 between 3.9 and 4.4); favourite-club bias not yet measured live (unit-tested only).

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

### Real-world context (CX-*)
| Test | Covers | Layer |
|---|---|---|
| Library schema: every entry has text, ≥1 source URL (https), title, retrieval date; every number in the text appears in the entry's numbers | CX-1 | pytest |
| Library build script with a fake search tool: entries created only from results that carry citations; uncited results dropped | CX-1 | pytest |
| Context agent (fake model): picks an entry relevant to the moment kind; rejects a card whose real-world number isn't in the entry or whose match number isn't in the facts; rejects real club/player names | CX-2, CX-4 | pytest |
| Ask box: cached answer reused for the same question; 16th search in a match refused; timeout returns a message; off-topic declined; answer without a source rejected | CX-3 | pytest |
| Desk shows a context card with a working source link beside a goal; ask box returns an answer with a link (scripted search) | CX-2, CX-3 | e2e |
| Context cards translated; links unchanged | CX-5 | pytest + e2e |
| With search down, desk otherwise unchanged and no context errors shown | CX-6 | e2e |

### Trend meaning (E-4, E-5)
| Test | Covers | Layer |
|---|---|---|
| Every trend moment has stakes, spell rank, previous-window shots, shots trend, opponent window shots and goals in the spell; each consistent with the numbers (3 seeds) | E-4 | pytest |
| "double"/"twice"/"three times" rejected unless two facts have that ratio; "strongest"/"first time" only with the matching spell fact; "first half" untouched; score wording must agree with the stakes ("trail 0-0") | E-5 | pytest |
| Missed shots carry "if it had gone in" and the score it would have made, consistent with the score (3 seeds); captions contradicting it rejected | E-6 | pytest |
| Goals carry run of play, shots it took and the wait for a goal, consistent with the match (3 seeds); contradicting captions rejected | E-7 | pytest |
| Football phrases that must pass: "doubles their lead", "would have made it 2-1", "cut the lead", "still ahead" for a consolation goal | E-5..E-7 | pytest |

### Pattern Analyst (PA-*)
| Test | Covers | Layer |
|---|---|---|
| Clubs have styles; favoured flank 42–62 % over a season, balanced clubs 25–43 % per channel; pressing sides win the ball higher; long-shot sides shoot from distance; every club has a playmaker; league realism still passes | PA-1 | pytest |
| Binomial tail; channels named from the attacker's view; counts equal the events; every pattern significant and carries its numbers | PA-2, PA-3 | pytest |
| Season profiles recover each club's configured styles (and not for balanced clubs); known styles come with today's numbers | PA-3b | pytest |
| Over 380 matches: strong flank styles found in ≥ 50 % of matches, balanced clubs flagged in ≤ 5 % | PA-9 | pytest |
| Wording for every pattern in EN/ES/AR uses only the pattern's numbers; fan lines have no numbers or jargon | PA-7, PA-8 | pytest |
| Agent notes checked: invented numbers and unknown ids fall back to plain wording; "remains/confirms" rejected when today contradicts the known style | PA-4 | pytest |
| Alerts need two checks in a row and fire once | PA-6 | pytest |
| AI off: desk and fan receive patterns, stats carry the shape, late joiners get the latest notes | PA-8 | pytest |
| Desk Patterns tab shows Today / Known-for notes and draws the selected one on the pitch; alerts appear among talking points; fan Stats shows plain lines without digits | PA-5..PA-7 | e2e |

### Fan app polish (F-*)
| Test | Covers | Layer |
|---|---|---|
| Trend throttle: same team within 15' dropped, other team allowed, after 15' allowed; fans get fewer trend cards than commentators over a full match | F-1 | pytest |
| Late-joining fan's backfill equals what a fan watching from kick-off saw | F-1 | pytest |
| Latest card's headline is above the tab bar on a 375×812 phone | F-2 | e2e |
| Fan recap written separately with plain instructions; decimals and jargon rejected for fans only; fans and commentators each receive their own | F-3 | pytest |
| After a settings change, backfill reuses a fitting AI version, never one written for another club or player | F-4 | pytest |
| Following a player shows the chip and the confirmation; clearing it removes them; cards about the player are marked | F-5 | e2e + unit |

### Fan cards list and "Why?" (F-6..F-8)
| Test | Covers | Layer |
|---|---|---|
| Bookings per team in match order, filtered by half | F-6 | unit |
| Fan Stats lists every card of the match, and only first-half ones on the 1st-half switch | F-6 | e2e |
| xG to odds; goal, missed chance, cards and pressure sentences; every kind gives 1-3 clean sentences in EN/ES/AR with no xG or %; no number the facts don't support | F-7 | unit |
| "Why?" opens sentences first; "See the numbers" reveals the facts | F-7, F-8 | e2e |

### Prep and storylines (PS-*)
| Test | Covers | Layer |
|---|---|---|
| Brief: earlier meetings, top scorer and playmaker per club, known styles, all from the simulated season | PS-1 | pytest |
| Seeds in EN/ES/AR only use their own numbers and name their players or clubs | PS-1 | pytest |
| AI suggestions: grounded ones kept, invented numbers fall back to the plain seed, unknown seeds dropped, 3-5 offered | PS-1 | pytest |
| Storylines from suggestions or typed; typed ones must name a player or club in the match; at most 4; remove | PS-2 | pytest |
| Which moments feed which storyline: anything involving the player (coming on included); club storylines only for moments that matter | PS-3 | pytest |
| Watcher: grounded updates kept; NONE, invented numbers or players give no AI update | PS-3 | pytest |
| Through the app with the AI off: brief and suggestions in hello, storylines shared and followed with updates, errors to the desk that asked, cues tagged with their storyline; fans get none of it | PS-1..PS-3 | pytest |
| Desk: before kick-off Prep comes first; add a suggestion and a typed storyline, an untrackable one is refused; kick off; updates appear for the storyline | PS-1..PS-3 | e2e |

### Ask about this match (AM-*)
| Test | Covers | Layer |
|---|---|---|
| Player and team stats "since minute X" equal counts from the raw events (first and second half); substitutes show when they came on and went off | AM-1 | pytest |
| Cards and substitutions tool: who, when, colour and the reason | AM-1 | pytest |
| The Ask Router sends real-world questions to the Researcher without calling the match tools; a router failure falls back to the analyst | AM-1 | pytest |
| A grounded answer carries its evidence (one line per distinct tool call) and "as of" | AM-3 | pytest |
| Invented numbers or players: one retry told what was wrong, then the tool facts without a narrative | AM-2 | pytest |
| The analyst says when the data does not hold the answer | AM-3 | pytest |
| Structured output survives a model that answers twice | AM-2 | pytest |
| Through the app: match and real-world questions reach the right agent; without models the box says it is unavailable | AM-1 | pytest |
| Desk: a match question shows the answer, "From the match data, checked · as of …" and the tool calls under "How I know" | AM-3 | e2e |

### Producer (GP-*)
| Test | Covers | Layer |
|---|---|---|
| Each stoppage type puts the cue on air with its window; the next pass, shot or kick-off returns it to up next; throw-ins and corner kicks do not count as breaks | GP-2 | pytest |
| Window estimates are within ±35 % of the simulation's median stoppage length per type | GP-2 | pytest |
| Ranking: importance wins when equally fresh; a fresh medium moment beats an old big one; pattern alerts age more slowly; context and storyline boosts; used items never cued; stale items dropped | GP-1 | pytest |
| A cue is only published when it changes; each published cue names its source and reasons and is in the trace | GP-1, GP-3 | pytest |
| Through the app with the AI off: cues go on air at substitutions and goals; marking used over the WebSocket moves the cue and syncs a second desk; hello carries the cue and used set | GP-4, GP-6 | pytest |
| AI note: a grounded note is published (and translated); NONE gives no note; an invented number is dropped; a note for a cue that has moved on is dropped | GP-5 | pytest |
| On-air display lasts max(window / speed, 6 s) of real time | GP-2 | unit |
| Desk shows the On air card with its source during a live match; Used moves it on | GP-1, GP-4 | e2e |

### Card reasons (F-6a, F-6b) and known styles (PA-3c)
| Test | Covers | Layer |
|---|---|---|
| Every card has a reason fitting its colour; foul cards directly follow that player's foul and name the fouled player; time-wasting only by a side ahead in the second half | F-6b | pytest |
| Over a simulated season: dissent 10-19 %, time-wasting 4-12 %, handball 2-8 % of bookings; late tackles the most common foul; yellows per team still 2.04 ± 0.3 | F-6b | pytest |
| Card incidents carry the reason and fouled player | F-6b | pytest |
| Reason wording for every reason in EN/ES/AR, with and without the fouled player; second yellows say so | F-6a | unit |
| Tapping › on a card in fan Stats shows its reason | F-6a | e2e |
| Known styles: configured flanks found, balanced clubs never get a flank, top long-shot and pressing clubs found, over a pooled four-season history; binomial test exact at season scale | PA-3c | pytest |

### Substitution cards (SB-*)
| Test | Covers | Layer |
|---|---|---|
| Card numbers equal the engine's player line at the moment of the change; minutes played counts from kick-off or from coming on; booked flag; subs used; score and minute | SB-1 | pytest |
| Change type: same line like-for-like, defender off striker on more attacking, and the reverse more defensive | SB-2 | pytest |
| Changes at the same stoppage group into one card; a later one starts a new card | SB-3 | unit |
| Fan lines in EN/ES/AR: no xG, no %, no template braces; numbers only from the card; goals mentioned when scored | SB-4 | pytest |
| Fan feed shows a substitution card; the card is marked when the followed player is involved | SB-4, SB-5 | e2e |
| AI off: every sub incident carries a card; late joiner's hello has the same cards | SB-6 | pytest |
| Overlay substitution body carries the key stat in every language, built only from moment facts | SB-7 | pytest |
| Desk shows the card on a substitution, dismiss hides it, clicking the timeline entry reopens it | SB-1, SB-3 | e2e |

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
