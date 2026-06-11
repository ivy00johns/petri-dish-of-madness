# Wave D1 contract — "the EW-grade city: vocabulary + generator" (W15)

> Items: EM-152 (city asset vocabulary) · EM-153 (deterministic CityGenerator) ·
> EM-154 (instanced render path) · EM-155 (city snapshot contract) · EM-156 (old-town
> historic district) · EM-157 (instancing scoped to static sets).
> Research: `docs/research/deep-research-v4.md`. Ledger: `docs/REMAINING-WORK.md`.
> Build waves: **wave 1 = D1a ∥ D1b ∥ D1c**, gate, **wave 2 = D1d**, gate, **QE**.

## Global rules (binding on every agent)

1. **Free-scale law:** no change may add a standing LLM call. This wave's backend surface
   is snapshot plumbing only (D1c) — zero provider/runtime-path changes.
2. **Exclusive file ownership** per the table below. Never edit another agent's files,
   even to "fix" a missing import — the wave gate is the integration point. If your file
   imports a sibling's not-yet-written module, that is EXPECTED mid-wave.
3. **Agents never commit.** The orchestrator commits at gates.
4. **Additive-only** schema/state changes: old snapshots, pre-W15 runs, and mock mode must
   stay valid. New keys are optional with safe defaults.
5. **CC0 only**, license verified BEFORE vendoring, every file recorded in
   `ASSET_LICENSES.md`. No CC-BY, ever.
6. **No new runtime deps.** Seeded randomness reuses the repo's deterministic hash idiom
   (see `foliageLayout.ts` / `townLayout.ts` `hashUnit`) — no `seedrandom`, no
   `Math.random()`, no `Date.now()`. Build-time tooling (`@gltf-transform/cli` via npx in
   /tmp) is fine.
7. **Determinism is a contract invariant:** same snapshot + same seed ⇒ byte-identical
   city plan, across live/replay/fork (EM-155).
8. **Old-town invariant (EM-156):** the Wave C town (places, lanes, GLB buildings,
   foliage, characters) renders EXACTLY as today. The generated city surrounds it as new
   districts; no generated piece may intrude into the historic core (clearance rule §D1b).
9. **Interactivity split (EM-157):** generated city pieces are non-interactive set
   dressing on raw `InstancedMesh`. Sim-owned entities (places, agent-built Buildings,
   villagers, critters) keep their existing per-instance components untouched.
10. **Fallback invariant:** with `/models/**` blocked, the app must still render the full
    Wave C procedural+GLB-fallback town with console clean of uncaught errors. Generated
    set dressing may simply be absent (registry `null`/load-failure ⇒ skip, never a hole,
    never a crash).
11. WebGL hex colors are exempt from the design-token rule (established convention) and
    stay centralized in the world3d modules.
12. Tests are part of the deliverable. Python tests import `petridish.engine.world`
    BEFORE `petridish.agents.runtime` (circular-import idiom). Node via
    `export PATH="$HOME/.nvm/versions/node/v22.22.3/bin:$PATH"` + `command npx`.

## Frozen vocabulary — `CityPieceKey`

Defined (the type + key list) in **`web/src/components/world3d/cityLayout.ts`** (D1b owns
the file); D1a's registry imports the type from there. The list is FROZEN by this
contract — both sides code against it independently:

```ts
export type CityPieceKey =
  // roads (Kenney City Kit Roads; ~2.6-unit tiles after scaling, see §D1a)
  | 'road_straight' | 'road_corner' | 'road_tee' | 'road_cross' | 'road_end'
  // zoned buildings (commercial / residential-suburban / industrial / civic)
  | 'com_a' | 'com_b' | 'com_c'
  | 'res_a' | 'res_b' | 'res_c'
  | 'ind_a' | 'ind_b'
  | 'civic_a'
  // street furniture + greenery
  | 'lamp' | 'bench' | 'hydrant' | 'bin' | 'fence' | 'tree_city'
  // vehicles (parked; ambient traffic is EM-169 / W17)
  | 'car_a' | 'car_b' | 'car_c';
```

## D1a — city asset vocabulary (EM-152) — agent `city-assets`

