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
| **W7 World** | EM-060 tiered tools · EM-061 building state · EM-062 collective projects · EM-063 ad-hoc spawn · EM-068 caching | unblocked → next |
| **W8 Chaos** | EM-064 cat & dog · EM-065 Animal Chaos Feed | blocked on W7 |

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

W7–W8 extend `world-model.md` + config — authored at each gate.

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
