# W29 Build Results — offline-review remediation army

> **Status: COMPLETE — all 25 findings fixed, QE gate proceed=true.**
> Branch `build/w29-offline-review-fixes` → PR #74 · 2026-07-03 · Lead: orchestrator session.
> Contract: `contracts/w29-remediation-contract.md` · Gate report: `coordination/qa-report.json` (wave-W29).
> Reality-gate note: every offline gate ran (full suites, production build, adversarial
> probes); a **live-sim browser walk was not exercised this wave** — that remains the
> repo's standing user-gated step (same gate as the `ROAD_MESH_ENABLED` visual
> sign-off). The frontend fixes here are leak/perf/a11y/fallback fixes with
> symptom-level unit regressions, not new surfaces.

## What shipped (5 lanes, 25 findings, exclusive file ownership)

| Lane | Commit | Findings |
|---|---|---|
| P providers | `f88dea1` | EM-287 image write-guard (8 MiB cap + raster magic), EM-296 SSRF guard (resolved-IP check, manual redirect re-validation) |
| U frontend-ui | `96e793b` | EM-274 scopedSlice LRU, EM-286 traffic content-sig memo, EM-291 RingGeometry dispose, EM-292 rAF token cache, EM-293 ARIA tabs, EM-294 diary fallback |
| S sim-core | `fc8f42b` | EM-272 teach no-op rejected, EM-275 crime-decay fork fix, EM-276 corpse-trial guard, EM-277 launder fee floor, EM-278 master-plan yield, EM-279 consolidation reachable, EM-288 partial-xp serialized (**PLAUSIBLE → confirmed real**), EM-289 co_build scoring |
| R runtime | `9b8449d` | EM-280 layout effects on the propose menu, EM-281 retry budget grows, EM-285 constitution cap+dedupe, EM-290 fundable-gated project block, EM-295 planar_faces signature cache |
| L city-layout | `e7d352a` | EM-273 edge-derived streets (no phantoms), EM-282 grid-plat fallback, EM-283 crossing detect-and-bail, EM-284 orientation-complete car ban |
| QE | `c019e97` | 20 cross-lane adversarial probes (5 families, all CONFIRMED-OK) + `qa-report.json` |
| docstring | (follow-on) | QE doc-drift routed back to Lane S: grant_skill_xp docstring corrected |

## Gates

- **Wave gate (first-pass green, circuit breaker never engaged):** backend `1912 passed`
  (`.venv/bin/python -m pytest backend/tests`), `tsc -b --force` rc=0, frontend
  `1210 passed / 103 files` (vitest), `vite build` ✓.
- **QE gate:** `proceed=true`, scores contract/coverage/security/regression all 5,
  0 blockers. Every finding has a regression test that fails on pre-fix code and
  asserts the user-visible symptom.
- **Determinism (EM-155):** no golden regenerated; fork/replay byte-identity proven
  end-to-end with the new `skill_xp` snapshot key and live crime decay (probe 1,
  incl. a teeth-test that re-introduces the pre-fix divergence).

## Follow-up candidates (NOT yet in the ledger — run `plan-intake` to file)

1. **Ambient-car overshoot on partially-thinned streets** (EM-273 residual, visual-only):
   cars sweep the global `trafficSpan` because `CityStreet` carries no paved extent;
   clipping needs `trafficLayout.ts`/`Traffic.tsx` to consume a per-street span.
   Characterization test already in `w29qe.crossmorph.test.ts`.
2. **Animals-lane retry-budget sibling** (`backend/petridish/animals/runtime.py:607`):
   same base-vs-actual bug class as EM-281, out of that finding's cited scope.
3. **Constitution dedupe-on-add** (`world.py` add site): EM-285 fixed rendering;
   the data layer can still store duplicate articles.
4. **Image body buffered before the size cap** (`imagegen/provider.py`): the written
   file is always bounded, but peak memory isn't; true bounding needs
   `client.stream()` + fixture growth.
5. **DNS-rebinding TOCTOU in the SSRF guard** (`imagegen/provider.py`): the guard
   resolves the host, then httpx resolves again on GET; hard bounding needs IP
   pinning via a custom transport.

## Handoff items for the user

- **Merge decision on PR #74** (squash, per repo convention).
- **`/code-review` on PR #74** — external CLI, user-triggered/billed (standing
  manifest handoff).
- **Live-sim smoke walk** rides the next live session (standing deferral).
- **Next build candidates:** W28 free-placement F1 (EM-268) needs its `writing-plans`
  decomposition first (spec approved, no implementation plan yet); same for EM-267
  ideologies. Wave O (EM-249–263) has full specs and War P1 is slated first.