**Owns:** `web/public/models/kenney-city/**`, `web/public/models/kaykit-city/**`,
`web/src/components/world3d/assets/cityModels.ts`, `…/assets/cityModels.test.ts`,
`ASSET_LICENSES.md` (sole writer this wave).

- Acquire headlessly (URLs verified at research time — if one 404s, find the kit's
  current direct zip on kenney.nl, do NOT substitute non-CC0 sources):
  Kenney City Kit Roads / Commercial / Suburban / Industrial, Car Kit, Furniture Kit
  (`https://kenney.nl/media/pages/assets/<kit>/...zip`); KayKit City Builder Bits
  (GitHub `KayKit-Game-Assets/KayKit-City-Builder-Bits-1.0`) for prop gaps only.
- Verify the bundled CC0 license text in each archive BEFORE vendoring; record every
  shipped file in `ASSET_LICENSES.md` (source URL, author, license, use).
- Vendor ONLY the GLBs the registry uses (~25–30 files). Repack each with
  `@gltf-transform` (`dedup`/`prune`/`resample`, textures embedded). **No DRACO/meshopt**
  (no decoders under `web/public/`). Total NEW payload ≤ 15 MB.
- `cityModels.ts`: `export const CITY_MODEL_REGISTRY: Record<CityPieceKey, ModelSpec | null>`
  (reuse `ModelSpec` from `./models`; import `CityPieceKey` from `../cityLayout`).
  Every key present; `null` allowed where no clean CC0 read exists (renderer skips).
  **Scale discipline:** road tiles must land at **2.6 world units** square (the frozen
  `TILE` in §D1b); buildings ≤ 3.4 units on the long side; props 0.4–1.2; cars ~1.6 long.
  Derive every `scale` from the GLB's measured bounding box.
- `cityModels.test.ts`: registry totality (all 23 keys), every non-null url resolves to a
  vendored file, footprint bounds re-measured from the GLB bytes (the `models.test.ts`
  pattern), every vendored file has an `ASSET_LICENSES.md` row and vice versa (no orphans
  either direction).

## D1b — deterministic CityGenerator (EM-153) — agent `city-generator`

**Owns:** `web/src/components/world3d/cityLayout.ts`, `…/cityLayout.test.ts`.
Reads (never edits): `townLayout.ts`, `worldSpace.ts`, `foliageLayout.ts`, `types/index.ts`.

```ts
export const TILE = 2.6;                  // road tile pitch, world units
export interface CityInstance { x: number; z: number; rotY: number; s?: number }
export interface CityPlan {
  pieces: Record<CityPieceKey, CityInstance[]>;
  blocks: { cx: number; cz: number; zone: 'commercial'|'residential'|'industrial'|'civic'|'park' }[];
  extent: number;                          // outer half-size used
}
export function computeCityPlan(
  world: { places: Place[]; city_seed?: number | null },
  opts?: { coreRadius?: number; extent?: number },
): CityPlan
```

- **Seed:** `world.city_seed ?? 1337`. All randomness via the repo's seeded-hash idiom
  keyed on `(seed, gridX, gridZ, purpose)`. Zero `Math.random()`/`Date`/module state.
- **Layout:** Manhattan grid in TILE units. Main avenues frame city blocks of 4×4–6×6
  tiles; blocks subdivide into 4–8 lots; each block gets a zone (commercial near the
  core ring, residential mid, industrial on one seeded edge, civic sprinkled, ~1 in 9
  blocks a park). Lots place zone-matched building keys with seeded variety + rotation
  facing the street; sidewalk props (`lamp`/`bench`/`hydrant`/`bin`) along road edges;
  `tree_city` in parks + residential; `car_a..c` parked along curbs (seeded sparse).
