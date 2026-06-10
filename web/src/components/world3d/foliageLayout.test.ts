/**
 * foliageLayout tests (EM-118) — the contract invariants for the instanced
 * treeline + town props:
 *   • determinism: same places → byte-identical layout across calls
 *   • clearance: no tree within 10 of any place center; wild props ≥ BAND_MAX
 *     from every center; near props (lamps/benches) on their own place's snug
 *     inner ring (below SLOT_BASE_RADIUS — outside their own slot band) and
 *     ≥ NEIGHBOR_FLOOR from every other center
 *   • variant distribution sanity: every tree variant present
 *   • counts within the contract bounds (trees 50–80, total instances ≲400)
 */

import { describe, it, expect } from 'vitest';
import type { Place } from '../../types';
import { placeToWorld } from './worldSpace';
import {
  layoutTrees,
  splitByLod,
  layoutLamps,
  layoutBenches,
  layoutFences,
  layoutMushrooms,
  layoutWildScatter,
  TREE_COUNT,
  TREE_SPACING,
  TREE_LOD_RADIUS,
  BAND_MAX,
  NEAR_RING_MIN,
  NEAR_RING_MAX,
  NEIGHBOR_FLOOR,
  PATH_HALF_WIDTH,
  PATH_CLEAR,
  pathSegments,
  distToNearestPath,
  MAX_LAMPS,
  BUSH_COUNT,
  ROCK_COUNT,
  MUSHROOM_COUNT,
  BENCHES_PER_PLAZA,
  FENCE_SEGMENTS_PER_HOME,
  type ScatterItem,
} from './foliageLayout';

/** A representative procgen-ish town: hub plaza + four satellite places. */
const PLACES: Place[] = [
  { id: 'plaza', name: 'Plaza', x: 500, y: 500, kind: 'social', description: '' },
  { id: 'market', name: 'Market', x: 760, y: 420, kind: 'work', description: '' },
  { id: 'hall', name: 'Town Hall', x: 420, y: 760, kind: 'governance', description: '' },
  { id: 'hearth', name: 'Hearth', x: 250, y: 300, kind: 'home', description: '' },
  { id: 'commons', name: 'Commons', x: 720, y: 760, kind: 'wild', description: '' },
];

const CENTERS = PLACES.map(placeToWorld);

function distToCenters(it: { x: number; z: number }): number[] {
  return CENTERS.map((c) => Math.hypot(c.x - it.x, c.z - it.z));
}

/**
 * Near-prop invariant: the prop sits on SOME place's snug inner ring
 * (NEAR_RING_MIN..NEAR_RING_MAX — entirely below that place's slot band) and
 * keeps ≥ NEIGHBOR_FLOOR from every other place center.
 */
function nearPropSafe(it: { x: number; z: number }): boolean {
  const ds = distToCenters(it);
  const own = Math.min(...ds);
  if (own < NEAR_RING_MIN || own > NEAR_RING_MAX) return false;
  return ds.every((d) => d === own || d >= NEIGHBOR_FLOOR);
}

describe('foliageLayout determinism', () => {
  it('produces identical tree layouts across two calls', () => {
    expect(layoutTrees(PLACES)).toEqual(layoutTrees(PLACES));
  });

  it('produces identical prop layouts across two calls', () => {
    expect(layoutLamps(PLACES)).toEqual(layoutLamps(PLACES));
    expect(layoutBenches(PLACES)).toEqual(layoutBenches(PLACES));
    expect(layoutFences(PLACES)).toEqual(layoutFences(PLACES));
    expect(layoutMushrooms(PLACES)).toEqual(layoutMushrooms(PLACES));
    expect(layoutWildScatter(BUSH_COUNT, 'bush', PLACES)).toEqual(
      layoutWildScatter(BUSH_COUNT, 'bush', PLACES),
    );
  });

  it('is insensitive to call order (pure functions, no shared state)', () => {
    const a = layoutTrees(PLACES);
    layoutLamps(PLACES);
    layoutWildScatter(ROCK_COUNT, 'rock', PLACES);
    expect(layoutTrees(PLACES)).toEqual(a);
  });
});

