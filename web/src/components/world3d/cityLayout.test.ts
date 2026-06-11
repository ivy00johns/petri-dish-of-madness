/**
 * cityLayout tests — Wave D1.5/D1.6 generator laws + the EM-155 frontend
 * determinism invariant home:
 *   • EM-155 determinism: same snapshot + same seed ⇒ JSON.stringify-identical
 *     plan (live/replay/fork all call the same pure function); a re-parsed
 *     (replayed/forked) snapshot yields the byte-identical plan
 *   • seed sensitivity: different city_seed ⇒ different plan
 *   • city_seed absent (pre-W15 snapshot) ⇒ default seed 1337
 *   • the frozen grid: 5×5 blocks at pitch 13.0, centered on the origin,
 *     roads between all blocks + an outer ring road
 *   • landmarks: every place claims a block (snap < 1.0u for the shipped
 *     town), landmark blocks carry zone 'landmark' and ZERO generated
 *     buildings
 *   • Wave D1.6 — development = f(snapshot):
 *       – tick-0 founding stock matches the FROZEN falloff (adjacent 2–3,
 *         mid ring 0–1, edge 0, Manhattan from the plaza block)
 *       – growth is MONOTONE in day and standing-building count, with a
 *         STABLE PREFIX (a lot once developed never moves at higher budgets)
 *       – the budget caps at total lots; at cap, every non-park generated
 *         block is FULLY developed (the D1.5 density law, now earned)
 *       – developed + emptyLots (platted pads) always partition the lots
 *       – realLots: 6 street-front lots inside each landmark block, never on
 *         roads; assignBuildingLots claims them by stable id order with the
 *         slotLayout-ring overflow fallback
 *   • parks: farm-district landmark blocks get tree fill; exactly one seeded
 *     park among the generated blocks
 *   • props sit on block sidewalks; cars sit on road curbs
 *   • vocabulary totality: pieces carries exactly the 23 frozen CityPieceKeys
 *   • bounds: every instance within the plan's extent (Chebyshev from origin)
 *   • road connectivity: every road tile neighbors ≥ 1 other road tile
 *   • instance budget ≤ MAX_CITY_INSTANCES (3000)
 *   • pre-Wave-C district-less snapshots still produce a lawful city
 */

import { describe, it, expect } from 'vitest';
import type { Building, Place } from '../../types';
import { placeToWorld, slotLayout, SLOT_BASE_RADIUS } from './worldSpace';
import {
  TILE,
  BLOCK_PITCH,
  BLOCK_HALF,
  GRID_BLOCKS,
  LOTS_PER_BLOCK,
  REAL_LOTS_PER_LANDMARK,
  GROWTH_PER_BUILDING,
  GROWTH_DAY_DIVISOR,
  CITY_PIECE_KEYS,
  CITY_ZONES,
  DEFAULT_CITY_SEED,
  MAX_CITY_INSTANCES,
  assignBuildingLots,
  computeCityPlan,
  computeLandmarks,
  growthBudget,
  snapToBlockCenter,
  type CityInstance,
  type CityPlan,
  type CityBlock,
  type CityPieceKey,
} from './cityLayout';

/** The Wave D1.5 15-place city grid (mirrors config/world.yaml). */
const TOWN: Place[] = [
  { id: 'plaza', name: 'Central Plaza', x: 500, y: 500, kind: 'social', district: 'core', description: '' },
  { id: 'well', name: 'Fountain Court', x: 500, y: 303, kind: 'social', district: 'core', description: '' },
  { id: 'market', name: 'Market Hall', x: 697, y: 303, kind: 'work', district: 'market', description: '' },
  { id: 'forge', name: 'The Steelworks', x: 894, y: 303, kind: 'work', district: 'market', description: '' },
  { id: 'workshop', name: "Tinker's Workshop", x: 894, y: 500, kind: 'work', district: 'market', description: '' },
  { id: 'townhall', name: 'City Hall', x: 106, y: 106, kind: 'governance', district: 'civic', description: '' },
  { id: 'archive', name: 'The Records Office', x: 303, y: 106, kind: 'governance', district: 'civic', description: '' },
  { id: 'home', name: 'Hearth House', x: 106, y: 697, kind: 'home', district: 'residential', description: '' },
  { id: 'rosehip_cottage', name: 'Rosehip Walk-up', x: 106, y: 894, kind: 'home', district: 'residential', description: '' },
  { id: 'mossy_row', name: 'Mossy Row Flats', x: 303, y: 894, kind: 'home', district: 'residential', description: '' },
  { id: 'lantern_loft', name: 'Lantern Lofts', x: 303, y: 697, kind: 'home', district: 'residential', description: '' },
  { id: 'commons', name: 'The Commons Park', x: 697, y: 697, kind: 'wild', district: 'farm', description: '' },
  { id: 'willow_pond', name: 'Willow Pond Park', x: 697, y: 894, kind: 'wild', district: 'farm', description: '' },
  { id: 'orchard', name: 'Orchard Green', x: 894, y: 894, kind: 'wild', district: 'farm', description: '' },
  { id: 'farmstead', name: 'Sunfall Depot', x: 894, y: 697, kind: 'work', district: 'farm', description: '' },
];

