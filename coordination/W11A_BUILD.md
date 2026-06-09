# W11a Build — "UI batch" (EM-086, 093–097, 099 + EM-094 backend half)

Branch: `build/w11a-ui-batch` (stacked on `build/w10-trust-hygiene`).
Source: ledger W11 items (user session 2026-06-09) + `BUILD_RESULTS_W10.md` handoff.
Contract deltas this wave (orchestrator, committed before spawn):
api.openapi.yaml **1.3.0** (`GET /api/runs` + optional `run_id` on all read endpoints),
event-log.md **v1.2.0** (`narrator_summary` kind; animal moves carry `payload.place`;
run-scoped reads normative), events.schema.json (+`narrator_summary`),
frontend-inspector.md **v1.2.0** (§8 run browser, §9 live-view layout/scroll/summary/
critters/camera).

W11b (sim texture: EM-079–083, 087, 091, 092, 098, 100, 101) follows after this wave's
gates.

## File ownership (strict)

| Agent | Owns | Forbidden |
|---|---|---|
| backend-agent | `backend/**` (not `backend/tests/**` new files — qe), `config/world.yaml` | `web/**`, contracts, README |
| frontend-live (A) | `web/src/components/**`, `web/src/hooks/**`, `web/src/lib/**`, `web/src/App.tsx`, `web/src/types/index.ts` | `backend/**`, `web/src/inspector/**`, contracts, package.json |
| frontend-inspector (B) | `web/src/inspector/**` | `backend/**`, everything A owns, contracts, package.json |
| docs-agent (wave 2) | `README.md` | code, contracts |
| qe-agent (wave 2) | `web/**/*.test.*`, `web/vitest.config.*`, `web/package.json` (test deps/scripts only), `backend/tests/**`, `coordination/qa-report.json` | src except tests |
| orchestrator | `contracts/**`, `coordination/**`, ledger, BUILD-PLAN | implementation |

Cross-cutting needs (e.g. B needs an `App.tsx` change) route through the orchestrator.

## Wave 1 (parallel)

**backend-agent — EM-086 (backend) + EM-094 (narrator) + animal place:**
- `GET /api/runs` per api.openapi.yaml 1.3.0 `RunRow` (active = MAX(id) held by the
  loop, NEVER the status column; `config_summary` is a small projection, not the blob).
- Optional `run_id` query param on `/api/events|turns/{id}|rules/history|relationships|
  snapshots|replay|analytics` (default = active run; unknown → 404). Past-run geometry
  via earliest snapshot `state_json`, not the `places` table.
- Narrator mode (event-log.md v1.2.0 §note 1): `world.narrator {enabled:false,
  every_n_ticks:50, model_profile}` → one `narrator_summary` event per window when
  enabled; failed call emits nothing and never stalls the loop; off-path = zero cost.
- `animal_action` movement rows include destination `payload.place` (additive).

**frontend-live (A) — EM-093 → EM-096 → EM-094 (digest UI) → EM-099 → EM-095:**
- EM-093 FIRST (P1): un-pinned feed never moves the viewport on arrivals; "X new"
  pill + re-pin behavior preserved. Regression bar: 50 arrivals, fixed viewport.
- EM-096 layout per contract §9 (left feed+summary, ~2× village, bottom agent strip,
  right controls). No info loss vs today.
- EM-094 digest: pure zero-LLM selector (deaths, active rules, projects, drama
  heuristic) at the top of the feed column; Narrator toggle surfaces
  `narrator_summary` events with a labeled off-state.
- EM-099 CRITTERS group in the bottom strip (species, name, mood, model chip,
  location, chaos count; click = focus/follow).
- EM-095 camera: pan, zoom-to-place on building click, follow-agent, reset view;
  user drag always escapes.

**frontend-inspector (B) — EM-086 (UI) + EM-097:**
- `RunBrowser.tsx` + archive mode per contract §8 (selectedRunId threads `run_id`
  through `api.ts`; WS merge disabled while archived; "back to live" affordance).
- Cross-run AWI comparison (two runs side-by-side via `/api/analytics?run_id=`).
- EM-097: capture-instance cleanup in SocialGraph (or delete the dead path); tell
  orchestrator so qe un-xfails the pin.

## Wave 2 (after wave-1 gate)

**qe-agent:** vitest for new selectors (digest, scroll-anchor logic where unit-testable,
RunBrowser archive-mode fetch scoping), un-xfail the EM-097 pin, backend tests for
/api/runs + run_id scoping + narrator emission + animal place payload; rerun both
suites; refresh `coordination/qa-report.json` with a gate decision.

**docs-agent:** README — run browser + narrator-mode + new layout/camera blurbs;
verify commands still real. Nothing else.

## Gates

1. Wave-1 gate: pytest green, `tsc -b` + `vite build` green, design-token check on diff.
2. Wave-2 QA gate: full suites green + qa-report proceed=true.
3. Orchestrator live verification (Playwright): scroll stability, new layout, digest,
   critters strip, camera modes, run browser vs the 5+ runs on disk, archive mode.
4. Ledger/BUILD-PLAN closeout + BUILD_RESULTS_W11A.md. No merge — branch only.

## Gate log

| Date | Gate | Result |
|---|---|---|
