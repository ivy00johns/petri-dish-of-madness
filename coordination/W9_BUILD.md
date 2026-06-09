# W9 Build — "Make v2 true" (EM-069–074)

Branch: `build/w9-make-v2-true` · Source plan: `BUILD-PLAN.md` §Wave 9 + `docs/audit-2026-06-09.md`
Orchestrated 2026-06-09. Contracts bumped first: event-log v1.1.0, api.openapi 1.2.0,
frontend-inspector v1.1.0, events.schema x-known-kinds (+`agent_starving`, `world_extinct`, `usage_sampled`).

## File ownership (strict)

| Agent | Owns | Forbidden |
|---|---|---|
| backend-agent | `backend/**`, `config/**` | `web/**`, `README.md`, contracts |
| frontend-agent | `web/**` | `backend/**`, `README.md`, contracts |
| qe-agent (after gate) | `backend/tests/**`, `coordination/qa-report.json` | src except tests |
| orchestrator | `contracts/**`, `coordination/**`, `docs/**`, ledger | implementation |

## Work split

**backend-agent — EM-070 (backend), EM-071 (backend), EM-073:**
- B1 animal turn_id: animals get own uuid turn_id, never inherit agent's (event-log v1.1.0 §2)
- B2 reset() awaits cancelled tick task (try/except CancelledError; drop misused shield)
- B3 `ban_arson` added to valid_effects (world.py + runtime.py validator)
- B4 build_step validator accepts funded `planned` building (align with world auto-upgrade)
- B6 llm_call emitted exactly once per attempt (remove W5 final-attempt duplicate path)
- B7 /api/replay returns delta only (base.tick < tick <= T)
- B8 snapshots serialize round/turn-order/turn-index; snapshot-after-tick boundary normative
- EM-070: needs salience in turn prompt (energy, countdown, recharge affordability);
  recharge-at-full → validator rejection with reason, NO credit charge; `agent_starving`
  events (threshold cross + per-turn at 0 w/ countdown); `world_state` agents carry
  `turns_until_death`; config `world.starving_warn_threshold` (25), documented in world.yaml
- EM-071: `world_extinct` event + `world.auto_pause_on_extinction` (default true)

**frontend-agent — EM-069, EM-071 (UI), EM-072, EM-074, EM-070 (UI):**
- EM-069: wire `inspectorApi` per frontend-inspector v1.1.0 (backfill on mount, /api/replay
  for scrub, onSeekTick passed from App, panels pinned at scrub tick, empty states everywhere,
  C4 strict-left fold boundary)
- EM-072: routing-degraded banner (≥2 distinct live profiles, all routed_via resolve to 1 model)
- EM-071 UI: extinction banner + end-of-run summary card (ticks survived, deaths, rules, crimes)
- EM-070 UI: starvation surfacing (agent panel countdown, feed warning styling for agent_starving)
- EM-074: C2 play/pause+speed render state, C3 reconnect timer cleanup + exponential backoff,
  C5 force-graph pauseAnimation cleanup (read ref at teardown), C6 AWI gov column
  (per-model passed/proposed, consistent numerator/denominator), C10 synthetic-event seq
  (collision-free scheme, not Date.now())
- Delete dead `PanelStub.tsx`

## Gates

1. Wave gate: `pytest` (backend/), `tsc -b && vite build` (web/), diff-scoped token check
2. qe-agent: regression tests for every EM-073 fix + replay fold-forward property test +
   starvation/extinction tests → `coordination/qa-report.json`
3. Orchestrator: live browser verification against BUILD-PLAN W9 exit criteria
   (fresh-load scrub correctness, starvation warnings, extinction pause/banner,
   routing-degraded banner, clean console)

## Gate log

| Date | Gate | Result |
|---|---|---|
| 2026-06-09 | Wave gate (impl) | GREEN — pytest 149/149; `tsc -b` + `vite build` clean; diff-scoped token check clean (hex only in token declarations; inline styles are var()/data-driven) |
| 2026-06-09 | QA gate | RED then GREEN — qe-agent found W9-QA-1 (HIGH: replay fold read wrong agent_moved key; positions stale between snapshots); fixed forward by frontend-agent (`payload.place` first), re-gated proceed=true. 172 passed / 0 failed / 1 intentional xfail pinning W9-QA-1b (backend analytics half, W10/EM-076). +24 tests in test_w9.py incl. fold-forward property test |
| 2026-06-09 | Live verification | GREEN — fresh page load vs 98-tick mock run: 869 events backfilled, scrub to t10 + t60 (between snapshots) renders correct positions/panels, governance scoped to scrub tick, animal traces isolated w/ per-attempt CACHED/RETRY badges; starvation countdown fired live (Bram 3→2→1→died); god-kill extinction → world_extinct + auto-pause + banner + run summary; routing-degraded banner field-verified by user on real FreeLLMAPI run; console 0 errors |
