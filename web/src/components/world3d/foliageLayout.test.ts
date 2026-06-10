/**
 * foliageLayout tests (EM-118, lane-aware since EM-149) — the contract
 * invariants for the instanced treeline + town props:
 *   • determinism: same places → byte-identical layout across calls
 *   • clearance: no tree within 10 of any place center; wild props ≥ BAND_MAX
 *     from every center; benches on their own place's snug inner ring (below
 *     SLOT_BASE_RADIUS) and ≥ NEIGHBOR_FLOOR from every other center
 *   • lane corridors: pathSegments is townLayout's lane graph (the single
 *     source of truth — Wave C) and every non-lamp item stays PATH_CLEAR off
 *     every lane centerline; lamps LINE the lanes, never sit on one, and obey
 *     the lamp clearance law (≥ NEIGHBOR_FLOOR, never inside a slot band)
 *   • variant distribution sanity: every tree variant present
 *   • counts within the contract bounds (trees 50–80, total instances ≲400)
 */

import { describe, it, expect } from 'vitest';
import type { Place } from '../../types';
import { placeToWorld } from './worldSpace';
import { computeTownLayout } from './townLayout';
import {
  layoutTrees,
  splitByLod,
  layoutLamps,
  layoutBenches,
  layoutFences,
  layoutMushrooms,
  layoutWildScatter,
  lampSpotValid,
  TREE_COUNT,
  TREE_SPACING,
  TREE_LOD_RADIUS,
  BAND_MAX,
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

/** The Wave C 15-place district town (mirrors config/world.yaml). */
const PLACES: Place[] = [
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

/** A pre-Wave-C, districtless town (fallback clustering path). */
const LEGACY: Place[] = [
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
 * Near-prop invariant (benches): the prop sits on SOME place's snug inner
 * ring (below that place's slot band) and keeps ≥ NEIGHBOR_FLOOR from every
 * other place center.
 */
function nearPropSafe(it: { x: number; z: number }): boolean {
  const ds = distToCenters(it);
  const own = Math.min(...ds);
  if (own < 3.2 || own > NEAR_RING_MAX) return false;
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

describe('lane corridors come from townLayout (EM-149 single source of truth)', () => {
  it('pathSegments returns EXACTLY the townLayout lane graph', () => {
    const lanes = computeTownLayout(PLACES).lanes;
    const segs = pathSegments(PLACES);
    expect(segs).toEqual(
      lanes.map((l) => ({ ax: l.ax, az: l.az, bx: l.bx, bz: l.bz })),
    );
    expect(segs.length).toBeGreaterThanOrEqual(PLACES.length - 1);
  });

  it('also tracks the lanes for districtless legacy towns', () => {
    const lanes = computeTownLayout(LEGACY).lanes;
    expect(pathSegments(LEGACY).length).toBe(lanes.length);
    expect(pathSegments(LEGACY).length).toBeGreaterThanOrEqual(LEGACY.length - 1);
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
  it('keeps benches on a social place inner ring, below the slot band', () => {
    const benches = layoutBenches(PLACES);
    expect(benches.length).toBeGreaterThan(0);
    const socials = PLACES.filter((p) => p.kind === 'social').map(placeToWorld);
    for (const b of benches) {
      expect(nearPropSafe(b)).toBe(true);
      const nearest = Math.min(
        ...socials.map((s) => Math.hypot(s.x - b.x, s.z - b.z)),
      );
      expect(nearest).toBeLessThanOrEqual(NEAR_RING_MAX);
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

  it('keeps every non-lamp item out of the lane corridors', () => {
    const segs = pathSegments(PLACES);
    expect(segs.length).toBeGreaterThan(0);
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

  it('keeps lamps beside the lane strips — lining a lane, never on one', () => {
    const segs = pathSegments(PLACES);
    const lamps = layoutLamps(PLACES);
    expect(lamps.length).toBeGreaterThan(0);
    expect(lamps.length).toBeLessThanOrEqual(MAX_LAMPS);
    for (const l of lamps) {
      const d = distToNearestPath(l.x, l.z, segs);
      // off the strip proper…
      expect(d).toBeGreaterThanOrEqual(PATH_HALF_WIDTH);
      // …but actually LINING a lane, not floating in a field
      expect(d).toBeLessThanOrEqual(2.5);
      // and obeying the lamp clearance law (structures + slot bands)
      expect(lampSpotValid(l.x, l.z, CENTERS)).toBe(true);
    }
  });

  it('lines lanes with lamps in legacy (districtless) towns too', () => {
    const lamps = layoutLamps(LEGACY);
    const segs = pathSegments(LEGACY);
    expect(lamps.length).toBeGreaterThan(0);
    for (const l of lamps) {
      expect(distToNearestPath(l.x, l.z, segs)).toBeGreaterThanOrEqual(PATH_HALF_WIDTH);
      expect(distToNearestPath(l.x, l.z, segs)).toBeLessThanOrEqual(2.5);
    }
  });

  it('clusters mushrooms near the wild places', () => {
    const wilds = PLACES.filter((p) => p.kind === 'wild').map(placeToWorld);
    const mushrooms = layoutMushrooms(PLACES);
    expect(mushrooms.length).toBeGreaterThan(0);
    for (const m of mushrooms) {
      const nearest = Math.min(
        ...wilds.map((w) => Math.hypot(w.x - m.x, w.z - m.z)),
      );
      expect(nearest).toBeLessThanOrEqual(BAND_MAX + 5.1);
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
    const socials = PLACES.filter((p) => p.kind === 'social').length;
    const homes = PLACES.filter((p) => p.kind === 'home').length;
    expect(layoutBenches(PLACES).length).toBeLessThanOrEqual(BENCHES_PER_PLAZA * socials);
    expect(layoutFences(PLACES).length).toBeLessThanOrEqual(FENCE_SEGMENTS_PER_HOME * homes);
    expect(layoutMushrooms(PLACES).length).toBeLessThanOrEqual(MUSHROOM_COUNT);
    expect(layoutLamps(PLACES).length).toBeLessThanOrEqual(MAX_LAMPS);
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

  it('handles a single place (no lanes → no lamps)', () => {
    const solo = [PLACES[0]];
    expect(pathSegments(solo)).toEqual([]);
    expect(layoutLamps(solo)).toEqual([]);
    const trees = layoutTrees(solo);
    const c = placeToWorld(solo[0]);
    for (const t of trees) {
      expect(Math.hypot(c.x - t.x, c.z - t.z)).toBeGreaterThanOrEqual(10);
    }
  });
});
