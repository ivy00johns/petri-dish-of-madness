/**
 * foliageLayout tests (EM-118, rebuilt for Wave D1.5) — the park-greenery
 * laws:
 *   • determinism: same places → byte-identical layout across calls and
 *     input orderings
 *   • PARK-ONLY law: every tree and grass tuft sits INSIDE a park landmark
 *     block (the blocks claimed by farm-district places); a town with no
 *     parks gets NO greenery
 *   • light scatter: per-park counts are small and anchor-clear, trees
 *     self-spaced
 *   • LOD split is a complete, threshold-faithful partition
 *   • the wilderness layers are dead: lamps/benches/fences/mushrooms/wild
 *     scatter always return []
 */

import { describe, it, expect } from 'vitest';
import type { Place } from '../../types';
import { placeToWorld } from './worldSpace';
import { snapToBlockCenter, BLOCK_HALF } from './cityLayout';
import {
  layoutTrees,
  layoutParkGrass,
  splitByLod,
  parkBlocks,
  insidePark,
  layoutLamps,
  layoutBenches,
  layoutFences,
  layoutMushrooms,
  layoutWildScatter,
  TREE_SPACING,
  TREE_LOD_RADIUS,
  PARK_TREES_PER_BLOCK,
  PARK_GRASS_PER_BLOCK,
  PARK_EDGE_INSET,
  PARK_ANCHOR_CLEAR,
  BUSH_COUNT,
  ROCK_COUNT,
} from './foliageLayout';

