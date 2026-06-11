/**
 * cityLayout tests — EM-153 generator laws + the EM-155 frontend determinism
 * invariant home:
 *   • EM-155 determinism: same snapshot + same seed ⇒ JSON.stringify-identical
 *     plan (live/replay/fork all call the same pure function); a re-parsed
 *     (replayed/forked) snapshot yields the byte-identical plan
 *   • seed sensitivity: different city_seed ⇒ different plan
 *   • city_seed absent (pre-W15 snapshot) ⇒ default seed 1337
 *   • historic-core clearance (EM-156): NO instance within coreRadius of the
 *     town centroid, across several seeds; roads terminate at the boundary
 *   • vocabulary totality: pieces carries exactly the 23 frozen CityPieceKeys
 *   • bounds: every instance within the plan's extent (Chebyshev)
 *   • road connectivity: every road tile neighbors ≥ 1 other road tile
 *   • instance budget ≤ MAX_CITY_INSTANCES (3000)
 *   • pre-Wave-C district-less snapshots still produce a lawful city
 */

import { describe, it, expect } from 'vitest';
import type { Place } from '../../types';
import { placeToWorld } from './worldSpace';
import {
  TILE,
  CITY_PIECE_KEYS,
  CITY_ZONES,
  DEFAULT_CITY_SEED,
  MAX_CITY_INSTANCES,
  MIN_CORE_RADIUS,
  computeCityPlan,
  deriveCoreRadius,
  townCenter,
  type CityInstance,
  type CityPlan,
  type CityPieceKey,
} from './cityLayout';

