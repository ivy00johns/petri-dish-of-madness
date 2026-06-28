# Mission skill manifest — EM-248 (S5b building variety) · Tasks 1–2 slice
Source: docs/superpowers/plans/2026-06-27-em248-building-variety.md · Scanned: 2026-06-27

Scope of THIS run: Tasks 1–2 ONLY (pure-code rewire) — `PLACE_POOLS` + industrial/civic
building pools. **Stop before Task 3 (vendoring).** Tasks 3–6 (new CC0 GLB downloads + live
walk) are deliberately OUT of this slice (network + HITL asset selection).

Every box ends ✅ (invoked, with artifact) or with a one-line deferral reason.

## Phase: Branch + setup
- [x] feature branch `feat/em248-building-variety` — ✅ created off main (7cd3641)
- [x] agent-config audit — ⚠️ `docs/agents/` absent; proceeding with defaults (single-context,
      local briefs), same as the EM-239 build. Noted, not blocked.

## Phase: Implement (subagents via Agent tool — no Workflow mode: no ultracode reminder this turn)
- [ ] frontend-agent (general-purpose) — Task 1 (PLACE_POOLS + resolvePlaceModel id + Building.tsx
      wiring + tests) and Task 2 (farm/workshop/library/clocktower MODEL_POOLS + tests). AFK (pure-code,
      no HITL). Contract = the plan's exact-code blocks (no separate contract-author phase needed).

## Phase: Verify
- [ ] wave gate (lead) — `npx vitest run src/components/world3d` + `tsc -b --force` green, 0 regressions
- [ ] qe-agent (MANDATORY) — qa-report.json: shape/footprint/determinism(EM-155)/slot-0 invariants,
      adversarial check that variety actually engages and replay-stability holds

## N/A for this slice (recorded, not silently skipped)
- `contract-author` — N/A: the plan supplies exact code + exact tests per task; that IS the contract.
- `nano-banana` / `frontend-design` / `ui-ux-pro-max` — N/A: no new imagery, no UI redesign; this is
  data-pipeline logic in `.ts` files (registry pools), zero JSX/styling surface.
- `design-token-guard` / `class-extraction-guard` — N/A: no className/style/DOM changes.
- `render-sanity` / `ux-review` — N/A as a *change* gate for this slice: the test suite (footprint +
  pool invariants + determinism) is the gate. The live visual sign-off is plan Task 6, which is
  POST-vendoring and out of this slice.
- `deployment-checklist` — N/A: not shipping; feature branch, slice stops before vendoring.