describe('tree clearance + counts (contract §B3)', () => {
  const trees = layoutTrees(PLACES);

  it('reaches the contract tree count band (50–80)', () => {
    expect(trees.length).toBeGreaterThanOrEqual(50);
    expect(trees.length).toBeLessThanOrEqual(80);
    expect(trees.length).toBeLessThanOrEqual(TREE_COUNT);
  });

  it('keeps every tree ≥ 10 units from every place center', () => {
    for (const t of trees) {
      for (const d of distToCenters(t)) expect(d).toBeGreaterThanOrEqual(10);
    }
  });

  it('keeps trees spaced apart from each other', () => {
    for (let i = 0; i < trees.length; i++) {
      for (let j = i + 1; j < trees.length; j++) {
        expect(
          Math.hypot(trees[i].x - trees[j].x, trees[i].z - trees[j].z),
        ).toBeGreaterThanOrEqual(TREE_SPACING);
      }
    }
  });

  it('includes every variant (oak, conifer, blossom)', () => {
    const variants = new Set(trees.map((t) => t.variant));
    expect(variants).toEqual(new Set(['oak', 'conifer', 'blossom']));
  });

  it('splits into near/far LOD batches deterministically and completely', () => {
    const { near, far } = splitByLod(trees);
    expect(near.length + far.length).toBe(trees.length);
    expect(near.length).toBeGreaterThan(0);
    expect(far.length).toBeGreaterThan(0);
    for (const t of near) expect(Math.hypot(t.x, t.z)).toBeLessThanOrEqual(TREE_LOD_RADIUS);
    for (const t of far) expect(Math.hypot(t.x, t.z)).toBeGreaterThan(TREE_LOD_RADIUS);
    expect(splitByLod(trees)).toEqual(splitByLod(trees));
  });
});

describe('prop clearance (own slot band avoided; neighbors respected)', () => {
  it('keeps lamps snug on their own ring, below the slot band', () => {
    const lamps = layoutLamps(PLACES);
    expect(lamps.length).toBeGreaterThan(0);
    expect(lamps.length).toBeLessThanOrEqual(MAX_LAMPS);
    for (const l of lamps) expect(nearPropSafe(l)).toBe(true);
  });

  it('keeps benches on the plaza inner ring, below the slot band', () => {
    const benches = layoutBenches(PLACES);
    expect(benches.length).toBeGreaterThan(0);
    const plaza = placeToWorld(PLACES[0]);
    for (const b of benches) {
      expect(nearPropSafe(b)).toBe(true);
      expect(Math.hypot(plaza.x - b.x, plaza.z - b.z)).toBeLessThanOrEqual(NEAR_RING_MAX);
    }
  });

  it('keeps fences, bushes, mushrooms and rocks ≥ BAND_MAX from every center', () => {
    const wildProps: ScatterItem[] = [
      ...layoutFences(PLACES),
      ...layoutWildScatter(BUSH_COUNT, 'bush', PLACES),
      ...layoutWildScatter(ROCK_COUNT, 'rock', PLACES),
      ...layoutMushrooms(PLACES),
    ];
    expect(wildProps.length).toBeGreaterThan(0);
    for (const p of wildProps) {
      for (const d of distToCenters(p)) expect(d).toBeGreaterThanOrEqual(BAND_MAX);
    }
  });

  it('keeps every non-lamp item out of the path corridors', () => {
    const segs = pathSegments(PLACES);
    expect(segs.length).toBe(PLACES.length - 1); // hub → each other place
    const nonLamp: ScatterItem[] = [
      ...layoutTrees(PLACES),
      ...layoutBenches(PLACES),
      ...layoutFences(PLACES),
      ...layoutWildScatter(BUSH_COUNT, 'bush', PLACES),
      ...layoutWildScatter(ROCK_COUNT, 'rock', PLACES),
      ...layoutMushrooms(PLACES),
    ];
    expect(nonLamp.length).toBeGreaterThan(0);
    for (const p of nonLamp) {
      expect(distToNearestPath(p.x, p.z, segs)).toBeGreaterThanOrEqual(PATH_CLEAR);
    }
  });

  it('keeps lamps beside the ribbons — lining a path, never on one', () => {
    const segs = pathSegments(PLACES);
    const lamps = layoutLamps(PLACES);
    expect(lamps.length).toBeGreaterThan(0);
    for (const l of lamps) {
      const d = distToNearestPath(l.x, l.z, segs);
      // off the ribbon proper…
      expect(d).toBeGreaterThanOrEqual(PATH_HALF_WIDTH);
      // …but actually LINING a path, not floating in a field
      expect(d).toBeLessThanOrEqual(2.5);
    }
  });

  it('clusters mushrooms near the wild place', () => {
    const wild = placeToWorld(PLACES[4]);
    const mushrooms = layoutMushrooms(PLACES);
    expect(mushrooms.length).toBeGreaterThan(0);
    for (const m of mushrooms) {
      expect(Math.hypot(wild.x - m.x, wild.z - m.z)).toBeLessThanOrEqual(BAND_MAX + 5.1);
    }
  });
});