/** A pre-Wave-C town: NO district field anywhere (old snapshot / procgen). */
const LEGACY: Place[] = [
  { id: 'plaza', name: 'Plaza', x: 500, y: 500, kind: 'social', description: '' },
  { id: 'market', name: 'Market', x: 760, y: 420, kind: 'work', description: '' },
  { id: 'hall', name: 'Town Hall', x: 420, y: 760, kind: 'governance', description: '' },
  { id: 'hearth', name: 'Hearth', x: 250, y: 300, kind: 'home', description: '' },
  { id: 'commons', name: 'Commons', x: 720, y: 760, kind: 'wild', description: '' },
];

const SEEDS = [1, 2, 7, 42, 1337, 9001];

/** Synthetic W7 buildings (only id/location/status matter to the layout). */
function mkBuildings(
  n: number,
  status: Building['status'] = 'operational',
  location = 'plaza',
): Building[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `b${String(i).padStart(3, '0')}`,
    name: `B${i}`,
    kind: 'house',
    location,
    owner_id: null,
    status,
    health: 100,
    condition_label: 'pristine' as const,
    progress: 100,
    funds_committed: 0,
    funds_required: 0,
    contributors: [],
    function: '',
  }));
}

/** A snapshot old/successful enough that the growth budget caps every lot. */
const MATURE_DAY = 999;

const ROAD_KEYS: CityPieceKey[] = ['road_straight', 'road_corner', 'road_tee', 'road_cross', 'road_end'];
const BUILDING_KEYS: CityPieceKey[] = [
  'com_a', 'com_b', 'com_c', 'res_a', 'res_b', 'res_c', 'ind_a', 'ind_b', 'civic_a',
];
const PROP_KEYS: CityPieceKey[] = ['lamp', 'bench', 'hydrant', 'bin', 'fence'];
const CAR_KEYS: CityPieceKey[] = ['car_a', 'car_b', 'car_c'];

/** The 5 frozen block-center coordinates per axis. */
const BLOCK_CENTERS = [-2, -1, 0, 1, 2].map((b) => b * BLOCK_PITCH);
/** The 6 frozen road centerlines per axis (between blocks + outer ring). */
const ROAD_LINES = [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5].map((k) => k * BLOCK_PITCH);

function allInstances(plan: CityPlan): CityInstance[] {
  return CITY_PIECE_KEYS.flatMap((k) => plan.pieces[k]);
}

function roadInstances(plan: CityPlan): CityInstance[] {
  return ROAD_KEYS.flatMap((k) => plan.pieces[k]);
}

function countInstances(plan: CityPlan): number {
  return allInstances(plan).length;
}

/** Instances of `keys` whose footprint center is inside the block. */
function inBlock(plan: CityPlan, block: CityBlock, keys: CityPieceKey[]): CityInstance[] {
  return keys
    .flatMap((k) => plan.pieces[k])
    .filter(
      (i) =>
        Math.abs(i.x - block.cx) <= BLOCK_HALF + 1e-9 &&
        Math.abs(i.z - block.cz) <= BLOCK_HALF + 1e-9,
    );
}

/** The shared law pack: grid, density, totality, bounds, connectivity, budget.
 *  Runs on a MATURE snapshot (budget at cap) so the D1.5 density law still
 *  binds — Wave D1.6 makes that density EARNED, not given. */
