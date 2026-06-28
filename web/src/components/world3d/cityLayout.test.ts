/**
 * cityLayout tests — Wave D1.5 generator laws + EM-174 ("if it's a building
 * it should have a purpose") + the EM-155 frontend determinism invariant:
 *   • EM-155 determinism: same snapshot + same seed ⇒ JSON.stringify-identical
 *     plan (live/replay/fork all call the same pure function); a re-parsed
 *     (replayed/forked) snapshot yields the byte-identical plan; the plan is
 *     keyed on (places, city_seed) ONLY — buildings/day never shape it
 *   • seed sensitivity: different city_seed ⇒ different plan
 *   • city_seed absent (pre-W15 snapshot) ⇒ default seed 1337
 *   • the frozen grid: 5×5 blocks at pitch 13.0, centered on the origin,
 *     roads between all blocks + an outer ring road
 *   • landmarks: every place claims a block (snap < 1.0u for the shipped
 *     town), landmark blocks carry zone 'landmark'
 *   • EM-174 — every building has a purpose:
 *       – ZERO generated building instances, ever, across seeds (the D1.5/
 *         D1.6 zone-building fill is retired; the 23-key vocabulary stays
 *         frozen for the registry)
 *       – every lot is either a platted pad (emptyLots/blockLots), a park
 *         fill, or claimable by a real W7 building
 *       – realLots: 6 street-front lots inside each landmark block, never on
 *         roads; assignBuildingLots claims them by stable id order, then
 *         nearest-block overflow onto platted lots (deterministic: block-
 *         center distance to the place, then plan block order, then lot
 *         index), slot-ring fallback only when the entire city is full
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
import type { Building, Place, Neighborhood } from '../../types';
import { placeToWorld, slotLayout, SLOT_BASE_RADIUS } from './worldSpace';
import {
  TILE,
  BLOCK_PITCH,
  BLOCK_HALF,
  GRID_BLOCKS,
  LOTS_PER_BLOCK,
  REAL_LOTS_PER_LANDMARK,
  CITY_PIECE_KEYS,
  CITY_ZONES,
  DEFAULT_CITY_SEED,
  MAX_CITY_INSTANCES,
  STREET_NAME_BANK_SIZE,
  STREET_NAME_STEMS,
  STREET_NAME_SUFFIXES,
  assignBuildingLots,
  computeCityPlan,
  computeLandmarks,
  computeStreets,
  snapToBlockCenter,
  streetNameAt,
  type CityInstance,
  type CityPlan,
  type CityBlock,
  type CityPieceKey,
  type CityWorld,
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

/** Synthetic W7 buildings (only id/location matter to lot assignment). */
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

const ROAD_KEYS: CityPieceKey[] = ['road_straight', 'road_corner', 'road_tee', 'road_cross', 'road_end'];
/** The retired zone-building vocabulary — registry keys the generator must
 *  NEVER emit (EM-174: only landmarks and real W7 buildings are buildings). */
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

/** Generated developable (non-park, non-landmark) blocks of a plan. */
function developableBlocks(plan: CityPlan): CityBlock[] {
  return plan.blocks.filter((b) => b.zone !== 'landmark' && b.zone !== 'park');
}

/** Pads of plan.emptyLots whose center is inside the block footprint. */
function padsInBlock(plan: CityPlan, block: CityBlock): CityInstance[] {
  return plan.emptyLots.filter(
    (p) =>
      Math.abs(p.x - block.cx) <= BLOCK_HALF + 1e-9 &&
      Math.abs(p.z - block.cz) <= BLOCK_HALF + 1e-9,
  );
}

