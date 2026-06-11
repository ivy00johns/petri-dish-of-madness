# Wave D1.5 contract — "make it THE city" (corrective, supersedes wave-d1.md §D1b/§D1d policy)

> User verdict on D1: the ring city is decor; the medieval core is dead. The sim moves ONTO
> the grid, EW-style: compact, dense, every block developed, places ARE city landmarks.
> Lean build: 2 agents (A: sim+layout, B: render+assets), orchestrator gates.
> All D1 invariants survive: determinism f(snapshot, city_seed), additive-only backend,
> CC0+recorded, fallback law (null/failed GLB ⇒ procedural or skip, never a crash),
> free-scale law (zero LLM-path changes), agents never commit.

## The frozen city plan

- Grid: **5×5 blocks**, block pitch **13.0** world units (4 developable tiles + 1 road
  tile, TILE=2.6), centered on the world origin; roads between all blocks + an outer ring
  road. City span ≈ 66u — it IS the world (SIZE stays 66).
- Block centers (world): −26, −13, 0, 13, 26 on each axis. Logical (0..1000) equivalents
  for `world.yaml`: **106, 303, 500, 697, 894** (placeToWorld puts these within 5mm of the
  block centers; cityLayout snaps landmark anchors to exact centers, tolerance 1.0u).
- **Every place claims one block** (its landmark block): place anchor + its building-slot
  ring live there; NO generated buildings inside a landmark block; sidewalk props on its
  road edges are fine.
- Non-landmark blocks are **fully developed by zone** — every lot gets a building
  (lot-level density; empty road-framed blocks are a contract violation), except park
  blocks (trees + benches, no buildings).
- Zone from district: core→plaza/civic flavor, market→commercial, civic→civic,
  residential→residential, farm→**park/greenbelt** (the modern re-read of the old farm
  edge). Generated blocks take the zone of the nearest landmark's district.

### The landmark table (ids, kinds, districts UNCHANGED — engine-safe; names/positions/descriptions re-themed)

| id | block (world) | yaml x,y | new name |
|---|---|---|---|
| plaza | (0, 0) | 500, 500 | Central Plaza |
| well | (0, −13) | 500, 303 | Fountain Court |
| townhall | (−26, −26) | 106, 106 | City Hall |
| archive | (−13, −26) | 303, 106 | The Records Office |
| market | (13, −13) | 697, 303 | Market Hall |
| forge | (26, −13) | 894, 303 | The Steelworks |
| workshop | (26, 0) | 894, 500 | Tinker's Workshop |
| home | (−26, 13) | 106, 697 | Hearth House |
| rosehip_cottage | (−26, 26) | 106, 894 | Rosehip Walk-up |
| mossy_row | (−13, 26) | 303, 894 | Mossy Row Flats |
| lantern_loft | (−13, 13) | 303, 697 | Lantern Lofts |
| commons | (13, 13) | 697, 697 | The Commons Park |
| willow_pond | (13, 26) | 697, 894 | Willow Pond Park |
| orchard | (26, 26) | 894, 894 | Orchard Green |
| farmstead | (26, 13) | 894, 697 | Sunfall Depot |

Descriptions: rewrite to city flavor, keep the mechanical sentence ("Rest and recharge.",
"Forage for scraps.", "Earn credits by working.", "Propose and vote on rules.") intact
where present — prompts quote them.

## Agent A — sim + layout (`city-sim-layout`)

**Owns:** `config/world.yaml` (places block only) + `backend/petridish/config/loader.py`
EMBEDDED mirror + any backend tests pinning place names/positions (update honestly;
ids/kinds/districts must NOT change); `web/src/components/world3d/cityLayout.ts` (+test);
`townLayout.ts` (+test); `foliageLayout.ts` (+test); `Scenery.tsx`.

1. Apply the landmark table to `world.yaml` + the embedded mirror (keep `city_seed`, agent
   seeds, every other section untouched). Run the FULL backend suite; fix pinned config
   tests honestly.
2. `cityLayout.ts` v2 — same exports plus:
   `CityPlan.landmarks: Record<string, { x: number; z: number }>` (place id → snapped
   anchor center) and `blocks[].zone` gains `'landmark'`. Remove the ring/coreRadius
   machinery (`deriveCoreRadius`, `townCenter` exported if still useful to others — check
   consumers first). Grid per the frozen plan; landmark blocks reserved; parks from
   farm-district landmarks + exactly 1 seeded park among generated blocks; all other lots
   developed (zone-matched key variety, street-facing rotations); props on sidewalks;
   sparse parked cars on curbs. Budget ≤ 3000 holds trivially at this size. Determinism
   invariants keep their names (EM-155 block). Tests updated: add "every non-park
   generated block has zero empty lots" and "every landmark block has zero generated
   buildings" and "landmark snap < 1.0u from placeToWorld".