describe('instance budget (contract: total NEW instances ≲400)', () => {
  it('keeps the per-part instance total under 400', () => {
    const trees = layoutTrees(PLACES);
    const { near, far } = splitByLod(trees);
    // parts per object, mirroring Foliage.tsx / Props.tsx exactly:
    // near tree = trunk + 2 canopy parts; far tree = trunk + 1 canopy
    const treeInstances = near.length * 3 + far.length * 2;
    const lampInstances = layoutLamps(PLACES).length * 3; // base+post+head
    const benchInstances = layoutBenches(PLACES).length * 4; // seat+back+2 legs
    const fenceInstances = layoutFences(PLACES).length * 3; // post+2 rails
    const bushInstances = layoutWildScatter(BUSH_COUNT, 'bush', PLACES).length;
    const rockInstances = layoutWildScatter(ROCK_COUNT, 'rock', PLACES).length;
    const mushroomInstances = layoutMushrooms(PLACES).length * 2; // stem+cap

    const total =
      treeInstances +
      lampInstances +
      benchInstances +
      fenceInstances +
      bushInstances +
      rockInstances +
      mushroomInstances;
    expect(total).toBeLessThanOrEqual(400);
  });

  it('respects the configured prop count caps', () => {
    expect(layoutBenches(PLACES).length).toBeLessThanOrEqual(BENCHES_PER_PLAZA);
    expect(layoutFences(PLACES).length).toBeLessThanOrEqual(FENCE_SEGMENTS_PER_HOME);
    expect(layoutMushrooms(PLACES).length).toBeLessThanOrEqual(MUSHROOM_COUNT);
  });
});

describe('degenerate worlds', () => {
  it('handles an empty place list without throwing', () => {
    expect(layoutLamps([])).toEqual([]);
    expect(layoutBenches([])).toEqual([]);
    expect(layoutFences([])).toEqual([]);
    expect(layoutTrees([]).length).toBe(TREE_COUNT);
    expect(layoutMushrooms([]).length).toBeGreaterThan(0); // falls back to scatter
  });

  it('handles a single place (no paths → no lamps)', () => {
    const solo = [PLACES[0]];
    expect(layoutLamps(solo)).toEqual([]);
    const trees = layoutTrees(solo);
    const c = placeToWorld(solo[0]);
    for (const t of trees) {
      expect(Math.hypot(c.x - t.x, c.z - t.z)).toBeGreaterThanOrEqual(10);
    }
  });
});
