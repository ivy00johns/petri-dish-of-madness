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

### Phase 2 — implement (Workflow `em264-implement`)
- [x] Lane A agent — ✅ `cityFaces.ts` + `cityFaces.test.ts` (16 tests).
- [x] Lane B agent — ✅ `cityLayout.ts`/`CityScape.tsx` + 14 appended on-path tests.

### Phase 3 — verify (Workflow `em264-verify` + lead)
- [x] Wave gate (lead, inline) — ✅ `tsc -b --force` exit 0; world3d **0 net-new failures**
  (3 pre-existing `CityScape.test.tsx` ROAD_MESH failures verified by stash).
- [x] Adversarial verify — ✅ 4 findings raised, 1 refuted (bogus float claim), **3 confirmed**:
  - LOW: docs said "max |area|" vs the correct winding-sign drop → docs corrected.
  - MED: `cityFaces.ts` had a literal NUL-byte separator (binary file) → JSON.stringify key.
  - **HIGH (pillar 2): silent-drop on angular ties** (radial master-plan via EM-245) → fixed
    (coincident-node merge + collinear-overlap split + distance tie-break + `[]` backstop);
    radial now decomposes into real sectors. Fix proven real: the 4 new tie tests FAIL on
    pre-fix code, PASS on the fix. cityFaces 16→22 tests.
- [x] `qe-agent` — ✅ `coordination/em264-qa-report.json`: PASS, `proceed=true`,
  contract 5 / security 5 / coverage 5 / regression 5, 0 blockers.

## Outcome
SA built, hardened, gated, committed on `build/em264-graph-zones`. Ships **OFF**
(`GRAPH_LOTS_ENABLED=false`, byte-identical). ONE open gate: the **user visual
sign-off** (flip the flag against a live pentagon/radial), the EM-247 pattern.

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
