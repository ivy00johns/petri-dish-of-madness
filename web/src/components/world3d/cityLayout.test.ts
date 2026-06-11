/**
 * cityLayout tests — Wave D1.5 generator laws + the EM-155 frontend
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
 *   • density: every non-park generated block has ZERO empty lots
 *     (LOTS_PER_BLOCK buildings — an empty road-framed block is a violation)
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
import type { Place } from '../../types';
import { placeToWorld } from './worldSpace';
import {
  TILE,
  BLOCK_PITCH,
  BLOCK_HALF,
  GRID_BLOCKS,
  LOTS_PER_BLOCK,
  CITY_PIECE_KEYS,
  CITY_ZONES,
  DEFAULT_CITY_SEED,
  MAX_CITY_INSTANCES,
  computeCityPlan,
  computeLandmarks,
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

/** The shared law pack: grid, density, totality, bounds, connectivity, budget. */
function expectCityLaws(places: Place[], seed: number) {
  const plan = computeCityPlan({ places, city_seed: seed });
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

  // DENSITY LAW: every non-park generated block has ZERO empty lots
  for (const block of plan.blocks.filter((b) => b.zone !== 'landmark' && b.zone !== 'park')) {
    expect(
      inBlock(plan, block, BUILDING_KEYS).length,
      `${label}: empty lots on generated block (${block.cx}, ${block.cz}) [${block.zone}]`,
    ).toBe(LOTS_PER_BLOCK);
  }

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

  it('every landmark block has zero generated buildings', () => {
    for (const seed of SEEDS) {
      const p = computeCityPlan({ places: TOWN, city_seed: seed });
      for (const block of p.blocks.filter((b) => b.zone === 'landmark')) {
        expect(
          inBlock(p, block, BUILDING_KEYS).length,
          `seed ${seed}: building inside landmark block (${block.cx}, ${block.cz})`,
        ).toBe(0);
      }
    }
  });
});

describe('density — every block developed (the EW law)', () => {
  it('every non-park generated block has zero empty lots, across seeds', () => {
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed });
      for (const block of plan.blocks.filter((b) => b.zone !== 'landmark' && b.zone !== 'park')) {
        expect(
          inBlock(plan, block, BUILDING_KEYS).length,
          `seed ${seed}: empty lots at (${block.cx}, ${block.cz})`,
        ).toBe(LOTS_PER_BLOCK);
      }
    }
  });

  it('developed blocks use zone-matched building keys', () => {
    const plan = computeCityPlan({ places: TOWN });
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

  it('stays within the instance budget across seeds', () => {
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed });
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
  it('handles an empty place list: a full grid, every block developed', () => {
    const plan = computeCityPlan({ places: [] });
    expect(Object.keys(plan.pieces)).toEqual([...CITY_PIECE_KEYS]);
    expect(plan.blocks.length).toBe(25);
    expect(plan.landmarks).toEqual({});
    expect(plan.blocks.filter((b) => b.zone === 'landmark').length).toBe(0);
    expect(plan.blocks.filter((b) => b.zone === 'park').length).toBe(1);
    for (const block of plan.blocks.filter((b) => b.zone !== 'park')) {
      expect(inBlock(plan, block, BUILDING_KEYS).length).toBe(LOTS_PER_BLOCK);
    }
    expect(countInstances(plan)).toBeLessThanOrEqual(MAX_CITY_INSTANCES);
  });

  it('handles a single place', () => {
    const plan = computeCityPlan({ places: [TOWN[0]], city_seed: 5 });
    expect(Object.keys(plan.pieces)).toEqual([...CITY_PIECE_KEYS]);
    expect(plan.blocks.filter((b) => b.zone === 'landmark').length).toBe(1);
    expect(countInstances(plan)).toBeLessThanOrEqual(MAX_CITY_INSTANCES);
  });

  it('snaps out-of-grid positions to the grid edge (clamped, never off-world)', () => {
    const far = snapToBlockCenter(500, -500);
    expect(far).toEqual({ x: 2 * BLOCK_PITCH, z: -2 * BLOCK_PITCH });
  });
});
