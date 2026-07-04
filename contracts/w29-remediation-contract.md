# W29 Remediation Contract — offline-review fix army (EM-272–296)

> **Version 1** · 2026-07-03 · Branch `build/w29-offline-review-fixes` · Lead: orchestrator session.
> Source of truth for the findings: `docs/REMAINING-WORK.md` W29 rows (EM-272–296),
> intaked from the 2026-07-01 deep review of PRs #49–69 (9 sibling criticals already
> shipped in PR #70 — see `contracts/fix-wave-offline-review-contract.md`).

## Mission

Fix all 25 W29 findings. Each fix: **verify first** (the review was offline; line
numbers may have drifted), fix minimally, add a regression test, keep every existing
test green.

## Lanes and file ownership (exclusive — no exceptions without lead approval)

| Lane | Agent | Findings | Owns (exclusively) |
|---|---|---|---|
| **S** sim-core | sim-core-agent | EM-272, 275, 276, 277, 278, 279, 288, 289 | `backend/petridish/engine/world.py`, `backend/petridish/engine/loop.py`, `backend/petridish/persistence/repository.py` |
| **R** runtime | runtime-agent | EM-280, 281, 285, 290, 295 | `backend/petridish/agents/runtime.py`, `backend/petridish/engine/citygraph.py` |
| **L** city-layout | citylayout-agent | EM-273, 282, 283, 284 | `web/src/components/world3d/cityLayout.ts`, `web/src/components/world3d/cityFaces.ts` |
| **U** frontend-ui | frontend-ui-agent | EM-274, 286, 291, 292, 293, 294 | `web/src/inspector/selectors.ts`, `web/src/inspector/InspectorLayout.tsx`, `web/src/components/world3d/Traffic.tsx`, `web/src/components/world3d/RoadMesh.tsx`, `web/src/components/map/WorldMap.tsx`, `web/src/components/diary/DiaryView.tsx` |
| **P** providers | providers-agent | EM-287, 296 | `backend/petridish/imagegen/provider.py` |

- **Test files:** every agent writes NEW test files only —
  `backend/tests/test_em###_<slug>.py` / `web/src/**/<Name>.em###.test.ts(x)` beside
  existing tests. Never edit a shared existing test file; if a golden or existing
  test legitimately must change, STOP on that finding and report to the lead.
- **Cross-lane needs** (e.g. lane S needing a `citygraph.py` change) go through the
  lead — do not touch another lane's files.

## Common rules (all lanes)

1. **Toolchain:** `.venv/bin/python -m pytest <targets>` from repo root (there is NO
   bare `python` on PATH). Frontend: `/usr/local/bin/npx vitest run <targets>` and
   `/usr/local/bin/npx tsc -b --force` from `web/` (nvm is broken — use the absolute
   npx path; never `tsc --noEmit`, project refs make it vacuous).
2. **Run TARGETED tests only** (your new test files + the directly-relevant existing
   files). Other lanes are editing the same working tree concurrently — a full-suite
   or full-typecheck failure outside your files is *their* in-flight state, not
   yours. The lead runs the integrated wave gate after all lanes land.
3. **NEVER run `git add`, `git commit`, or any git write.** Leave edits in the
   working tree; the lead commits per lane after the wave gate.
4. **Determinism (EM-155) is law.** Replay/fork must stay byte-identical. If a
   determinism golden or replay test fails from your change, stop and report — never
   regenerate a golden silently. New serialized fields need old-snapshot fallbacks
   (missing field ⇒ deterministic default; never a crash, never a hole).
5. **Two coordinate frames:** places/citygraph logical `0..1000` vs world `±33`.
   Convert only via `citygraph.logical_to_world`. A missed conversion silently
   killed EM-243 in every live run — check which frame every coordinate is in.
6. **Prompt-diet / free-scale law:** prompt-surface fixes (EM-280/285/290) must not
   bloat prompts — compact lines, caps, dedupe. Never add a standing LLM call and
   never throttle/mute agents.
7. **Verify-before-fix:** reproduce each finding at the cited site first. If a
   finding is not real (esp. EM-288, filed as PLAUSIBLE), report `not-a-bug` with
   evidence instead of "fixing" it.
8. **Minimal diffs.** Match surrounding style. No drive-by refactors.

## Per-lane report format (final message = machine-consumable)

For each finding: `EM-### — fixed | not-a-bug | blocked` + one-line root cause, files
touched, new test file + test names, and the exact targeted-test command you ran with
its result. End with any cross-lane or golden-change escalations.

## Wave plan

- **Wave 1:** lanes S, R, L, U, P in parallel (this contract).
- **Wave gate (lead):** full `.venv/bin/python -m pytest backend/tests` +
  `tsc -b --force` + `vitest run`; failures routed back by file ownership;
  circuit breaker at 3 no-progress iterations.
- **Wave 2:** qe-agent — schema-conformant `qa-report.json`, integration/regression
  coverage audit of all 25.
- **Gate:** `gate_decision.proceed` rules; lead never overrides.
