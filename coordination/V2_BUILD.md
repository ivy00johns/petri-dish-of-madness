# V2 Expansion Build — orchestration status

**Branch:** `build/v2-expansion` · **Mode:** ultracode / Workflow · **Scope (user-confirmed):**
all four waves W5→W8 (EM-053–068), wave-gated. Source: `docs/research/deep-research-v2.md`
→ ledger `docs/REMAINING-WORK.md`.

**Steering note (user, 2026-06-08):** the **3D village is the primary experience**; the 2D
`/inspector` is an analysis annex (right tool for data-viz + frees the GPU during analysis),
NOT a demotion. W7/W8 world features render *in* the 3D village. Encoded in
`contracts/frontend-inspector.md §0` and the W5/W7/W8 plan text.

## Waves (each closes with a QE gate)

| Wave | Items | Status |
|---|---|---|
| **W5 Foundations (gate)** | EM-053 `/inspector` annex + WebGL unmount · EM-054 event-log spine · EM-066 decision-trace output | ✅ DONE — gate GREEN |
| **W6 Instrumentation** | EM-055 replay · EM-056 trace inspector · EM-057 governance history · EM-058 social graph · EM-059 AWI dashboard · EM-067 usage tracking | ✅ DONE — gate GREEN |
| **W7 World** | EM-060 tiered tools · EM-061 building state · EM-062 collective projects · EM-063 ad-hoc spawn · EM-068 caching | ✅ DONE — gate GREEN (after fix) |
| **W8 Chaos** | EM-064 cat & dog · EM-065 Animal Chaos Feed | unblocked → next (finale) |

## Contracts (W5 gate — LOCKED)

- `event-log.md` v1.0.0 (NEW) — append-only spine, decision-trace chain, snapshots, read API.
- `frontend-inspector.md` v1.0.0 (NEW) — `/` 3D primary vs `/inspector` 2D annex, WebGL unmount.
- `db-schema.sql` v1.1.0 — events += sim_time/actor_type/turn_id; pragmas; snapshots populated.
- `action-protocol.schema.json` v1.1.0 — optional perceived_summary/memories_used/reasoning.
- `events.schema.json` v1.1.0 — turn_id/actor_type/sim_time + chain kinds; open-enum forward-compat.
- `README.md` (NEW) — domain rules, file ownership, per-agent notes.

## Contracts (W6 — LOCKED)

- `api.openapi.yaml` v1.1.0 — 7 read endpoints over the §7 interface (events/turns/rules-history/
  relationships/snapshots/replay/analytics) + `EventRow` component.
- `providers.md` v1.1.0 — `last_usage` capture (EM-067) + per-attempt `llm_call` rows + cap policy.
- `frontend-inspector.md` §7 — W6 data contract: panels compute from client-side rolling history
  (work in mock + live), REST = deep replay; selectors/api/types/PanelProps; mock generator must
  emit chain + rule lifecycle + relationships + usage.

## Contracts (W7 — LOCKED)

- `world-model.md` v1.1.0 — §W7: **Building** entity = the collective-project pipeline (one
  lifecycle planned→under_construction→operational, +damaged/abandoned/destroyed); tiered tool
  catalog (reflex/llm + location/agreement gates); spawn modes (god/governance); decision cache.
  Buildings live in snapshot + event log — **no new tables**. Render in the 3D village.
- `action-protocol.schema.json` — +6 actions (propose_project/contribute_funds/build_step/repair/arson/take_offline).
- `events.schema.json` — +structure_state_changed/project_proposed/funded/built/building_operational/damaged/destroyed.
- `api.openapi.yaml` — POST /api/agents `mode` (god|governance) + GET /api/buildings.
- `providers.md` — EM-068 router decision cache (sha1(profile+messages), default on).
- `config/world.yaml` — world.buildings/spawn/cache defaults.

W8 extends config + a new Animal entity — authored at the W8 gate.

## File ownership (parallel-safe — see contracts/README.md)

persistence → `persistence/**` · backend → `engine,agents,api,run.py` · providers →
`providers/**` · frontend → `web/src/**`,`web/package.json` · qe → `backend/tests/**`,`*.test.*`.

## Skills manifest (orchestrator composition for this build)

- [x] `orchestrator` — driving (Workflow mode).
- [x] `contract-author` — W5 gate contracts authored.
- [ ] role-agents (general-purpose + role brief) — per wave via Workflow.
- [ ] `qe-agent` brief — mandatory gate each wave; produces `coordination/qa-report.json`.
- [ ] `frontend-design` + `ui-ux-pro-max` — W6 inspector panels (invoked inside frontend agents).
- [ ] `design-token-guard` — every UI wave gate (source-level, alongside tsc).
- [ ] `render-sanity` — outcome gate after UI waves (W6, final).
- [ ] `ux-review` — subjective pass after UI waves.
- [ ] `playwright` — E2E (route switch / WebGL unmount; inspector flows).
- [ ] `deployment-checklist` — final, if shipping.

## Live-run findings (fix at W6 gate)