/** The Wave D1.5 15-place city grid (mirrors config/world.yaml). */
const PLACES: Place[] = [
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

/** A pre-Wave-C, districtless town (wild-kind fallback path). */
const LEGACY: Place[] = [
  { id: 'plaza', name: 'Plaza', x: 500, y: 500, kind: 'social', description: '' },
  { id: 'market', name: 'Market', x: 760, y: 420, kind: 'work', description: '' },
  { id: 'hall', name: 'Town Hall', x: 420, y: 760, kind: 'governance', description: '' },
  { id: 'hearth', name: 'Hearth', x: 250, y: 300, kind: 'home', description: '' },
  { id: 'commons', name: 'Commons', x: 720, y: 760, kind: 'wild', description: '' },
];

/** A town with NO farm district and NO wild kind: zero parks anywhere. */
const PARKLESS: Place[] = PLACES.filter((p) => p.district !== 'farm');

const FARM_IDS = ['commons', 'farmstead', 'orchard', 'willow_pond'];

describe('park blocks', () => {
  it('derives one park block per farm-district place, sorted and snapped', () => {
    const blocks = parkBlocks(PLACES);
    expect(blocks.map((b) => b.id)).toEqual(FARM_IDS);
    for (const b of blocks) {
      const place = PLACES.find((p) => p.id === b.id)!;
      const w = placeToWorld(place);
      expect({ x: b.cx, z: b.cz }).toEqual(snapToBlockCenter(w.x, w.z));
    }
  });

  it('falls back to wild-kind places for district-less legacy towns', () => {
    expect(parkBlocks(LEGACY).map((b) => b.id)).toEqual(['commons']);
  });

  it('is insensitive to input ordering', () => {
    const reversed = [...PLACES].reverse();
    expect(parkBlocks(reversed)).toEqual(parkBlocks(PLACES));
  });

  it('a parkless town has no park blocks', () => {
    expect(parkBlocks(PARKLESS)).toEqual([]);
  });
});

describe('determinism', () => {
  it('produces identical tree and grass layouts across two calls', () => {
    expect(layoutTrees(PLACES)).toEqual(layoutTrees(PLACES));
    expect(layoutParkGrass(PLACES)).toEqual(layoutParkGrass(PLACES));
  });

  it('is insensitive to call order (pure functions, no shared state)', () => {
    const a = layoutTrees(PLACES);
    layoutParkGrass(PLACES);
    layoutTrees(LEGACY);
    expect(layoutTrees(PLACES)).toEqual(a);
  });
});

describe('the park-only law (Wave D1.5)', () => {
  const blocks = parkBlocks(PLACES);
  const trees = layoutTrees(PLACES);
  const grass = layoutParkGrass(PLACES);

  it('plants a light scatter in every park block', () => {
    expect(trees.length).toBe(blocks.length * PARK_TREES_PER_BLOCK);
    expect(grass.length).toBe(blocks.length * PARK_GRASS_PER_BLOCK);
  });

  it('keeps EVERY tree and tuft inside a park landmark block', () => {
    for (const item of [...trees, ...grass]) {
      expect(
        insidePark(item.x, item.z, blocks),
        `greenery escaped the parks at (${item.x}, ${item.z})`,
      ).toBe(true);
      // …and inset from the sidewalk rim
      const owner = blocks.find(
        (b) =>
          Math.abs(item.x - b.cx) <= BLOCK_HALF && Math.abs(item.z - b.cz) <= BLOCK_HALF,
      )!;
      expect(Math.abs(item.x - owner.cx)).toBeLessThanOrEqual(BLOCK_HALF - PARK_EDGE_INSET + 1e-9);
      expect(Math.abs(item.z - owner.cz)).toBeLessThanOrEqual(BLOCK_HALF - PARK_EDGE_INSET + 1e-9);
    }
  });

  it('keeps trees clear of the park anchor and spaced apart within a park', () => {
    for (const b of blocks) {
      const inThis = trees.filter(
        (t) => Math.abs(t.x - b.cx) <= BLOCK_HALF && Math.abs(t.z - b.cz) <= BLOCK_HALF,
      );
      for (const t of inThis) {
        expect(Math.hypot(t.x - b.cx, t.z - b.cz)).toBeGreaterThanOrEqual(PARK_ANCHOR_CLEAR);
      }
      for (let i = 0; i < inThis.length; i++) {
        for (let j = i + 1; j < inThis.length; j++) {
          expect(
            Math.hypot(inThis[i].x - inThis[j].x, inThis[i].z - inThis[j].z),
          ).toBeGreaterThanOrEqual(TREE_SPACING);
        }
      }
    }
  });

  it('a town without parks gets ZERO greenery', () => {
    expect(layoutTrees(PARKLESS)).toEqual([]);
    expect(layoutParkGrass(PARKLESS)).toEqual([]);
  });

  it('legacy wild-kind places still seed their park', () => {
    const legacyTrees = layoutTrees(LEGACY);
    expect(legacyTrees.length).toBeGreaterThan(0);
    expect(legacyTrees.length).toBeLessThanOrEqual(PARK_TREES_PER_BLOCK);
    const legacyBlocks = parkBlocks(LEGACY);
    for (const t of legacyTrees) expect(insidePark(t.x, t.z, legacyBlocks)).toBe(true);
  });
});

describe('tree variants + LOD', () => {
  const trees = layoutTrees(PLACES);

  it('mixes tree variants (no monoculture)', () => {
    const variants = new Set(trees.map((t) => t.variant));
    expect(variants.size).toBeGreaterThanOrEqual(2);
    for (const v of variants) expect(['oak', 'conifer', 'blossom']).toContain(v);
  });

  it('splits into near/far LOD batches deterministically and completely', () => {
    const { near, far } = splitByLod(trees);
    expect(near.length + far.length).toBe(trees.length);
    for (const t of near) expect(Math.hypot(t.x, t.z)).toBeLessThanOrEqual(TREE_LOD_RADIUS);
    for (const t of far) expect(Math.hypot(t.x, t.z)).toBeGreaterThan(TREE_LOD_RADIUS);
    expect(splitByLod(trees)).toEqual(splitByLod(trees));
  });
});

describe('the wilderness layers are dead (Wave D1.5)', () => {
  it('lamps, benches, fences, mushrooms and wild scatter always return []', () => {
    for (const places of [PLACES, LEGACY, [], [PLACES[0]]]) {
      expect(layoutLamps(places)).toEqual([]);
      expect(layoutBenches(places)).toEqual([]);
      expect(layoutFences(places)).toEqual([]);
      expect(layoutMushrooms(places)).toEqual([]);
      expect(layoutWildScatter(BUSH_COUNT, 'bush', places)).toEqual([]);
      expect(layoutWildScatter(ROCK_COUNT, 'rock', places)).toEqual([]);
      expect(layoutWildScatter(50, 'anything', places, 99)).toEqual([]);
    }
  });
});

describe('degenerate worlds', () => {
  it('handles an empty place list without throwing', () => {
    expect(layoutTrees([])).toEqual([]);
    expect(layoutParkGrass([])).toEqual([]);
    expect(parkBlocks([])).toEqual([]);
  });

  it('handles a single (non-park) place', () => {
    expect(layoutTrees([PLACES[0]])).toEqual([]);
  });

  it('handles a single park place', () => {
    const solo = [PLACES.find((p) => p.id === 'commons')!];
    const trees = layoutTrees(solo);
    expect(trees.length).toBeGreaterThan(0);
    expect(trees.length).toBeLessThanOrEqual(PARK_TREES_PER_BLOCK);
  });
});