/** The shared law pack: grid, EM-174 purpose law, totality, bounds,
 *  connectivity, budget. */
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

  // a real city came out (roads + props + parks + cars)
  expect(countInstances(plan), label).toBeGreaterThan(300);

  for (const inst of [...allInstances(plan), ...plan.emptyLots]) {
    expect(Number.isFinite(inst.x), label).toBe(true);
    expect(Number.isFinite(inst.z), label).toBe(true);
    expect(Number.isFinite(inst.rotY), label).toBe(true);
    if (inst.s !== undefined) expect(inst.s).toBeGreaterThan(0);
    // bounds: within the extent (Chebyshev from the world origin)
    expect(Math.abs(inst.x), label).toBeLessThanOrEqual(plan.extent);
    expect(Math.abs(inst.z), label).toBeLessThanOrEqual(plan.extent);
  }

  // EM-174 PURPOSE LAW: the generator emits ZERO buildings, anywhere, ever
  for (const key of BUILDING_KEYS) {
    expect(plan.pieces[key], `${label}: generated ${key} emitted`).toEqual([]);
  }

  // …and every developable lot is a platted pad instead
  expect(plan.emptyLots.length, label).toBe(developableBlocks(plan).length * LOTS_PER_BLOCK);
  for (const block of developableBlocks(plan)) {
    expect(
      padsInBlock(plan, block).length,
      `${label}: missing pads on block (${block.cx}, ${block.cz})`,
    ).toBe(LOTS_PER_BLOCK);
  }

  // park blocks: trees, never pads
  for (const block of plan.blocks.filter((b) => b.zone === 'park')) {
    expect(padsInBlock(plan, block).length, label).toBe(0);
    expect(inBlock(plan, block, ['tree_city']).length, label).toBeGreaterThan(0);
  }

  // landmark blocks: no pads either (the place + its realLots own the block)
  for (const block of plan.blocks.filter((b) => b.zone === 'landmark')) {
    expect(padsInBlock(plan, block).length, label).toBe(0);
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

  // EM-188: 12 named streets (6 per axis), unique names, anchors in bounds
  expect(plan.streets.length, label).toBe(12);
  expect(new Set(plan.streets.map((s) => s.name)).size, label).toBe(12);
  for (const s of plan.streets) {
    for (const a of s.labels) {
      expect(Math.abs(a.x), label).toBeLessThanOrEqual(plan.extent);
      expect(Math.abs(a.z), label).toBeLessThanOrEqual(plan.extent);
    }
  }
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

  it('EM-188: street names are part of the pinned byte-identical output', () => {
    // Names ride the plan itself, so the stringify invariants above already
    // pin them — this makes the law explicit: same seed ⇒ identical names…
    expect(computeStreets(1337)).toEqual(computeStreets(1337));
    const plan = computeCityPlan({ places: TOWN, city_seed: 1337 });
    expect(plan.streets).toEqual(computeStreets(1337));
    const json = JSON.stringify(plan);
    for (const s of plan.streets) expect(json).toContain(s.name);
    // …and different seed ⇒ different names (seed sensitivity).
    const names = (seed: number) => computeStreets(seed).map((s) => s.name).join('|');
    expect(names(1)).not.toBe(names(2));
    expect(names(1337)).not.toBe(names(9001));
  });

  it('is keyed on (places, city_seed) ONLY — buildings/day never shape the plan (EM-174)', () => {
    // A full WorldState snapshot carries buildings/day/tick alongside the
    // plan inputs; the generator must ignore everything but (places, seed).
    const noisy = {
      places: TOWN,
      city_seed: 1337,
      day: 73,
      buildings: mkBuildings(5),
      tick: 4096,
    } as CityWorld;
    expect(JSON.stringify(computeCityPlan(noisy))).toBe(
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
});

// ── EM-174: every building has a purpose ─────────────────────────────────────

describe('EM-174 — zero generated buildings, ever', () => {
  it('emits no zone-building instance for any seed (the fill is retired)', () => {
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed });
      for (const key of BUILDING_KEYS) {
        expect(plan.pieces[key], `seed ${seed}: ${key}`).toEqual([]);
      }
    }
  });

  it('emits no zone-building instance for legacy and degenerate towns either', () => {
    for (const places of [LEGACY, [], [TOWN[0]]]) {
      const plan = computeCityPlan({ places, city_seed: 1337 });
      for (const key of BUILDING_KEYS) expect(plan.pieces[key]).toEqual([]);
    }
  });

  it('the 23-key vocabulary stays frozen (registry keys survive, just unemitted)', () => {
    const plan = computeCityPlan({ places: TOWN });
    expect(Object.keys(plan.pieces)).toEqual([...CITY_PIECE_KEYS]);
    expect(CITY_PIECE_KEYS).toContain('com_a'); // still registry vocabulary
    expect(CITY_PIECE_KEYS).toContain('civic_a');
  });
});

