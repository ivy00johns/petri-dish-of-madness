# EM-264 (SA) — Graph-Derived Buildable Zones · Build Coordination

Source spec: `docs/superpowers/specs/2026-06-29-agent-building-layout-sA-graph-zones-design.md`
Contract: `contracts/em264-build-contract.md` · Branch: `build/em264-graph-zones` · Scanned: 2026-06-29

## Runtime
ultracode ON → **Workflow mode**. Design + contracts inline (this doc + the
contract). Implement + verify run as Workflow scripts. SA is sequential within
the initiative (SB depends on SA, SC on SB) — we build **SA only** here, gate it,
then stop for the user's visual sign-off before SB.

## Lanes (file ownership in the contract §1)
- **Lane A** — `cityFaces.ts` + `cityFaces.test.ts` (the planar-face algorithm; pure, isolated).
- **Lane B** — `cityLayout.ts` branch + `CityScape.tsx` flag + appended on-path tests (consumes real Lane A).
- **QE** — `coordination/em264-qa-report.json` (verifies; edits no source).

## Mission skill manifest — EM-264
Every box ends ✅ (invoked, artifact path) or a one-line deferral reason.

### Phase 1 — design / contracts (inline, done)
- [x] `brainstorming` — ✅ specs SA/SB/SC merged to main (prior session).
- [x] `contract-author` (inline) — ✅ `contracts/em264-build-contract.md`.

### Phase 2 — implement (Workflow)
- [ ] Lane A agent — `cityFaces.ts` + tests.
- [ ] Lane B agent — `cityLayout.ts`/`CityScape.tsx` + on-path tests.

### Phase 3 — verify (Workflow + lead)
- [ ] Wave gate (lead, inline) — integrated `tsc -b --force` + `vitest run`.
- [ ] Adversarial verify — algorithm / byte-identical / silent-drop lenses.
- [ ] `qe-agent` — `coordination/em264-qa-report.json` (QA gate).

### Deferred / N-A (with reasons)
- `nano-banana` — N/A: no new imagery; SA reuses existing GLBs (no new assets).
- `ui-ux-pro-max` / `frontend-design` — N/A: no new UI chrome; SA changes 3-D lot
  *placement* behind a default-off flag, not 2-D UI.
- `ux-review` — N/A for the off-path (no visible change). Folds into the **user
  visual sign-off** when `GRAPH_LOTS_ENABLED` is flipped on (deferred gate).
- `render-sanity` — deferred to the flag-on visual sign-off; off-path renders
  byte-identical (no route/visible-text surface to walk).
- `design-token-guard` / `class-extraction-guard` — N/A: no styling/CSS touched.
- `deployment-checklist` — N/A: no deploy; feature ships dormant behind a flag.

## Gate sequence
See contract §5. Hard gate = off-path byte-identical (existing goldens unchanged).
Final user gate = flip the flag on against a live pentagon (deferred, like EM-247).
