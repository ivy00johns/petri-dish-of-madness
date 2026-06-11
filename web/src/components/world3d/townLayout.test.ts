/**
 * townLayout tests (EM-149, trimmed for Wave D1.5) — the district-layer laws:
 *   • lanes are DEAD: computeTownLayout keeps its signature but always
 *     returns lanes: [] and junctions: [] (the city grid owns the streets)
 *   • determinism: same places → byte-identical plan across calls and
 *     input orderings
 *   • district fallback: districtless places (old snapshots / procgen) are
 *     coordinate-clustered into zone-N groups
 *   • zone tints: known districts map to their tint, fallback zones cycle,
 *     every zone's disc covers its member places
 */

import { describe, it, expect } from 'vitest';
import type { Place } from '../../types';
import { placeToWorld } from './worldSpace';
import {
  computeTownLayout,
  groupByDistrict,
  zoneTint,
  DISTRICT_TINTS,
} from './townLayout';

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

describe('lanes are dead (Wave D1.5 — the city grid owns the streets)', () => {
  it('always returns empty lanes and junctions, signature intact', () => {
    for (const places of [TOWN, LEGACY, [TOWN[0]], []]) {
      const plan = computeTownLayout(places);
      expect(plan.lanes).toEqual([]);
      expect(plan.junctions).toEqual([]);
      expect(Array.isArray(plan.zones)).toBe(true);
    }
  });
});

describe('determinism', () => {
  it('same input → byte-identical plan (districted town)', () => {
    expect(computeTownLayout(TOWN)).toEqual(computeTownLayout(TOWN));
  });

  it('same input → byte-identical plan (legacy town)', () => {
    expect(computeTownLayout(LEGACY)).toEqual(computeTownLayout(LEGACY));
  });

  it('is insensitive to input ordering', () => {
    const shuffled = [TOWN[7], TOWN[2], TOWN[14], TOWN[0], TOWN[9], TOWN[4],
      TOWN[1], TOWN[12], TOWN[5], TOWN[11], TOWN[3], TOWN[13], TOWN[6],
      TOWN[10], TOWN[8]];
    expect(computeTownLayout(shuffled).zones).toEqual(computeTownLayout(TOWN).zones);
  });
});

describe('district fallback (pre-Wave-C snapshots)', () => {
  it('clusters districtless places into zone-N groups', () => {
    const groups = groupByDistrict(LEGACY);
    expect(groups.length).toBeGreaterThanOrEqual(2);
    for (const g of groups) {
      expect(g.key).toMatch(/^zone-\d+$/);
      expect(g.members.length).toBeGreaterThan(0);
    }
    const all = groups.flatMap((g) => g.members.map((m) => m.id)).sort();
    expect(all).toEqual([...LEGACY.map((p) => p.id)].sort());
  });

  it('groups districted places by their district verbatim', () => {
    const groups = groupByDistrict(TOWN);
    const keys = groups.map((g) => g.key).sort();
    expect(keys).toEqual(['civic', 'core', 'farm', 'market', 'residential']);
    const core = groups.find((g) => g.key === 'core')!;
    expect(core.members.map((m) => m.id).sort()).toEqual(['plaza', 'well']);
  });

  it('mixed towns (some places districted, some not) zone everyone', () => {
    const mixed = TOWN.map((p, i) => (i % 3 === 0 ? { ...p, district: undefined } : p));
    const { zones } = computeTownLayout(mixed);
    const covered = new Set(zones.flatMap((z) => z.placeIds));
    expect(covered.size).toBe(TOWN.length);
  });
});

describe('district zones + tints', () => {
  it('maps every known district to its curated tint', () => {
    const { zones } = computeTownLayout(TOWN);
    expect(zones.length).toBe(5);
    for (const z of zones) {
      expect(z.tint).toBe(DISTRICT_TINTS[z.key]);
      expect(z.tint).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it('covers every member place with the zone disc', () => {
    const { zones } = computeTownLayout(TOWN);
    const byId = new Map(TOWN.map((p) => [p.id, placeToWorld(p)]));
    for (const z of zones) {
      expect(z.placeIds.length).toBeGreaterThan(0);
      for (const id of z.placeIds) {
        const w = byId.get(id)!;
        expect(Math.hypot(w.x - z.x, w.z - z.z)).toBeLessThanOrEqual(z.radius);
      }
    }
  });

  it('cycles fallback tints deterministically and dodges prototype keys', () => {
    expect(zoneTint('zone-0', 0)).toMatch(/^#[0-9a-f]{6}$/);
    expect(zoneTint('zone-1', 1)).toMatch(/^#[0-9a-f]{6}$/);
    expect(zoneTint('zone-0', 0)).toBe(zoneTint('zone-0', 0));
    // arbitrary strings must never resolve through the prototype chain
    for (const evil of ['constructor', 'toString', '__proto__']) {
      expect(zoneTint(evil, 2)).toMatch(/^#[0-9a-f]{6}$/);
    }
  });
});

describe('degenerate worlds', () => {
  it('handles an empty place list', () => {
    expect(computeTownLayout([])).toEqual({ lanes: [], junctions: [], zones: [] });
  });

  it('handles a single place: one zone, no lanes', () => {
    const plan = computeTownLayout([TOWN[0]]);
    expect(plan.lanes).toEqual([]);
    expect(plan.junctions).toEqual([]);
    expect(plan.zones.length).toBe(1);
    expect(plan.zones[0].key).toBe('core');
  });
});