function expectCityLaws(places: Place[], seed: number) {
  const plan = computeCityPlan({ places, city_seed: seed, day: MATURE_DAY });
  const label = `seed ${seed}`;

  // vocabulary totality — exactly the 23 frozen keys, in canonical order
  expect(Object.keys(plan.pieces), label).toEqual([...CITY_PIECE_KEYS]);

  // the frozen 5×5 grid: every block on a frozen center, all 25 present
  expect(plan.blocks.length, label).toBe(GRID_BLOCKS * GRID_BLOCKS);
  for (const b of plan.blocks) {
    expect(BLOCK_CENTERS, label).toContain(b.cx);
    expect(BLOCK_CENTERS, label).toContain(b.cz);
    expect(CITY_ZONES, label).toContain(b.zone);
  }

  // a real dense city came out
  expect(countInstances(plan), label).toBeGreaterThan(300);

  for (const inst of allInstances(plan)) {
    expect(Number.isFinite(inst.x), label).toBe(true);
    expect(Number.isFinite(inst.z), label).toBe(true);
    expect(Number.isFinite(inst.rotY), label).toBe(true);
    if (inst.s !== undefined) expect(inst.s).toBeGreaterThan(0);
    // bounds: within the extent (Chebyshev from the world origin)
    expect(Math.abs(inst.x), label).toBeLessThanOrEqual(plan.extent);
    expect(Math.abs(inst.z), label).toBeLessThanOrEqual(plan.extent);
  }

  // landmark blocks: zero generated buildings (the place owns the block)
  for (const block of plan.blocks.filter((b) => b.zone === 'landmark')) {
    expect(
      inBlock(plan, block, BUILDING_KEYS).length,
      `${label}: generated building inside landmark block (${block.cx}, ${block.cz})`,
    ).toBe(0);
  }

  // park blocks: trees, never buildings
  for (const block of plan.blocks.filter((b) => b.zone === 'park')) {
    expect(inBlock(plan, block, BUILDING_KEYS).length, label).toBe(0);
    expect(inBlock(plan, block, ['tree_city']).length, label).toBeGreaterThan(0);
  }

  // DENSITY LAW (at budget cap): every non-park generated block full
  for (const block of plan.blocks.filter((b) => b.zone !== 'landmark' && b.zone !== 'park')) {
    expect(
      inBlock(plan, block, BUILDING_KEYS).length,
      `${label}: empty lots on generated block (${block.cx}, ${block.cz}) [${block.zone}]`,
    ).toBe(LOTS_PER_BLOCK);
  }
  // …and no platted pads remain once everything is developed
  expect(plan.emptyLots.length, label).toBe(0);

  // exactly one seeded park among the generated (non-landmark) blocks of the
  // shipped-shape town (farm adjacency contributes none here)
  const generatedParks = plan.blocks.filter((b) => b.zone === 'park');
  expect(generatedParks.length, label).toBeGreaterThanOrEqual(1);

  // props on sidewalks: inside some block footprint, near its edge
  for (const p of PROP_KEYS.flatMap((k) => plan.pieces[k])) {
    const nearestCx = BLOCK_CENTERS.reduce((a, b) => (Math.abs(b - p.x) < Math.abs(a - p.x) ? b : a));
    const nearestCz = BLOCK_CENTERS.reduce((a, b) => (Math.abs(b - p.z) < Math.abs(a - p.z) ? b : a));
    expect(Math.abs(p.x - nearestCx), `${label}: prop off-block at (${p.x}, ${p.z})`).toBeLessThanOrEqual(BLOCK_HALF);
    expect(Math.abs(p.z - nearestCz), `${label}: prop off-block at (${p.x}, ${p.z})`).toBeLessThanOrEqual(BLOCK_HALF);
  }

  // cars on curbs: one axis within a road tile's half-width of a road line
  for (const c of CAR_KEYS.flatMap((k) => plan.pieces[k])) {
    const dx = Math.min(...ROAD_LINES.map((l) => Math.abs(c.x - l)));
    const dz = Math.min(...ROAD_LINES.map((l) => Math.abs(c.z - l)));
    expect(
      Math.min(dx, dz),
      `${label}: car off the curb at (${c.x}, ${c.z})`,
    ).toBeLessThanOrEqual(TILE / 2);
  }

  // road connectivity: every road tile neighbors ≥ 1 other road tile
  const roads = roadInstances(plan);
  expect(roads.length, label).toBeGreaterThan(0);
  for (const r of roads) {
    const hasNeighbor = roads.some(
      (o) => o !== r && Math.abs(Math.hypot(o.x - r.x, o.z - r.z) - TILE) < 0.02,
    );
    expect(hasNeighbor, `${label}: orphan road tile at (${r.x}, ${r.z})`).toBe(true);
  }

  // instance budget
  expect(countInstances(plan), label).toBeLessThanOrEqual(MAX_CITY_INSTANCES);
}