describe('EM-174 — every lot is a pad, a park fill, or claimed by a real building', () => {
  it('every developable lot renders as a platted pad from day 0, across seeds', () => {
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed });
      const developable = developableBlocks(plan);
      expect(plan.emptyLots.length, `seed ${seed}`).toBe(developable.length * LOTS_PER_BLOCK);
      for (const block of developable) {
        expect(
          padsInBlock(plan, block).length,
          `seed ${seed}: block (${block.cx}, ${block.cz})`,
        ).toBe(LOTS_PER_BLOCK);
      }
    }
  });

  it('blockLots groups exactly the emptyLots pads, one entry per developable block', () => {
    const plan = computeCityPlan({ places: TOWN, city_seed: 1337 });
    expect(plan.blockLots.length).toBe(developableBlocks(plan).length);
    for (const b of plan.blockLots) {
      expect(BLOCK_CENTERS).toContain(b.cx);
      expect(BLOCK_CENTERS).toContain(b.cz);
      expect(b.lots).toHaveLength(LOTS_PER_BLOCK);
      // grouped lots sit inside their own block footprint
      for (const lot of b.lots) {
        expect(Math.abs(lot.x - b.cx)).toBeLessThanOrEqual(BLOCK_HALF);
        expect(Math.abs(lot.z - b.cz)).toBeLessThanOrEqual(BLOCK_HALF);
      }
    }
    expect(plan.blockLots.flatMap((b) => b.lots)).toEqual(plan.emptyLots);
  });

  it('park and landmark blocks carry no pads; parks carry trees', () => {
    const plan = computeCityPlan({ places: TOWN });
    for (const block of plan.blocks.filter((b) => b.zone === 'park' || b.zone === 'landmark')) {
      expect(padsInBlock(plan, block).length, `(${block.cx}, ${block.cz})`).toBe(0);
    }
    for (const block of plan.blocks.filter((b) => b.zone === 'park')) {
      expect(inBlock(plan, block, ['tree_city']).length).toBeGreaterThan(0);
    }
  });

  it('overflow claims land exactly on platted pads (a building replaces/sits on its pad)', () => {
    const plan = computeCityPlan({ places: TOWN });
    const centers = new Map(TOWN.map((p) => [p.id, placeToWorld(p)]));
    const buildings = mkBuildings(REAL_LOTS_PER_LANDMARK + 5, 'operational', 'market');
    const spots = assignBuildingLots(plan, buildings, centers);
    const padSet = new Set(plan.emptyLots.map((p) => `${p.x},${p.z}`));
    const ids = buildings.map((b) => b.id).sort();
    for (const id of ids.slice(REAL_LOTS_PER_LANDMARK)) {
      const s = spots.get(id)!;
      expect(padSet.has(`${s.x},${s.z}`), `${id} not on a platted pad`).toBe(true);
    }
  });
});