/** The Wave C 15-place district town (mirrors config/world.yaml). */
const TOWN: Place[] = [
  { id: 'plaza', name: 'Central Plaza', x: 500, y: 500, kind: 'social', district: 'core', description: '' },
  { id: 'well', name: 'The Old Well', x: 510, y: 420, kind: 'social', district: 'core', description: '' },
  { id: 'market', name: 'Market', x: 750, y: 400, kind: 'work', district: 'market', description: '' },
  { id: 'forge', name: 'The Ember Forge', x: 840, y: 340, kind: 'work', district: 'market', description: '' },
  { id: 'workshop', name: "Tinker's Workshop", x: 820, y: 470, kind: 'work', district: 'market', description: '' },
  { id: 'townhall', name: 'Town Hall', x: 250, y: 350, kind: 'governance', district: 'civic', description: '' },
  { id: 'archive', name: 'The Records Hall', x: 180, y: 260, kind: 'governance', district: 'civic', description: '' },
  { id: 'home', name: 'Hearth', x: 300, y: 650, kind: 'home', district: 'residential', description: '' },
  { id: 'rosehip_cottage', name: 'Rosehip Cottage', x: 210, y: 640, kind: 'home', district: 'residential', description: '' },
  { id: 'mossy_row', name: 'Mossy Row', x: 250, y: 740, kind: 'home', district: 'residential', description: '' },
  { id: 'lantern_loft', name: 'Lantern Loft', x: 340, y: 740, kind: 'home', district: 'residential', description: '' },
  { id: 'commons', name: 'The Commons', x: 500, y: 750, kind: 'wild', district: 'farm', description: '' },
  { id: 'willow_pond', name: 'Willow Pond', x: 610, y: 690, kind: 'wild', district: 'farm', description: '' },
  { id: 'orchard', name: 'Bramble Orchard', x: 640, y: 790, kind: 'wild', district: 'farm', description: '' },
  { id: 'farmstead', name: 'Sunfall Farmstead', x: 730, y: 700, kind: 'work', district: 'farm', description: '' },
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

/** Independent centroid computation (must agree with the module's origin). */
function centroidOf(places: Place[]): { x: number; z: number } {
  if (places.length === 0) return { x: 0, z: 0 };
  let x = 0;
  let z = 0;
  for (const p of places) {
    const w = placeToWorld(p);
    x += w.x;
    z += w.z;
  }
  return { x: x / places.length, z: z / places.length };
}

function allInstances(plan: CityPlan): CityInstance[] {
  return CITY_PIECE_KEYS.flatMap((k) => plan.pieces[k]);
}

function roadInstances(plan: CityPlan): CityInstance[] {
  return ROAD_KEYS.flatMap((k) => plan.pieces[k]);
}

function countInstances(plan: CityPlan): number {
  return allInstances(plan).length;
}

/** The shared law pack: clearance, totality, bounds, connectivity, budget. */
function expectCityLaws(places: Place[], seed: number) {
  const plan = computeCityPlan({ places, city_seed: seed });
  const c = centroidOf(places);
  const coreRadius = deriveCoreRadius(places);
  const label = `seed ${seed}`;

  // vocabulary totality — exactly the 23 frozen keys, in canonical order
  expect(Object.keys(plan.pieces), label).toEqual([...CITY_PIECE_KEYS]);

  // a real city came out (not a degenerate empty plan)
  expect(countInstances(plan), label).toBeGreaterThan(200);
  expect(plan.blocks.length, label).toBeGreaterThan(10);

  for (const inst of allInstances(plan)) {
    // every field finite
    expect(Number.isFinite(inst.x), label).toBe(true);
    expect(Number.isFinite(inst.z), label).toBe(true);
    expect(Number.isFinite(inst.rotY), label).toBe(true);
    if (inst.s !== undefined) expect(inst.s).toBeGreaterThan(0);
    // historic-core clearance (EM-156): nothing inside the core
    expect(
      Math.hypot(inst.x - c.x, inst.z - c.z),
      `${label}: instance inside the historic core`,
    ).toBeGreaterThanOrEqual(coreRadius);
    // bounds: within the extent actually used (Chebyshev from the centroid)
    expect(Math.abs(inst.x - c.x), label).toBeLessThanOrEqual(plan.extent);
    expect(Math.abs(inst.z - c.z), label).toBeLessThanOrEqual(plan.extent);
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

  // every block carries a valid zone
  for (const b of plan.blocks) {
    expect(CITY_ZONES).toContain(b.zone);
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
});

describe('historic core clearance (EM-156)', () => {
  it('keeps every instance outside the derived core radius across seeds', () => {
    const c = centroidOf(TOWN);
    const coreRadius = deriveCoreRadius(TOWN);
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed });
      for (const inst of allInstances(plan)) {
        expect(
          Math.hypot(inst.x - c.x, inst.z - c.z),
          `seed ${seed}: instance inside the core`,
        ).toBeGreaterThanOrEqual(coreRadius);
      }
    }
  });

  it('derives the core radius from the town measurements (never below the place reach)', () => {
    const c = centroidOf(TOWN);
    const coreRadius = deriveCoreRadius(TOWN);
    let maxPlace = 0;
    for (const p of TOWN) {
      const w = placeToWorld(p);
      maxPlace = Math.max(maxPlace, Math.hypot(w.x - c.x, w.z - c.z));
    }
    // every place + its building-slot band must fit inside the core
    expect(coreRadius).toBeGreaterThan(maxPlace + 10);
    expect(deriveCoreRadius([])).toBe(MIN_CORE_RADIUS);
  });

  it('agrees with the module on the grid origin (the town centroid)', () => {
    expect(townCenter(TOWN)).toEqual(centroidOf(TOWN));
    expect(townCenter([])).toEqual({ x: 0, z: 0 });
  });

  it('honors an explicit coreRadius option', () => {
    const c = centroidOf(TOWN);
    const big = deriveCoreRadius(TOWN) + 12;
    const plan = computeCityPlan({ places: TOWN, city_seed: 7 }, { coreRadius: big, extent: big * 2 });
    for (const inst of allInstances(plan)) {
      expect(Math.hypot(inst.x - c.x, inst.z - c.z)).toBeGreaterThanOrEqual(big);
    }
  });

  it('terminates roads at boundaries with road_end caps, some near the core', () => {
    const c = centroidOf(TOWN);
    const coreRadius = deriveCoreRadius(TOWN);
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed });
      expect(plan.pieces.road_end.length, `seed ${seed}`).toBeGreaterThan(0);
      // the road network reaches down to just outside the core boundary
      const nearest = Math.min(
        ...roadInstances(plan).map((r) => Math.hypot(r.x - c.x, r.z - c.z)),
      );
      expect(nearest, `seed ${seed}`).toBeLessThanOrEqual(coreRadius + 3 * TILE);
    }
  });
});