describe('EM-155 — city plan determinism invariant', () => {
  it('two identical calls produce JSON.stringify-identical plans (districted town)', () => {
    const a = computeCityPlan({ places: TOWN, city_seed: 1337 });
    const b = computeCityPlan({ places: TOWN, city_seed: 1337 });
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it('two identical calls produce JSON.stringify-identical plans (legacy town)', () => {
    const a = computeCityPlan({ places: LEGACY, city_seed: 42 });
    const b = computeCityPlan({ places: LEGACY, city_seed: 42 });
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it('a re-parsed (replayed / forked) snapshot yields the byte-identical plan', () => {
    const world = { places: TOWN, city_seed: 2024 };
    const replayed = JSON.parse(JSON.stringify(world)) as typeof world;
    expect(JSON.stringify(computeCityPlan(replayed))).toBe(JSON.stringify(computeCityPlan(world)));
  });

  it('different city_seed ⇒ different plan (seed sensitivity)', () => {
    const a = computeCityPlan({ places: TOWN, city_seed: 1 });
    const b = computeCityPlan({ places: TOWN, city_seed: 2 });
    expect(JSON.stringify(a)).not.toBe(JSON.stringify(b));
  });

  it('city_seed absent or null ⇒ default seed 1337 (pre-W15 snapshots stay valid)', () => {
    const explicit = JSON.stringify(computeCityPlan({ places: TOWN, city_seed: DEFAULT_CITY_SEED }));
    expect(DEFAULT_CITY_SEED).toBe(1337);
    expect(JSON.stringify(computeCityPlan({ places: TOWN }))).toBe(explicit);
    expect(JSON.stringify(computeCityPlan({ places: TOWN, city_seed: null }))).toBe(explicit);
  });

  it('is insensitive to place input ordering', () => {
    const shuffled = [TOWN[7], TOWN[2], TOWN[14], TOWN[0], TOWN[9], TOWN[4],
      TOWN[1], TOWN[12], TOWN[5], TOWN[11], TOWN[3], TOWN[13], TOWN[6],
      TOWN[10], TOWN[8]];
    expect(JSON.stringify(computeCityPlan({ places: shuffled, city_seed: 1337 }))).toBe(
      JSON.stringify(computeCityPlan({ places: TOWN, city_seed: 1337 })),
    );
  });

  it('holds with the Wave D1.6 growth inputs (buildings + day)', () => {
    const world = {
      places: TOWN,
      city_seed: 1337,
      day: 73,
      buildings: mkBuildings(5),
    };
    const a = computeCityPlan(world);
    const b = computeCityPlan(JSON.parse(JSON.stringify(world)));
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
    // and the growth inputs really shape the plan
    expect(JSON.stringify(a)).not.toBe(
      JSON.stringify(computeCityPlan({ places: TOWN, city_seed: 1337 })),
    );
  });
});

describe('landmarks — every place claims a block (Wave D1.5)', () => {
  const plan = computeCityPlan({ places: TOWN });

  it('exports CityPlan.landmarks with an anchor for every place id', () => {
    expect(Object.keys(plan.landmarks).sort()).toEqual(TOWN.map((p) => p.id).sort());
  });

  it('landmark snap < 1.0u from placeToWorld (the shipped yaml coords)', () => {
    for (const p of TOWN) {
      const w = placeToWorld(p);
      const a = plan.landmarks[p.id];
      expect(
        Math.hypot(a.x - w.x, a.z - w.z),
        `${p.id} snapped too far`,
      ).toBeLessThan(1.0);
    }
  });

  it('snapped anchors sit exactly on frozen block centers', () => {
    for (const p of TOWN) {
      const a = plan.landmarks[p.id];
      expect(BLOCK_CENTERS).toContain(a.x);
      expect(BLOCK_CENTERS).toContain(a.z);
    }
    // and they agree with the standalone snapping helpers
    expect(plan.landmarks).toEqual(computeLandmarks(TOWN));
    const w = placeToWorld(TOWN[0]);
    expect(snapToBlockCenter(w.x, w.z)).toEqual(plan.landmarks.plaza);
  });

  it('the 15 shipped places claim 15 DISTINCT landmark blocks', () => {
    const blocks = new Set(Object.values(plan.landmarks).map((a) => `${a.x},${a.z}`));
    expect(blocks.size).toBe(15);
    expect(plan.blocks.filter((b) => b.zone === 'landmark').length).toBe(15);
  });

  it('every landmark block has zero generated buildings (even at budget cap)', () => {
    for (const seed of SEEDS) {
      const p = computeCityPlan({ places: TOWN, city_seed: seed, day: MATURE_DAY });
      for (const block of p.blocks.filter((b) => b.zone === 'landmark')) {
        expect(
          inBlock(p, block, BUILDING_KEYS).length,
          `seed ${seed}: building inside landmark block (${block.cx}, ${block.cz})`,
        ).toBe(0);
      }
    }
  });
});

describe('density — every block developed at budget cap (the EW law, earned)', () => {
  it('every non-park generated block has zero empty lots, across seeds', () => {
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed, day: MATURE_DAY });
      for (const block of plan.blocks.filter((b) => b.zone !== 'landmark' && b.zone !== 'park')) {
        expect(
          inBlock(plan, block, BUILDING_KEYS).length,
          `seed ${seed}: empty lots at (${block.cx}, ${block.cz})`,
        ).toBe(LOTS_PER_BLOCK);
      }
    }
  });

  it('developed blocks use zone-matched building keys', () => {
    const plan = computeCityPlan({ places: TOWN, day: MATURE_DAY });
    const zoneKeys: Record<string, CityPieceKey[]> = {
      commercial: ['com_a', 'com_b', 'com_c'],
      residential: ['res_a', 'res_b', 'res_c'],
      industrial: ['ind_a', 'ind_b'],
      civic: ['civic_a'],
    };
    for (const block of plan.blocks.filter((b) => b.zone !== 'landmark' && b.zone !== 'park')) {
      const matched = inBlock(plan, block, zoneKeys[block.zone]);
      expect(matched.length, `block (${block.cx}, ${block.cz}) [${block.zone}]`).toBe(LOTS_PER_BLOCK);
    }
  });

  it('zones the shipped town from the landmark districts', () => {
    const plan = computeCityPlan({ places: TOWN });
    const zones = plan.blocks.map((b) => b.zone);
    expect(zones.filter((z) => z === 'landmark').length).toBe(15);
    expect(zones).toContain('commercial');
    expect(zones).toContain('residential');
    expect(zones).toContain('civic');
    expect(zones).toContain('park');
  });
});

// ── Wave D1.6: development = f(snapshot) ─────────────────────────────────────

/** Generated developable (non-park) blocks of a plan. */
function developableBlocks(plan: CityPlan): CityBlock[] {
  return plan.blocks.filter((b) => b.zone !== 'landmark' && b.zone !== 'park');
}

/** All generated-building instances of a plan (the development measure). */
function developedInstances(plan: CityPlan): CityInstance[] {
  return BUILDING_KEYS.flatMap((k) => plan.pieces[k]);
}

/** A stable identity for one developed lot (key + exact position). */
function lotIds(plan: CityPlan): Set<string> {
  const out = new Set<string>();
  for (const k of BUILDING_KEYS) {
    for (const i of plan.pieces[k]) out.add(`${k}@${i.x.toFixed(6)},${i.z.toFixed(6)}`);
  }
  return out;
}

describe('Wave D1.6 — growth budget (snapshot-only)', () => {
  it('counts standing buildings (operational|damaged|offline) and sim days', () => {
    expect(growthBudget([], 0)).toBe(0);
    expect(growthBudget(null, null)).toBe(0);
    expect(growthBudget(mkBuildings(3), 0)).toBe(3 * GROWTH_PER_BUILDING);
    expect(growthBudget([], GROWTH_DAY_DIVISOR * 10)).toBe(10);
    expect(
      growthBudget(
        [...mkBuildings(2, 'operational'), ...mkBuildings(1, 'damaged'), ...mkBuildings(1, 'offline')],
        0,
      ),
    ).toBe(4 * GROWTH_PER_BUILDING);
  });

  it('ignores plans, ruins and ghosts (planned/under_construction/abandoned/destroyed)', () => {
    const ghosts = [
      ...mkBuildings(2, 'planned'),
      ...mkBuildings(2, 'under_construction'),
      ...mkBuildings(2, 'abandoned'),
      ...mkBuildings(2, 'destroyed'),
    ];
    expect(growthBudget(ghosts, 0)).toBe(0);
  });

  it('never goes negative on a malformed day', () => {
    expect(growthBudget([], -50)).toBe(0);
  });
});

describe('Wave D1.6 — tick-0 founding stock matches the frozen falloff', () => {
  it('adjacent-to-plaza 2–3, mid ring 0–1, edge 0 (Manhattan), across seeds', () => {
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed, day: 0, buildings: [] });
      for (const block of developableBlocks(plan)) {
        const d =
          Math.abs(Math.round(block.cx / BLOCK_PITCH)) +
          Math.abs(Math.round(block.cz / BLOCK_PITCH)); // plaza block is (0,0)
        const n = inBlock(plan, block, BUILDING_KEYS).length;
        const label = `seed ${seed}, block (${block.cx}, ${block.cz}), d=${d}`;
        if (d <= 1) {
          expect(n, label).toBeGreaterThanOrEqual(2);
          expect(n, label).toBeLessThanOrEqual(3);
        } else if (d === 2) {
          expect(n, label).toBeLessThanOrEqual(1);
        } else {
          expect(n, label).toBe(0);
        }
      }
    }
  });

  it('tick 0 is founded, not finished: pads cover every undeveloped lot', () => {
    const plan = computeCityPlan({ places: TOWN, day: 0, buildings: [] });
    const totalLots = developableBlocks(plan).length * LOTS_PER_BLOCK;
    const developed = developedInstances(plan).length;
    expect(developed).toBeGreaterThan(0); // founded…
    expect(developed).toBeLessThan(totalLots / 2); // …but visibly young
    expect(plan.emptyLots.length).toBe(totalLots - developed);
    // pads sit on generated blocks, inside the block footprint
    for (const pad of plan.emptyLots) {
      const nearestCx = BLOCK_CENTERS.reduce((a, b) => (Math.abs(b - pad.x) < Math.abs(a - pad.x) ? b : a));
      const nearestCz = BLOCK_CENTERS.reduce((a, b) => (Math.abs(b - pad.z) < Math.abs(a - pad.z) ? b : a));
      expect(Math.abs(pad.x - nearestCx)).toBeLessThanOrEqual(BLOCK_HALF);
      expect(Math.abs(pad.z - nearestCz)).toBeLessThanOrEqual(BLOCK_HALF);
      const block = plan.blocks.find((b) => b.cx === nearestCx && b.cz === nearestCz)!;
      expect(block.zone === 'landmark' || block.zone === 'park', `pad on ${block.zone} block`).toBe(false);
    }
  });
});

