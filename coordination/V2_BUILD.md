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
| **W5 Foundations (gate)** | EM-053 `/inspector` annex + WebGL unmount · EM-054 event-log spine · EM-066 decision-trace output | contracts locked → implementing |
| **W6 Instrumentation** | EM-055 replay · EM-056 trace inspector · EM-057 governance history · EM-058 social graph · EM-059 AWI dashboard · EM-067 usage tracking | blocked on W5 gate |
| **W7 World** | EM-060 tiered tools · EM-061 building state · EM-062 collective projects · EM-063 ad-hoc spawn · EM-068 caching | blocked on W5/W6 |
| **W8 Chaos** | EM-064 cat & dog · EM-065 Animal Chaos Feed | blocked on W7 |

## Contracts (W5 gate — LOCKED)

- `event-log.md` v1.0.0 (NEW) — append-only spine, decision-trace chain, snapshots, read API.
- `frontend-inspector.md` v1.0.0 (NEW) — `/` 3D primary vs `/inspector` 2D annex, WebGL unmount.
- `db-schema.sql` v1.1.0 — events += sim_time/actor_type/turn_id; pragmas; snapshots populated.
- `action-protocol.schema.json` v1.1.0 — optional perceived_summary/memories_used/reasoning.
- `events.schema.json` v1.1.0 — turn_id/actor_type/sim_time + chain kinds; open-enum forward-compat.
- `README.md` (NEW) — domain rules, file ownership, per-agent notes.

W6–W8 extend `api.openapi.yaml`, `world-model.md`, `providers.md`, config — authored at each gate.

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

## Wave gate log

| Date | Wave | Result |
|---|---|---|
| 2026-06-08 | W5 contracts | 6 contracts authored/extended; JSON valid; framing corrected (3D primary) |