- **Optional decision-trace fields can fail a turn (regression, mine).** Observed live: agents
  hit `schema error: '...' is too long` → idle fallback when a model echoes a long memory line
  into the EM-066 `memories_used` field (W5 set item maxLength 160; real memory lines run ~190+).
  Fix: optional trace fields (`perceived_summary`/`memories_used`/`reasoning`) must NEVER fail a
  turn — truncate/drop over-long values before validation, validate the ACTION separately. Touch
  runtime.py inline ACTION_SCHEMA + action-protocol.schema.json. **First task at W6 gate.**
- **Models hallucinate world features** (an "oak tree", a "community garden") and fail to act on
  them (`unknown place 'None'`). Not a bug — motivates W7 (collective projects + buildings let
  them actually build it). No fix; it's the design pull toward W7.
- Per-attempt `llm_call` rows confirmed emitting live (two `consults` rows on a retried turn). ✓

## Wave gate log (W7)

- **W7 verify BLOCKED → FIXED → GREEN** — the value of the adversarial gate. QE's `test_w7.py`
  (which the 97 existing tests couldn't catch — none exercised the new actions through the loop)
  + skeptics found a CRITICAL integration mismatch: `world-core` shipped a dict-returning
  `action_*` API (id string) while `runtime-api` dispatched against a `(ok,reason)` tuple + a
  Building object → **every** construction turn crashed end-to-end. Plus a HIGH: governance-spawn
  called the wrong method name (`propose_admit_agent` vs `enqueue_admit_agent`) → silent no-op.
  Root cause: my contract said "mirror the action_work pattern" (ambiguous). Fixed: contract
  clarified (locked the event-dict boundary in world-model §W7); a reconciliation agent rewrote
  the 6 dispatch branches (vote-style `_emit_world_result`, id string) + the governance call;
  the 2 strict-xfail pins promoted to real end-to-end loop assertions. Re-verified by orchestrator:
  135 passed / 0 failed / 0 xfail; the construction chain runs through `TickLoop._execute_turn`
  (operational@100, credits conserved, no parse_failure); governance-spawn creates a real rule.
  Skeptics on cache + frontend were NOT refuted (clean). qa-report.json updated with resolution.

- **W7 build gate PASS** — backend 97 (no regression w/ buildings/projects/cache integrated), `tsc -b`+`vite build` exit 0. 0 NEW token violations (Structure.tsx hex = idiomatic Three.js material, consistent w/ all world3d; ControlPanel `#c8ff00` = pre-existing v1 debt).
- **render-sanity PASS** (browser, mock) — 3D village renders buildings by lifecycle status (a garden built through construction→operational; "Village Oak Tree"), 1 WebGL ctx on `/`, real gov/economy events, no smells; `/inspector` 0 WebGL (clean unmount preserved from `/`), building markers surfaced. Evidence: docs/build-evidence/w7/.
- **Dev-console cleanup item (non-blocking):** 1 console error on `/` — `THREE.WebGLRenderer: Canvas has an existing context of a different type` = known R3F+StrictMode dev double-mount artifact; village renders fully, absent in prod build. Candidate fix: Canvas `key`/remove StrictMode churn.

## Wave gate log (W6)

- **W6 build gate PASS** — backend 79, `tsc -b`+`vite build` exit 0, design-token-guard clean (CSS vars + data-driven colors, 0 hardcoded hex). Bundle >500KB warning → lazy-load-inspector follow-up (not a blocker).
- **Live-run fix landed** — optional trace fields truncate-not-reject (verified: the exact "too long" case validates; structural args still strict; 79/79).
- **render-sanity PASS** (browser walk, mock mode) — all 5 panels render REAL data (decision-trace chain, governance lifecycle 10 proposed/6 active, social graph 5/5 agents 9 ties, 9-AWI w/ values + no composite score + model-vs-model); **0 WebGL contexts on /inspector** (3D truly unmounts); 0 console errors; no smell tokens. Evidence: docs/build-evidence/w6/.
- Minor cosmetic follow-ups: `@@` glyphs (missing icon chars) in trace memory rows; lazy-load inspector to shrink bundle.

## Wave gate log

| Date | Wave | Result |
|---|---|---|
| 2026-06-08 | W5 contracts | 6 contracts authored/extended; JSON valid; framing corrected (3D primary) |
| 2026-06-08 | W5 implement | 3 agents (persistence/backend/frontend), disjoint ownership, all `done` |
| 2026-06-08 | W5 wave gate | PASS — backend 63 tests, `tsc -b`+`vite build` clean, 0 new token violations (pre-existing Header status-color debt logged) |
| 2026-06-08 | W5 verify | GREEN — QE 79/79 (16 new event-log tests), conformance 5 / invariants 5 / security 4, replay-determinism asserted as real equality. Adversarial panel (5 skeptics): replay ✅, one-call-per-turn ✅, WebGL-unmount ✅, OTel-keys ✅, append-only ✅. 3 contract-consistency findings reconciled: opened events.schema `kind` (was closed enum), aligned event-log parse-failure language to uniform-chain reality, deferred per-attempt `llm_call` rows → EM-067/W6. |