describe('Wave D1.6 — growth is monotone with a stable prefix', () => {
  const ladder: Array<{ day: number; buildings: Building[] }> = [
    { day: 0, buildings: [] },
    { day: 10, buildings: mkBuildings(2) },
    { day: 50, buildings: mkBuildings(6) },
    { day: 120, buildings: mkBuildings(10) },
    { day: 250, buildings: mkBuildings(12) },
    { day: MATURE_DAY, buildings: mkBuildings(20) },
  ];

  it('developed count never decreases as day/building count rise', () => {
    for (const seed of SEEDS) {
      let prev = -1;
      for (const rung of ladder) {
        const plan = computeCityPlan({ places: TOWN, city_seed: seed, ...rung });
        const n = developedInstances(plan).length;
        expect(n, `seed ${seed}, day ${rung.day}`).toBeGreaterThanOrEqual(prev);
        prev = n;
      }
    }
  });

  it('a lot once developed stays developed (scrubbing never teleports buildings)', () => {
    for (const seed of [1, 1337, 9001]) {
      let prev: Set<string> | null = null;
      for (const rung of ladder) {
        const ids = lotIds(computeCityPlan({ places: TOWN, city_seed: seed, ...rung }));
        if (prev) {
          for (const id of prev) {
            expect(ids.has(id), `seed ${seed}, day ${rung.day}: lost lot ${id}`).toBe(true);
          }
        }
        prev = ids;
      }
    }
  });

  it('developed + emptyLots partition the platted lots at every budget', () => {
    for (const rung of ladder) {
      const plan = computeCityPlan({ places: TOWN, city_seed: 1337, ...rung });
      const totalLots = developableBlocks(plan).length * LOTS_PER_BLOCK;
      expect(developedInstances(plan).length + plan.emptyLots.length).toBe(totalLots);
    }
  });

  it('caps at total lots: a mature run fills the city completely', () => {
    const plan = computeCityPlan({ places: TOWN, day: MATURE_DAY, buildings: mkBuildings(40) });
    const totalLots = developableBlocks(plan).length * LOTS_PER_BLOCK;
    expect(developedInstances(plan).length).toBe(totalLots);
    expect(plan.emptyLots.length).toBe(0);
  });
});