- **Historic core clearance (EM-156):** compute the core radius from the snapshot's
  places bounding circle + margin (default `coreRadius` ≈ townLayout's occupied extent;
  read `computeTownLayout` to derive it, don't hardcode). NO generated piece inside it.
  Roads must visually terminate at the core boundary (`road_end` caps), leaving the Wave C
  lane network untouched inside.
- **Default extent:** city ring spans from the core boundary out to `extent` (default
  ≈ 2× the core radius, capped so total instances ≤ ~3,000).
- `cityLayout.test.ts` (this is the EM-155 frontend invariant home): determinism — two
  calls with the same input are `JSON.stringify`-identical; seed sensitivity — different
  seed ⇒ different plan; core clearance — no instance within coreRadius of the centroid;
  totality — every emitted key ∈ CityPieceKey; bounds — all instances within extent;
  road connectivity — every road tile neighbors ≥1 other road tile; instance budget
  ≤ 3,000; works with `city_seed` absent (default 1337) and with a pre-Wave-C
  district-less snapshot.

## D1c — city snapshot contract (EM-155) — agent `snapshot-contract`

**Owns:** `backend/petridish/engine/world.py` (city_seed only),
`backend/petridish/config/loader.py` + `config/world.yaml` (`world.city_seed` key),
`backend/tests/test_city_seed.py`, `web/src/types/index.ts` (one additive field),
`contracts/world-model.md` (additive delta note).

- `World` gains `city_seed: int` (config `world.city_seed`, default **1337**).
- `to_snapshot()` emits `"city_seed"`; `from_snapshot()` restores it (int-coerced,
  default 1337 when absent — pre-W15 snapshots stay valid). It therefore rides
  `world_state` to the frontend and survives **fork/resume (EM-101) and replay (EM-075)**
  — that is the point of this item.
- `web/src/types/index.ts`: `city_seed?: number | null` on `WorldState` (comment: W15
  EM-155, additive).
- `test_city_seed.py`: config→world wiring; snapshot round-trip; absent-key default;
  fork (`from_snapshot` of a mid-run snapshot) preserves it; world_state payload carries
  it. Import world before runtime.
- Check the three `PlaceConfig→PlaceState`-style conversion sites (app.py / run.py /
  loop.py) for any world-construction path that must thread `city_seed` — Wave C found
  exactly this class of silent drop.

## D1d — instanced render path (EM-154/156/157) — agent `city-render` (wave 2)

**Owns:** `web/src/components/world3d/CityScape.tsx` (+test), `worldSpace.ts` (SIZE/bounds
retune), `CozyWorld.tsx` (mount + camera/fog/shadow retune), `Ground.tsx` (ground plane
extent only — lane network untouched).

- `CityScape`: `computeCityPlan` + `CITY_MODEL_REGISTRY` → one raw `<instancedMesh>` per
  (piece key × block-chunk). Extract geometry/material once per GLB via the existing
  toon-converted load path (`useToonGLTF`), share materials. `null`/failed registry
  entries ⇒ skip (rule 10). Per-chunk `frustumCulled` with correct bounding spheres.
  Memoize the plan on `(places-identity, city_seed)` — never recompute per frame.
- SIZE/camera/fog/shadow retune so core + city ring read well and the shadow frustum
  stays tight (follow the Wave C retune pattern in git history). Keep 60fps: measure
  with the perf HUD; total draw calls ≤ current scene + 30.
- drei `<Detailed>` LOD only if the budget needs it — measure first.
- Tests: plan→instance-count mapping, chunking math, registry-null skip, and a
  CityScape render smoke via the existing world3d test harness.

## QE — agent `qe` (after wave 2)

Adversarial pass + `coordination/qa-report.json` (schema as previous waves; gate rules
apply). Probe families at minimum: determinism invariant under replay/fork snapshots
(EM-155), historic-core intrusion sweep across 25 seeds, pre-Wave-C snapshot + missing
`city_seed`, blocked `/models/**` fallback probe, asset/license integrity both
directions, draw-call + fps measurement at default and zoomed cameras, free-scale law
(zero LLM-path changes in the diff), instance-budget cap, console-clean live run.

## Gates

- **Gate 1** (after wave 1): backend `pytest -q` green, web `vitest run` green,
  `npm run build` clean. Orchestrator commits per-item.
- **Gate 2** (after wave 2): gate 1 suite + Playwright live pass (city visible around
  the historic core, console 0 errors, fps ≥ 55 measured, blocked-models probe) +
  design-token diff check (world3d/WebGL exemption applies). Orchestrator commits.
- **QE gate:** `qa-report.json` `gate_decision.proceed=true`, no CRITICAL, contract +
  security scores ≥ 3. The orchestrator does not override the gate.
