# Mission skill manifest — EM-239 (Layout-Graph Spine, S1)
Source: docs/superpowers/plans/2026-06-27-em239-layout-graph-spine.md · Scanned: 2026-06-27

Every box ends ✅ (invoked, with artifact path) or with a one-line deferral reason.
This build's acceptance bar is **byte-identical rendered output (EM-155)** — there is
deliberately NO visual change, which is why the visual/imagery gates are N/A, not skipped.

## Pre-build (already done this session)
- [x] `brainstorming` — ✅ produced docs/superpowers/specs/2026-06-27-agent-city-layout-*.md
- [x] `plan-intake` — ✅ filed EM-239 + EM-243–248 into docs/REMAINING-WORK.md (commit 764622f)
- [x] `writing-plans` — ✅ produced the EM-239 implementation plan (commit 39bbe97)

## Phase: Implement (Workflow mode — ultracode)
- [x] `orchestrator` — ✅ this build; contracts inline, implement + verify via Workflow tool
- [x] backend-agent (general-purpose) — ✅ Tasks 1,2,5 → citygraph.py, world.py, test_citygraph.py (1620 pass)
- [x] frontend-agent (general-purpose) — ✅ Tasks 3,4 → types, cityLayout.ts, CityScape.tsx, test (byte-identical PASS)

## Phase: Verify
- [x] `qe-agent` (MANDATORY) — ✅ qa-report.json, status PASS, proceed=true (docs/superpowers/em239-build/qa-report.json)
- [x] adversarial verify — ✅ 3 lenses (byte-identical+cross-language PASS, scope+determinism PASS, resilience FAIL→fixed in 52d6c67)

## N/A for this build (recorded, not silently skipped)
- `nano-banana` — N/A: no new imagery; byte-identical city, zero new assets (S5 owns assets).
- `frontend-design` / `ui-ux-pro-max` — N/A: no UI redesign; output must match pixel-for-pixel.
- `render-sanity` / `ux-review` — N/A as a *change* gate: the byte-identical golden test IS the
  render gate (any visual drift fails it). Manual live/replay/fork visual check is Task 5 Step 3.
- `design-token-guard` / `class-extraction-guard` — N/A: no styling/className changes (logic-only
  edits to cityLayout.ts data pipeline; no JSX style surface touched).
- `deployment-checklist` — N/A: not shipping; feature branch only.