describe('Wave D1.6 — real buildings claim real lots', () => {
  const plan = computeCityPlan({ places: TOWN });

  it('every claiming place reserves exactly REAL_LOTS_PER_LANDMARK lots', () => {
    expect(Object.keys(plan.realLots).sort()).toEqual(TOWN.map((p) => p.id).sort());
    for (const lots of Object.values(plan.realLots)) {
      expect(lots).toHaveLength(REAL_LOTS_PER_LANDMARK);
    }
  });

  it('real lots sit INSIDE their landmark block — never on roads', () => {
    for (const [id, lots] of Object.entries(plan.realLots)) {
      const anchor = plan.landmarks[id];
      for (const lot of lots) {
        // inside the developable footprint ⇒ off the road by construction
        // (roads start at half-pitch 6.5; the footprint ends at 5.2)
        expect(Math.abs(lot.x - anchor.x), `${id} lot off-block`).toBeLessThanOrEqual(BLOCK_HALF - 0.5);
        expect(Math.abs(lot.z - anchor.z), `${id} lot off-block`).toBeLessThanOrEqual(BLOCK_HALF - 0.5);
      }
    }
  });

  it('real lots keep clear of the place anchor and of each other', () => {
    for (const [id, lots] of Object.entries(plan.realLots)) {
      const anchor = plan.landmarks[id];
      for (let i = 0; i < lots.length; i++) {
        expect(
          Math.hypot(lots[i].x - anchor.x, lots[i].z - anchor.z),
          `${id} lot ${i} on the anchor`,
        ).toBeGreaterThan(3.4);
        for (let j = i + 1; j < lots.length; j++) {
          expect(
            Math.hypot(lots[i].x - lots[j].x, lots[i].z - lots[j].z),
            `${id} lots ${i}/${j} overlap`,
          ).toBeGreaterThan(2.4);
        }
      }
    }
  });

  it('assignBuildingLots claims lots by stable id order', () => {
    const centers = new Map(TOWN.map((p) => [p.id, placeToWorld(p)]));
    const buildings = mkBuildings(4, 'operational', 'market');
    const spots = assignBuildingLots(plan, buildings, centers);
    const ids = buildings.map((b) => b.id).sort();
    ids.forEach((id, i) => {
      expect(spots.get(id)).toEqual({
        x: plan.realLots.market[i].x,
        z: plan.realLots.market[i].z,
      });
    });
    // input order must not matter
    const reversed = assignBuildingLots(plan, [...buildings].reverse(), centers);
    for (const id of ids) expect(reversed.get(id)).toEqual(spots.get(id));
  });

  it('overflow past the real lots falls back to the slotLayout ring', () => {
    const centers = new Map(TOWN.map((p) => [p.id, placeToWorld(p)]));
    const buildings = mkBuildings(REAL_LOTS_PER_LANDMARK + 3, 'operational', 'plaza');
    const spots = assignBuildingLots(plan, buildings, centers);
    const ids = buildings.map((b) => b.id).sort();
    const anchor = plan.landmarks.plaza;
    // first 6 on the real lots…
    for (let i = 0; i < REAL_LOTS_PER_LANDMARK; i++) {
      expect(spots.get(ids[i])).toEqual({
        x: plan.realLots.plaza[i].x,
        z: plan.realLots.plaza[i].z,
      });
    }
    // …the rest exactly where the EM-131 ring puts them, around the anchor
    const overflow = ids.slice(REAL_LOTS_PER_LANDMARK);
    const ring = slotLayout(anchor, overflow);
    for (const id of overflow) {
      expect(spots.get(id)).toEqual(ring.get(id));
      const p = spots.get(id)!;
      expect(Math.hypot(p.x - anchor.x, p.z - anchor.z)).toBeCloseTo(SLOT_BASE_RADIUS, 6);
      // the shrunken ring keeps overflow centers inside the block
      expect(Math.abs(p.x - anchor.x)).toBeLessThanOrEqual(BLOCK_HALF);
      expect(Math.abs(p.z - anchor.z)).toBeLessThanOrEqual(BLOCK_HALF);
    }
  });

  it('unknown locations fall back to the place center (or origin)', () => {
    const centers = new Map([['mystery', { x: 9, z: -9 }]]);
    const spots = assignBuildingLots(
      plan,
      [
        { id: 'a', location: 'mystery' },
        { id: 'b', location: 'nowhere' },
      ],
      centers,
    );
    const a = spots.get('a')!;
    expect(Math.hypot(a.x - 9, a.z + 9)).toBeCloseTo(SLOT_BASE_RADIUS, 6);
    const b = spots.get('b')!;
    expect(Math.hypot(b.x, b.z)).toBeCloseTo(SLOT_BASE_RADIUS, 6);
  });
});