describe('city laws — totality, bounds, connectivity, budget', () => {
  it('holds the full law pack across seeds (districted town)', () => {
    for (const seed of SEEDS) expectCityLaws(TOWN, seed);
  });

  it('stays within the instance budget across seeds', () => {
    for (const seed of SEEDS) {
      const plan = computeCityPlan({ places: TOWN, city_seed: seed });
      expect(countInstances(plan), `seed ${seed}`).toBeLessThanOrEqual(MAX_CITY_INSTANCES);
    }
  });

  it('zones the default-seed city: commercial ring, residential mass, parks', () => {
    const plan = computeCityPlan({ places: TOWN });
    const zones = new Set(plan.blocks.map((b) => b.zone));
    expect(zones.has('commercial')).toBe(true);
    expect(zones.has('residential')).toBe(true);
    expect(zones.has('park')).toBe(true);
    // commercial blocks sit nearer the core than the residential average
    const c = centroidOf(TOWN);
    const avg = (zone: string) => {
      const list = plan.blocks.filter((b) => b.zone === zone);
      return list.reduce((s, b) => s + Math.hypot(b.cx - c.x, b.cz - c.z), 0) / list.length;
    };
    expect(avg('commercial')).toBeLessThan(avg('residential'));
  });

  it('default extent spans ≈ 2× the core radius (unless budget-capped)', () => {
    const plan = computeCityPlan({ places: TOWN });
    const coreRadius = deriveCoreRadius(TOWN);
    expect(plan.extent).toBeGreaterThan(coreRadius);
    expect(plan.extent).toBeLessThanOrEqual(coreRadius * 2);
  });
});

describe('pre-Wave-C snapshots (district-less)', () => {
  it('holds the full law pack for a legacy town across seeds', () => {
    for (const seed of [1, 1337, 9001]) expectCityLaws(LEGACY, seed);
  });

  it('produces a deterministic plan with the default seed', () => {
    const a = computeCityPlan({ places: LEGACY });
    const b = computeCityPlan({ places: LEGACY });
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
    expect(countInstances(a)).toBeGreaterThan(0);
  });
});

describe('degenerate worlds', () => {
  it('handles an empty place list without crashing (city around MIN_CORE_RADIUS)', () => {
    const plan = computeCityPlan({ places: [] });
    expect(Object.keys(plan.pieces)).toEqual([...CITY_PIECE_KEYS]);
    expect(countInstances(plan)).toBeLessThanOrEqual(MAX_CITY_INSTANCES);
    for (const inst of allInstances(plan)) {
      expect(Math.hypot(inst.x, inst.z)).toBeGreaterThanOrEqual(MIN_CORE_RADIUS);
    }
  });

  it('handles a single place', () => {
    const plan = computeCityPlan({ places: [TOWN[0]], city_seed: 5 });
    expect(Object.keys(plan.pieces)).toEqual([...CITY_PIECE_KEYS]);
    expect(countInstances(plan)).toBeLessThanOrEqual(MAX_CITY_INSTANCES);
  });

  it('returns an empty plan when the extent leaves no room outside the core', () => {
    // extent small enough that even the square's corners stay inside the core circle
    const coreRadius = deriveCoreRadius(TOWN);
    const plan = computeCityPlan({ places: TOWN, city_seed: 3 }, { extent: coreRadius / 2 });
    expect(countInstances(plan)).toBe(0);
    expect(plan.blocks).toEqual([]);
  });
});