describe('EM-174 — real buildings claim real lots', () => {
  const plan = computeCityPlan({ places: TOWN });
  const centers = new Map(TOWN.map((p) => [p.id, placeToWorld(p)]));

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

  it('assignBuildingLots claims the landmark block first, by stable id order', () => {
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

  it('overflow round-robins across the NEAREST blocks: lot index, then block-center distance (EM-181)', () => {
    const buildings = mkBuildings(REAL_LOTS_PER_LANDMARK + 5, 'operational', 'plaza');
    const spots = assignBuildingLots(plan, buildings, centers);
    const ids = buildings.map((b) => b.id).sort();
    const anchor = plan.landmarks.plaza;
    // first 6 on the landmark block's real lots…
    for (let i = 0; i < REAL_LOTS_PER_LANDMARK; i++) {
      expect(spots.get(ids[i])).toEqual({
        x: plan.realLots.plaza[i].x,
        z: plan.realLots.plaza[i].z,
      });
    }
    // …the rest on the deterministic round-robin walk: lot index 0 of every
    // block (nearest-first), then lot index 1, and so on (EM-181 spread sooner).
    const blockOrder = [...plan.blockLots.keys()].sort((a, b) => {
      const da = Math.hypot(plan.blockLots[a].cx - anchor.x, plan.blockLots[a].cz - anchor.z);
      const db = Math.hypot(plan.blockLots[b].cx - anchor.x, plan.blockLots[b].cz - anchor.z);
      return da - db || a - b;
    });
    const maxLots = Math.max(...plan.blockLots.map((b) => b.lots.length));
    const expected: Array<{ x: number; z: number }> = [];
    for (let li = 0; li < maxLots; li++) {
      for (const bi of blockOrder) {
        if (li < plan.blockLots[bi].lots.length) expected.push(plan.blockLots[bi].lots[li]);
      }
    }
    const overflow = ids.slice(REAL_LOTS_PER_LANDMARK);
    overflow.forEach((id, i) => {
      expect(spots.get(id), `overflow ${i}`).toEqual({ x: expected[i].x, z: expected[i].z });
    });
    // overflow never lands on a road: inside some block footprint
    for (const id of overflow) {
      const s = spots.get(id)!;
      const nearestCx = BLOCK_CENTERS.reduce((a, b) => (Math.abs(b - s.x) < Math.abs(a - s.x) ? b : a));
      const nearestCz = BLOCK_CENTERS.reduce((a, b) => (Math.abs(b - s.z) < Math.abs(a - s.z) ? b : a));
      expect(Math.abs(s.x - nearestCx)).toBeLessThanOrEqual(BLOCK_HALF);
      expect(Math.abs(s.z - nearestCz)).toBeLessThanOrEqual(BLOCK_HALF);
    }
  });

  it('overflow assignment is deterministic and input-order independent', () => {
    const a = mkBuildings(REAL_LOTS_PER_LANDMARK + 7, 'operational', 'plaza');
    const spots1 = assignBuildingLots(plan, a, centers);
    const spots2 = assignBuildingLots(plan, [...a].reverse(), centers);
    const spots3 = assignBuildingLots(plan, a, centers);
    for (const b of a) {
      expect(spots2.get(b.id)).toEqual(spots1.get(b.id));
      expect(spots3.get(b.id)).toEqual(spots1.get(b.id));
    }
  });

  it('two overflowing places never share a lot, resolved deterministically', () => {
    const atPlaza = mkBuildings(REAL_LOTS_PER_LANDMARK + 4, 'operational', 'plaza');
    const atMarket = mkBuildings(REAL_LOTS_PER_LANDMARK + 4, 'operational', 'market')
      .map((b) => ({ ...b, id: `m_${b.id}` }));
    const all = [...atPlaza, ...atMarket];
    const spots = assignBuildingLots(plan, all, centers);
    const seen = new Map<string, string>();
    for (const b of all) {
      const s = spots.get(b.id)!;
      const key = `${s.x},${s.z}`;
      expect(seen.has(key), `${b.id} shares a lot with ${seen.get(key)}`).toBe(false);
      seen.set(key, b.id);
    }
    // shuffled input ⇒ identical claims (sorted-location resolution)
    const shuffled = [...all].reverse();
    const spotsB = assignBuildingLots(plan, shuffled, centers);
    for (const b of all) expect(spotsB.get(b.id)).toEqual(spots.get(b.id));
  });

  it('slot-ring fallback fires ONLY when the entire city is full', () => {
    const capacity =
      REAL_LOTS_PER_LANDMARK + plan.blockLots.reduce((n, b) => n + b.lots.length, 0);
    const buildings = mkBuildings(capacity + 3, 'operational', 'plaza');
    const spots = assignBuildingLots(plan, buildings, centers);
    const ids = buildings.map((b) => b.id).sort();
    const anchor = plan.landmarks.plaza;
    // everything within capacity sits on a real or platted lot (no ring)
    const padSet = new Set([
      ...plan.emptyLots.map((p) => `${p.x},${p.z}`),
      ...plan.realLots.plaza.map((p) => `${p.x},${p.z}`),
    ]);
    for (const id of ids.slice(0, capacity)) {
      const s = spots.get(id)!;
      expect(padSet.has(`${s.x},${s.z}`), `${id} should be on a lot`).toBe(true);
    }
    // the overflow-of-the-overflow rings the anchor (EM-131 slotLayout)
    const ringIds = ids.slice(capacity);
    const ring = slotLayout(anchor, ringIds);
    for (const id of ringIds) {
      expect(spots.get(id)).toEqual(ring.get(id));
      const p = spots.get(id)!;
      expect(Math.hypot(p.x - anchor.x, p.z - anchor.z)).toBeCloseTo(SLOT_BASE_RADIUS, 6);
    }
  });

  it('unknown locations claim the platted lots nearest their center', () => {
    const mystery = new Map([['mystery', { x: 9, z: -9 }]]);
    const spots = assignBuildingLots(
      plan,
      [
        { id: 'a', location: 'mystery' },
        { id: 'b', location: 'nowhere' },
      ],
      mystery,
    );
    // 'mystery' has a center: nearest block to (9, -9); 'nowhere' falls back
    // to the origin — both land on real platted pads, not floating rings.
    const padSet = new Set(plan.emptyLots.map((p) => `${p.x},${p.z}`));
    for (const id of ['a', 'b']) {
      const s = spots.get(id)!;
      expect(padSet.has(`${s.x},${s.z}`), `${id} not on a platted pad`).toBe(true);
    }
    // and the claims are the deterministic nearest-block walk for each center
    const nearestTo = (c: { x: number; z: number }) =>
      [...plan.blockLots.keys()].sort((x, y) => {
        const dx = Math.hypot(plan.blockLots[x].cx - c.x, plan.blockLots[x].cz - c.z);
        const dy = Math.hypot(plan.blockLots[y].cx - c.x, plan.blockLots[y].cz - c.z);
        return dx - dy || x - y;
      })[0];
    const aLot = plan.blockLots[nearestTo({ x: 9, z: -9 })].lots[0];
    expect(spots.get('a')).toEqual({ x: aLot.x, z: aLot.z });
    const bLot = plan.blockLots[nearestTo({ x: 0, z: 0 })].lots[0];
    expect(spots.get('b')).toEqual({ x: bLot.x, z: bLot.z });
  });
});

// ── EM-182 — lot assignment keys off building.location, not the builder ──────
//
// Wave K pulls EM-182 in: a building's chosen `location` (a place / district)
// decides its lot, exactly like a prop's `place`. assignBuildingLots already
// keys purely off building.location + the place centers (no agent input
// anywhere), so a building proposed for a district the builder isn't standing
// in lands in THAT district. This locks that contract.

describe('EM-182 — a building renders at its chosen location, not the agent\'s', () => {
  const plan = computeCityPlan({ places: TOWN });
  const centers = new Map(TOWN.map((p) => [p.id, placeToWorld(p)]));

  it('a building at place X lands in X\'s landmark block (regardless of any agent)', () => {
    // One building each at market and townhall — different districts. Each must
    // claim its OWN place's first real lot. The agent who proposed it is
    // irrelevant: assignBuildingLots never sees an agent.
    const buildings = [
      { id: 'shop', location: 'market' },
      { id: 'hall', location: 'townhall' },
    ];
    const spots = assignBuildingLots(plan, buildings, centers);
    expect(spots.get('shop')).toEqual({
      x: plan.realLots.market[0].x,
      z: plan.realLots.market[0].z,
    });
    expect(spots.get('hall')).toEqual({
      x: plan.realLots.townhall[0].x,
      z: plan.realLots.townhall[0].z,
    });
    // …and each lot really is inside its own landmark block, not the other's.
    const near = (pt: { x: number; z: number }, anchor: { x: number; z: number }) =>
      Math.hypot(pt.x - anchor.x, pt.z - anchor.z);
    expect(near(spots.get('shop')!, plan.landmarks.market))
      .toBeLessThan(near(spots.get('shop')!, plan.landmarks.townhall));
    expect(near(spots.get('hall')!, plan.landmarks.townhall))
      .toBeLessThan(near(spots.get('hall')!, plan.landmarks.market));
  });

  it('changing ONLY a building\'s location moves its lot to the new place', () => {
    const atMarket = assignBuildingLots(plan, [{ id: 'b', location: 'market' }], centers);
    const atTownhall = assignBuildingLots(plan, [{ id: 'b', location: 'townhall' }], centers);
    expect(atMarket.get('b')).toEqual({
      x: plan.realLots.market[0].x,
      z: plan.realLots.market[0].z,
    });
    expect(atTownhall.get('b')).toEqual({
      x: plan.realLots.townhall[0].x,
      z: plan.realLots.townhall[0].z,
    });
    expect(atMarket.get('b')).not.toEqual(atTownhall.get('b'));
  });
});

// ── EM-188: street names ─────────────────────────────────────────────────────

describe('EM-188 — seeded street names on the frozen grid', () => {
  /** The 6 frozen road centerlines per axis (between blocks + outer ring). */
  const LINES = [-2.5, -1.5, -0.5, 0.5, 1.5, 2.5].map((k) => k * BLOCK_PITCH);
  const RING = 2.5 * BLOCK_PITCH; // ±32.5: the outer ring road

  it('names exactly 12 streets — 6 ns + 6 ew, one per frozen road line', () => {
    const streets = computeStreets(1337);
    expect(streets).toHaveLength(12);
    for (const axis of ['ns', 'ew'] as const) {
      const ats = streets.filter((s) => s.axis === axis).map((s) => s.at);
      expect(ats, axis).toEqual(LINES);
    }
  });

  it('is deterministic in the seed and independent of places (pure seed data)', () => {
    for (const seed of SEEDS) {
      const fromTown = computeCityPlan({ places: TOWN, city_seed: seed }).streets;
      const fromLegacy = computeCityPlan({ places: LEGACY, city_seed: seed }).streets;
      const fromEmpty = computeCityPlan({ places: [], city_seed: seed }).streets;
      expect(fromTown, `seed ${seed}`).toEqual(computeStreets(seed));
      expect(fromLegacy, `seed ${seed}`).toEqual(fromTown);
      expect(fromEmpty, `seed ${seed}`).toEqual(fromTown);
    }
  });

  it('never duplicates a name within a city, across seeds (dedupe proof)', () => {
    // The bank (24 stems × 4 suffixes = 96) dwarfs the 12 streets, so the
    // deterministic walk-forward dedupe always finds a free name…
    expect(STREET_NAME_BANK_SIZE).toBe(
      STREET_NAME_STEMS.length * STREET_NAME_SUFFIXES.length,
    );
    expect(STREET_NAME_BANK_SIZE).toBeGreaterThanOrEqual(12 * 2);
    // …and every generated city carries 12 DISTINCT names.
    for (const seed of [...SEEDS, 3, 11, 99, 256, 4096]) {
      const names = computeStreets(seed).map((s) => s.name);
      expect(new Set(names).size, `seed ${seed}`).toBe(names.length);
    }
  });

  it('draws every name from the two-part bank (stem × Lane/Row/Way/Street)', () => {
    const stems = new Set<string>(STREET_NAME_STEMS);
    const suffixes = new Set<string>(STREET_NAME_SUFFIXES);
    for (const seed of SEEDS) {
      for (const s of computeStreets(seed)) {
        const parts = s.name.split(' ');
        expect(parts, `${s.name} (seed ${seed})`).toHaveLength(2);
        expect(stems.has(parts[0]), `${s.name}: unknown stem`).toBe(true);
        expect(suffixes.has(parts[1]), `${s.name}: unknown suffix`).toBe(true);
      }
    }
    // the bank indexer covers all 96 combos without repeats
    const all = Array.from({ length: STREET_NAME_BANK_SIZE }, (_, k) => streetNameAt(k));
    expect(new Set(all).size).toBe(STREET_NAME_BANK_SIZE);
  });

  it('labels are SPARSE: only interior avenues, mid-block, never intersections', () => {
    for (const s of computeStreets(1337)) {
      if (Math.abs(s.at) === RING) {
        // the outer ring road is not a main lane and stays unlabeled
        expect(s.main, s.id).toBe(false);
        expect(s.labels, s.id).toEqual([]);
        continue;
      }
      expect(s.main, s.id).toBe(true);
      expect(s.labels.length, s.id).toBe(3);
      for (const a of s.labels) {
        // ON the road centerline…
        expect(s.axis === 'ns' ? a.x : a.z, s.id).toBe(s.at);
        // …at a block-center row on the cross axis (mid-block — road lines
        // sit at half-pitch offsets, so this can never be an intersection)
        const cross = s.axis === 'ns' ? a.z : a.x;
        expect([-2 * BLOCK_PITCH, 0, 2 * BLOCK_PITCH], s.id).toContain(cross);
        expect(LINES, `${s.id}: anchor on an intersection`).not.toContain(cross);
      }
    }
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
      // the park gets trees + benches, no pads
      expect(inBlock(plan, parks[0], ['tree_city']).length, `seed ${seed}`).toBeGreaterThan(0);
      expect(inBlock(plan, parks[0], ['bench']).length, `seed ${seed}`).toBeGreaterThan(0);
      expect(padsInBlock(plan, parks[0]).length, `seed ${seed}`).toBe(0);
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
  it('handles an empty place list: a full platted grid, zero buildings', () => {
    const plan = computeCityPlan({ places: [] });
    expect(Object.keys(plan.pieces)).toEqual([...CITY_PIECE_KEYS]);
    expect(plan.blocks.length).toBe(25);
    expect(plan.landmarks).toEqual({});
    expect(plan.realLots).toEqual({});
    expect(plan.blocks.filter((b) => b.zone === 'landmark').length).toBe(0);
    expect(plan.blocks.filter((b) => b.zone === 'park').length).toBe(1);
    for (const key of BUILDING_KEYS) expect(plan.pieces[key]).toEqual([]);
    expect(plan.emptyLots.length).toBe(24 * LOTS_PER_BLOCK);
    expect(countInstances(plan)).toBeLessThanOrEqual(MAX_CITY_INSTANCES);
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

// ── EM-123: zoned districts deepen as megaprojects complete ──────────────────
// (reuses the file-level countInstances helper defined above.)

/** All five hand-town districts at tier 1 (the derivable baseline). */
const NB_BASELINE: Neighborhood[] = [
  { id: 'core', name: 'Core', zone_kind: 'civic', tier: 1, progress: 0 },
  { id: 'market', name: 'Market', zone_kind: 'market', tier: 1, progress: 0 },
  { id: 'civic', name: 'Civic', zone_kind: 'civic', tier: 1, progress: 0 },
  { id: 'residential', name: 'Residential', zone_kind: 'residential', tier: 1, progress: 0 },
  { id: 'farm', name: 'Farm', zone_kind: 'farm', tier: 1, progress: 0 },
];

const withTier = (id: string, tier: number): Neighborhood[] =>
  NB_BASELINE.map((n) => (n.id === id ? { ...n, tier } : n));

describe('EM-123 — district maturity drives extra street life', () => {
  it('tier-1 (or absent) neighborhoods ⇒ byte-identical to the pre-EM-123 plan', () => {
    const base = JSON.stringify(computeCityPlan({ places: TOWN, city_seed: 1337 }));
    // Explicit all-tier-1 neighborhoods change nothing.
    expect(JSON.stringify(computeCityPlan({ places: TOWN, city_seed: 1337, neighborhoods: NB_BASELINE }))).toBe(base);
    // null/undefined neighborhoods change nothing.
    expect(JSON.stringify(computeCityPlan({ places: TOWN, city_seed: 1337, neighborhoods: null }))).toBe(base);
  });

  it('a matured district emits MORE instances (a strict superset of tier 1)', () => {
    const base = countInstances(computeCityPlan({ places: TOWN, city_seed: 1337 }));
    const grownFarm = countInstances(
      computeCityPlan({ places: TOWN, city_seed: 1337, neighborhoods: withTier('farm', 4) }));
    const grownMarket = countInstances(
      computeCityPlan({ places: TOWN, city_seed: 1337, neighborhoods: withTier('market', 4) }));
    // Farm gains park trees; market gains curb props — both above baseline.
    expect(grownFarm).toBeGreaterThan(base);
    expect(grownMarket).toBeGreaterThan(base);
  });

  it('growth is monotonic in tier (each step adds, never removes)', () => {
    const at = (t: number) =>
      countInstances(computeCityPlan({ places: TOWN, city_seed: 1337, neighborhoods: withTier('farm', t) }));
    expect(at(2)).toBeGreaterThan(at(1));
    expect(at(3)).toBeGreaterThanOrEqual(at(2));
    expect(at(4)).toBeGreaterThanOrEqual(at(3));
  });

  it('is deterministic + insensitive to neighborhood array ordering', () => {
    const nb = withTier('farm', 3);
    const a = computeCityPlan({ places: TOWN, city_seed: 7, neighborhoods: nb });
    const b = computeCityPlan({ places: TOWN, city_seed: 7, neighborhoods: [...nb].reverse() });
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it('only the matured district changes — others stay at the baseline plan', () => {
    // Counting the farm park-tree pieces in isolation: a market-only bump must
    // not touch them, proving growth is district-scoped.
    const base = computeCityPlan({ places: TOWN, city_seed: 1337 });
    const marketGrown = computeCityPlan({ places: TOWN, city_seed: 1337, neighborhoods: withTier('market', 4) });
    expect(marketGrown.pieces.tree_city.length).toBe(base.pieces.tree_city.length);
    // …but its curb props grew.
    const curb = (p: CityPlan) => p.pieces.lamp.length + p.pieces.bin.length + p.pieces.hydrant.length + p.pieces.bench.length;
    expect(curb(marketGrown)).toBeGreaterThan(curb(base));
  });

  it('a per-place zone_kind override re-zones that block (residential → commercial)', () => {
    const rezoned: Place[] = TOWN.map((p) =>
      p.id === 'home' ? { ...p, zone_kind: 'industrial' } : p);
    const base = computeCityPlan({ places: TOWN, city_seed: 1337 });
    const over = computeCityPlan({ places: rezoned, city_seed: 1337 });
    // The plan changes (the home landmark block keeps zone 'landmark', but
    // generated blocks nearest to it adopt commercial instead of residential).
    expect(JSON.stringify(over)).not.toBe(JSON.stringify(base));
  });
});

// ── EM-239 (S1) — render city FROM the CityGraph, byte-identical to the grid ──

// Build the classic_grid graph exactly as backend engine/citygraph.py emits it
// (node id `n:i:j`, edge id `e:a->b`, tile center (i + 0.5) * TILE). The
// byte-identical gate proves the graph-derived road-tile predicate reproduces
// the hardcoded frozen grid field-for-field.
const ROAD_IDX = [-13, -8, -3, 2, 7, 12];
const tc = (i: number) => (i + 0.5) * TILE; // TILE is already imported in the test
function classicGridGraph(seed = 1337) {
  const nodes = [];
  for (const j of ROAD_IDX) for (const i of ROAD_IDX)
    nodes.push({ id: `n:${i}:${j}`, x: tc(i), z: tc(j), kind: 'junction' as const });
  const edges = [];
  for (const j of ROAD_IDX) for (let k = 0; k < ROAD_IDX.length - 1; k++) {
    const a = `n:${ROAD_IDX[k]}:${j}`, b = `n:${ROAD_IDX[k + 1]}:${j}`;
    edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
  }
  for (const i of ROAD_IDX) for (let k = 0; k < ROAD_IDX.length - 1; k++) {
    const a = `n:${i}:${ROAD_IDX[k]}`, b = `n:${i}:${ROAD_IDX[k + 1]}`;
    edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
  }
  return { version: 1, seed, car_policy: 'cars' as const, nodes, edges };
}

describe('EM-239 byte-identical graph rendering', () => {
  const seed = DEFAULT_CITY_SEED;
  const places: Place[] = TOWN; // reuse the shipped-shape town fixture

  it('classic_grid graph yields a plan identical to the no-graph fallback', () => {
    const fallback = computeCityPlan({ places, city_seed: seed });
    const fromGraph = computeCityPlan({ places, city_seed: seed, city_graph: classicGridGraph(seed) });
    expect(fromGraph).toEqual(fallback);
  });

  it('absent city_graph still renders via the legacy path', () => {
    const plan = computeCityPlan({ places, city_seed: seed, city_graph: null });
    expect(plan.pieces.road_straight.length).toBeGreaterThan(0);
    expect(plan.blocks.length).toBe(GRID_BLOCKS * GRID_BLOCKS);
  });

  it('type-corrupt city_graph degrades to the grid without throwing', () => {
    // ModelBoundary (EM-239): a corrupt graph (nodes/edges not real arrays) must
    // fall back to the hardcoded grid byte-identically, never throw during the
    // render-path computeCityPlan call (upstream of the per-piece boundary).
    const fallback = JSON.stringify(computeCityPlan({ places, city_seed: seed }));
    const corrupt: unknown[] = [
      { nodes: 'str', edges: 'str' },
      { nodes: 5, edges: [{ a: 'x', b: 'y' }] },
      { edges: [{ a: 'x', b: 'y' }] }, // no nodes key
      { edges: { length: 1 } },
      { version: 1, seed, car_policy: 'cars', nodes: [], edges: [] }, // empty
    ];
    for (const bad of corrupt) {
      let plan;
      expect(() => {
        plan = computeCityPlan({ places, city_seed: seed, city_graph: bad as never });
      }, JSON.stringify(bad)).not.toThrow();
      expect(JSON.stringify(plan), JSON.stringify(bad)).toBe(fallback);
    }
  });
});