describe('parks (greenbelt law)', () => {
  it('farm-district landmark blocks get a tree fill', () => {
    const plan = computeCityPlan({ places: TOWN });
    for (const id of ['commons', 'willow_pond', 'orchard', 'farmstead']) {
      const a = plan.landmarks[id];
      const block: CityBlock = { cx: a.x, cz: a.z, zone: 'landmark' };
      expect(
        inBlock(plan, block, ['tree_city']).length,
        `${id} block missing its park trees`,
      ).toBeGreaterThan(0);
    }
  });

  it('guarantees exactly one seeded park among the generated blocks', () => {
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed });
      const parks = plan.blocks.filter((b) => b.zone === 'park');
      expect(parks.length, `seed ${seed}`).toBe(1);
      // the park gets trees + benches, no buildings
      expect(inBlock(plan, parks[0], ['tree_city']).length, `seed ${seed}`).toBeGreaterThan(0);
      expect(inBlock(plan, parks[0], ['bench']).length, `seed ${seed}`).toBeGreaterThan(0);
      expect(inBlock(plan, parks[0], BUILDING_KEYS).length, `seed ${seed}`).toBe(0);
    }
  });
});

describe('city laws — grid, totality, bounds, connectivity, budget', () => {
  it('holds the full law pack across seeds (districted town)', () => {
    for (const seed of SEEDS) expectCityLaws(TOWN, seed);
  });

  it('builds the frozen road network: ring road + interior crosses, no dead ends', () => {
    const plan = computeCityPlan({ places: TOWN });
    // the fully connected 5×5 grid has no road_end caps
    expect(plan.pieces.road_end.length).toBe(0);
    // 4 outer ring corners
    expect(plan.pieces.road_corner.length).toBe(4);
    // 4×4 interior intersections are crosses
    expect(plan.pieces.road_cross.length).toBe(16);
    // 4 tees per outer edge (interior lines meeting the ring)
    expect(plan.pieces.road_tee.length).toBe(16);
    // every road tile sits on a frozen road line
    for (const r of roadInstances(plan)) {
      const onLine =
        ROAD_LINES.some((l) => Math.abs(r.x - l) < 1e-9) ||
        ROAD_LINES.some((l) => Math.abs(r.z - l) < 1e-9);
      expect(onLine, `road tile off the grid at (${r.x}, ${r.z})`).toBe(true);
    }
  });

  it('extent covers the outer ring road and stays compact (≈ the 66u world)', () => {
    const plan = computeCityPlan({ places: TOWN });
    expect(plan.extent).toBeCloseTo(2.5 * BLOCK_PITCH + TILE / 2); // 33.8
    expect(plan.extent * 2).toBeLessThan(70);
  });

  it('stays within the instance budget across seeds (at the dense cap)', () => {
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed, day: MATURE_DAY });
      expect(countInstances(plan), `seed ${seed}`).toBeLessThanOrEqual(MAX_CITY_INSTANCES);
    }
  });
});

