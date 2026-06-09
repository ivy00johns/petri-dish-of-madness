# W10 Build — "Trust & hygiene" (EM-075–078 + EM-043)

Branch: `build/w10-trust-hygiene` (stacked on `build/w9-make-v2-true`).
Source: `BUILD-PLAN.md` §Wave 10 + `docs/audit-2026-06-09.md` + W9 carry-forwards
(`BUILD_RESULTS_W9.md` §Known issues). Contract deltas this wave: `/api/animals` added to
api.openapi (E2); never-emitted kinds removed from events.schema x-known-kinds (E3).
End state: PR (user-requested) after gates.

## Status of filed items vs reality (scope notes)

- EM-075 "snapshot round-state" sub-item: ALREADY SHIPPED in W9 (B8). Remaining scope:
  time-projected buildings (C7), animals on 2D map (D4), status-strip scrub/live mix,
  scrubbed agent energy/credits re-projection.
- EM-077 "cache flush on reset" (B12): ALREADY SHIPPED in W9. Remaining: B10, B11, B14, B15.

## File ownership (strict)

| Agent | Owns | Forbidden |
|---|---|---|
| backend-agent | `backend/**` | `web/**`, contracts, README.md, docs |
| frontend-agent | `web/src/**` (no package.json) | `backend/**`, contracts, README.md |
| docs-agent | `README.md`, `coordination/V2_BUILD.md`, `docs/FUTURE.md` | code, contracts |
| qe-agent (wave 2) | `web/**/*.test.*`, `web/vitest.config.*`, `web/package.json` (test deps/scripts only), `backend/tests/**`, `coordination/qa-report.json` | src except tests |
| orchestrator | `contracts/**`, `coordination/**`, ledger | implementation |

## Wave 1 (parallel)

**backend-agent — EM-076 (backend) + EM-077:**
- B9: get_analytics active_rules — correct formula AND source of truth (rules table /
  world state, not event counting)
- W9-QA-1b: space_exploration reads agent_moved payload.place (repository.py:593);
  flip the strict xfail in tests/test_w9.py to a passing assertion
- B10: WS broadcast — done-callback cleans failed sockets out of _connections
- B11: Gemini key via x-goog-api-key header, not URL query
- B14: implement profile-color lookup for governance spawns (drop the hasattr guard)
- B15: max_length caps on spawn name/personality/location (agents + animals)

**frontend-agent — EM-075 (remaining) + D5:**
- C7: time-projected building status in replay (fold structure_state_changed/project_* into
  replayStateAt; scrubbed replay map shows the building as it was at tick T)
- D4: animals on the 2D WorldMap (and replay map if absent there)
- Status strip: while scrubbed, agent count/rules reflect the scrub tick (no live/scrub mix)
- Scrubbed agent energy/credits re-projection where events carry deltas (action_resolved
  state_deltas, economy events); document any remaining approximation in the panel
- D5: speed label derives from server tick_interval_seconds (world_state), not slider-local
  state; slider re-syncs when server value changes

**docs-agent — EM-078 (docs half):**
- README.md: restore the two screenshot image embeds + the Animal Chaos Feed sentence ON TOP
  of the current working-tree edits (preserve the user's link/table changes); add a short
  "replayable runs need a file db_path" note (event-log.md §6); verify all commands/paths
  still real
- coordination/V2_BUILD.md: mark W8 DONE (stale "next"); add pointer to W9/W10 build docs
- docs/FUTURE.md: annotate head-to-head dashboard as shipped (EM-059); remove replay-viewer
  remnants if any

## Wave 2 (after wave-1 gate)

**qe-agent — EM-043 + regression:**
- Vitest + jsdom infra in web/ (test deps + `npm test` script)
- Unit tests: selectors (replayStateAt incl. building projection + strict-left boundary,
  governanceTimeline, awiSummary gov column + space exploration, turnTrace), routing-health
  hook logic, extinction lib, synthetic-seq scheme
- Component smokes: ReplayScrubber play/pause state, AgentPanels dying badge
- Backend suite re-run; refresh coordination/qa-report.json with gate decision

## Gates

1. Wave-1 gate: pytest green (incl. flipped xfail), tsc -b + vite build, token check on diff
2. Wave-2 QA gate: vitest suite green + qa-report proceed=true
3. Orchestrator live verification (scrubbed buildings/animals, speed label, README claims)
4. PR (user-requested): branch → main via git-pr skill

## Gate log

| Date | Gate | Result |
|---|---|---|