3. `townLayout.ts` — lanes are dead: `computeTownLayout` keeps its signature but returns
   `lanes: []`, `junctions: []`; keep `groupByDistrict`/`zoneTint`/`DISTRICT_TINTS`/zones
   (Ground still tints; foliage's pathSegments naturally empties). Delete or empty the
   spine/MST machinery and its tests honestly.
4. `foliageLayout.ts` + `Scenery.tsx` — the wilderness is dead: treeline/bushes/rocks/
   mushrooms/grass/flowers layers return empty (or are removed) EXCEPT inside park
   landmark blocks, where a seeded light scatter of trees/grass is welcome. Lamp/bench
   place dressing dies with the lanes (the city plan provides street furniture). Update
   tests honestly; remove the cityLayout↔foliageLayout import cycle while you're in there
   (lift `BAND_MAX` into worldSpace or inline it) — coordinate: worldSpace is Agent B's
   file, so if lifting, put the constant in YOUR file and have only you import it.

## Agent B — render + assets (`city-render-swap`)

**Owns:** `web/src/components/world3d/assets/models.ts` (+test), `assets/cityModels.ts`
(+test) if needed, `web/public/models/kaykit-medieval-hexagon/**` +
`web/public/models/kenney-fantasy-town/stall.glb` (deletions), `ASSET_LICENSES.md`,
`CityScape.tsx` (+test), `Ground.tsx`, `CozyWorld.tsx`, `worldSpace.ts`.

1. **Retire the medieval look.** `PLACE_MODELS`: social→`fountain` spec (the Kenney
   fantasy-town fountain reads fine as a city fountain), governance→`civic_a`,
   home→`res_b`, work→`com_c`, wild→null (parks are trees). `MODEL_REGISTRY`
   (agent-built operational buildings): farm→`ind_b`, workshop→`ind_a`, house→`res_a`,
   stall→`com_a`, clocktower→`civic_a`, well→`fountain`, generic→`com_b`,
   monument→`fountain`, garden/library stay null. Reuse the cityModels GLBs by URL —
   measure scales from the existing cityModels specs (city pieces in PLACE/MODEL registries
   may need their own scale row; derive from the same measured bounds, anchors may read
   ~15% larger per Wave C convention). DELETE the now-unreferenced medieval GLBs
   (kaykit-medieval-hexagon dir, fantasy-town stall.glb) and their `ASSET_LICENSES.md`
   rows; keep villager/cat/dog and the HDRI. Update models.test.ts honestly (it re-measures
   registry files; the license both-directions checks must stay green).
2. `Ground.tsx` — lanes/junction rendering dies (townLayout returns none); keep grass +
   district zone tints (they'll tint blocks via the zones API); ground extent back to a
   compact world (city span 66 + small apron — no more WORLD_REACH sprawl).
3. `worldSpace.ts` — WORLD_REACH shrinks to fit (city + apron, ~SIZE*0.85); keep SIZE 66.
4. `CozyWorld.tsx` — camera/fog/shadow retune for the compact dense city: default framing
   shows the whole city readable (EW screenshot is the reference: you can see the grid,
   the blocks, the landmarks, the agents); shadow frustum covers the whole 66u city now
   (it's smaller than D1's core+ring); remove the dead preload entries for deleted GLBs.
5. `CityScape.tsx` — consume the v2 plan (landmarks/zone additions); no policy of its own.

## Cross-agent seam (FROZEN so you never touch each other's files)

- `computeTownLayout` keeps its signature; `lanes`/`junctions` become empty arrays.
- `CityPlan` gains `landmarks` + `'landmark'` zone as above; everything else unchanged.
- Neither agent edits the other's files. If blocked on the seam, STOP and report.

## Gates (orchestrator)

Full backend pytest + web vitest + tsc + build; live browser pass against the EW
reference: compact dense grid, zero empty non-park blocks, landmarks anchored on their
blocks with agents visible at them, no medieval geometry anywhere, 60fps, console clean;
determinism + license integrity suites green.