describe('pre-Wave-C snapshots (district-less)', () => {
  it('holds the full law pack for a legacy town across seeds', () => {
    for (const seed of [1, 1337, 9001]) expectCityLaws(LEGACY, seed);
  });

  it('legacy places still claim landmark blocks (kind fallback zoning)', () => {
    const plan = computeCityPlan({ places: LEGACY });
    expect(Object.keys(plan.landmarks).sort()).toEqual(LEGACY.map((p) => p.id).sort());
    expect(plan.blocks.filter((b) => b.zone === 'landmark').length).toBe(5);
  });

  it('produces a deterministic plan with the default seed', () => {
    const a = computeCityPlan({ places: LEGACY });
    const b = computeCityPlan({ places: LEGACY });
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
    expect(countInstances(a)).toBeGreaterThan(0);
  });
});

describe('degenerate worlds', () => {
  it('handles an empty place list: a full grid, every block developed at cap', () => {
    const plan = computeCityPlan({ places: [], day: MATURE_DAY });
    expect(Object.keys(plan.pieces)).toEqual([...CITY_PIECE_KEYS]);
    expect(plan.blocks.length).toBe(25);
    expect(plan.landmarks).toEqual({});
    expect(plan.realLots).toEqual({});
    expect(plan.blocks.filter((b) => b.zone === 'landmark').length).toBe(0);
    expect(plan.blocks.filter((b) => b.zone === 'park').length).toBe(1);
    for (const block of plan.blocks.filter((b) => b.zone !== 'park')) {
      expect(inBlock(plan, block, BUILDING_KEYS).length).toBe(LOTS_PER_BLOCK);
    }
    expect(countInstances(plan)).toBeLessThanOrEqual(MAX_CITY_INSTANCES);
  });

  it('handles an empty place list at tick 0: founded around the origin', () => {
    const plan = computeCityPlan({ places: [], day: 0 });
    expect(developedInstances(plan).length).toBeGreaterThan(0);
    expect(plan.emptyLots.length).toBeGreaterThan(0);
  });

  it('handles a single place', () => {
    const plan = computeCityPlan({ places: [TOWN[0]], city_seed: 5 });
    expect(Object.keys(plan.pieces)).toEqual([...CITY_PIECE_KEYS]);
    expect(plan.blocks.filter((b) => b.zone === 'landmark').length).toBe(1);
    expect(plan.realLots.plaza).toHaveLength(REAL_LOTS_PER_LANDMARK);
    expect(countInstances(plan)).toBeLessThanOrEqual(MAX_CITY_INSTANCES);
  });

  it('snaps out-of-grid positions to the grid edge (clamped, never off-world)', () => {
    const far = snapToBlockCenter(500, -500);
    expect(far).toEqual({ x: 2 * BLOCK_PITCH, z: -2 * BLOCK_PITCH });
  });
});
