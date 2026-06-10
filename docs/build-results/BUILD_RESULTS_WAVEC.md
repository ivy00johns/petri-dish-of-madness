# Wave C — "a town, not a diorama" · Build Results

> Branch: `build/wave-c-real-city` (stacked on `fix/live-run-annoyances`, PR #8)
> Date: 2026-06-10 · Contract: `contracts/wave-c.md` · QA: `coordination/qa-report.json` (proceed=true)
> Items: EM-147, EM-148, EM-149, EM-150, EM-124 — all **done** in the ledger (`wave-C 2026-06-10`).
> Design: `docs/superpowers/specs/2026-06-10-wave-c-real-city-design.md` (filed via plan-intake as EM-147–150 + EM-124 rescope).

## What shipped

| Item | Commit | Delivery |
|---|---|---|
| EM-147 district town | `059cc60` | 15-place district town (core/market/civic/residential/farm over the existing 5 kinds) in `world.yaml` + the loader's embedded mirror (sync test-pinned); additive optional `PlaceConfig/PlaceState.district` serialized only when set; legacy ids/kinds survive; plaza/townhall gate ids hold; three `PlaceConfig→PlaceState` conversion sites that silently dropped the field fixed. 8 tests incl. a full cross-district mock-path run. |
| EM-148 GLB asset layer | `d5ca5d9` | `world3d/assets/`: models.ts registry (10 VariantKeys, place anchors, villager/cat/dog), `<Model>`/`<InstancedModel>`/`useToonGLTF`/`preloadHeroModels`, toonify.ts pure conversion (toon ramp once per GLB, maps preserved, tint/healthTint on cloned materials). 14 CC0 GLBs vendored, **3.65 MB** (KayKit Medieval Hexagon + Adventurers, Kenney Fantasy Town, Quaternius cat/dog) — licenses verified pre-vendor, recorded in `ASSET_LICENSES.md`; zero new runtime deps, no decoders needed. 51 tests incl. footprint bounds proven against the GLB bytes. |
| EM-149 lane network | `0c35196` | `townLayout.ts` (pure/deterministic): district anchors → angle-ordered main-street ring, per-district Prim MST connectors, full reachability tested, lanes bend around places, junction patches; coordinate-clustering fallback for district-less snapshots. Ground renders warm-toon lane strips (look-dev call: strips > road tiles) + subtle district zone tints. **The hub-and-spoke pinwheel is dead.** SIZE 40→66 + camera/fog/shadow retune; foliage corridors consume townLayout's lanes (single source of truth). 36 layout tests; 60fps at default camera. |
| EM-150 buildings swap | `ab733d0` | Operational structures render registry GLBs by `operationalVariant()` (windmill/blacksmith/tower/stall/fountain/well/tavern; garden+library stay procedural by design); place anchors get kit models (work/governance/home). `ModelBoundary` = Suspense + error boundary: procedural fallback while streaming AND on fetch failure (bare Suspense blacked out the canvas — probe-proven fixed). Soot/offline ride the model tint; labels/bob/click-to-focus preserved. 44 tests. |
| EM-124 characters swap | `abacfda` | Rigged KayKit villager + Quaternius cat/dog, idle/walk crossfade via hysteresis on the existing position lerp, wrap-aware facing, per-agent tint on cloned materials. `SkeletonUtils.clone` (drei `<Clone>` mis-rebinds the Quaternius rigs) + `frustumCulled=false` on skinned meshes. Dead agents keep the Wave B ghost; unknown species fall back procedural (EM-143-ready); overlays untouched, labels no longer jiggle. 20 tests. |

## Gates

- Backend **367/367** (+8) · web **376/376** (+82 across C2/C3/C4/C5) · `npm run build` clean.
- QE adversarial gate (`qa-report.json`): proceed=true — contract 5/5, coverage 5/5, security 5/5, regression 4/5. **9 probe families, zero bugs**: unguarded-GLB-site sweep (none), pre-Wave-C snapshot + clustering fallback, 15-place round-trip byte-stability, 16 evil kinds through the full resolution chain (Wave B's prototype-key crash class confirmed dead), mixed/partial districts, asset/license integrity both directions (no orphan payload), free-scale law (zero LLM call sites in the wave diff), double-invocation determinism.
- Browser (orchestrator + QE independently): console **0 errors**, 60fps measured, click-to-focus on GLB buildings works, fallback probe (blocked `/models/**`) renders the full procedural town. Evidence: `docs/build-evidence/wave-c-gate2-town-live.jpeg`, `wave-c3-home-view.png`, `qe-wave-c-town-initial.jpeg`, `qe-wave-c-plaza-zoom.jpeg`.

## Recorded QE MINORs (not blocking)

1. `InstancedModel` has zero production consumers yet — wire it when town density grows (repeated same-variant cottages).
2. `PlaceState` now has 3 duplicated construction sites (api/loop/run) that must each remember `district=` — a shared constructor helper would de-risk.
3. Module-scope `preloadHeroModels()` rejections unhandled (console noise risk on flaky networks only; render paths are boundary-safe).
4. Non-string snapshot districts coerce via `str()` (cosmetic).

## Deliberate scope notes

- garden/library VariantKeys stay procedural — no CC0 model with the right read was acquirable headlessly; registry nulls are the documented mechanism.
- KayKit City Builder Bits skipped (modern-city aesthetic); Quaternius site downloads aren't headless — his CC0 models came via poly.pizza direct URLs (CC-BY ones rejected).
- Model facing: all `rotation: 0` — probe sheets showed KayKit/Kenney author fronts toward the default camera; `structureModel.ts` keeps the per-variant tuning table.
- Status renderers (planned/under_construction/damaged/…) remain procedural this wave by contract.

## Handoff

- Wave C is complete on `build/wave-c-real-city`, stacked on `fix/live-run-annoyances` (**PR #8, awaiting the user's merge**). Merge PR #8 first, then PR wave-c (or retarget).
- Open P1: **EM-151** (inspector archive blank on 40k-event runs). Open city-track depth: EM-123 (neighborhoods grow), EM-127 (day/night + particles), EM-143 (god-spawn critters — squirrel falls back procedural until a model is added).
- Full-skill `ux-review` repo-wide pass owed on merged main (standing since W11b — now the natural moment: the W9→WaveC surface is finished).
