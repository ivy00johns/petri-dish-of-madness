/**
 * townLayout tests (EM-149) — the Wave C lane-network laws:
 *   • determinism: same places → byte-identical plan across calls
 *   • full reachability: union-find over lane segments connects EVERY place
 *     (no orphans), spine + connectors present
 *   • no duplicate segments, no zero-length segments
 *   • lane-place clearance: no segment passes within LANE_PLACE_CLEAR of a
 *     place it doesn't terminate at (lanes route AROUND places)
 *   • district fallback: districtless places (old snapshots / procgen) are
 *     coordinate-clustered and still get a fully connected lane network
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
  LANE_PLACE_CLEAR,
  LANE_WIDTHS,
  type LaneSegment,
} from './townLayout';

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

const EPS = 1e-4;

function ptKey(x: number, z: number): string {
  return `${x.toFixed(4)},${z.toFixed(4)}`;
}

/** Union-find reachability: which component is each unique endpoint in? */
function components(lanes: LaneSegment[]): Map<string, string> {
  const parent = new Map<string, string>();
  const find = (k: string): string => {
    let root = k;
    while (parent.get(root) !== root) root = parent.get(root)!;
    let cur = k;
    while (parent.get(cur) !== root) {
      const next = parent.get(cur)!;
      parent.set(cur, root);
      cur = next;
    }
    return root;
  };
  const union = (a: string, b: string) => {
    if (!parent.has(a)) parent.set(a, a);
    if (!parent.has(b)) parent.set(b, b);
    parent.set(find(a), find(b));
  };
  for (const l of lanes) union(ptKey(l.ax, l.az), ptKey(l.bx, l.bz));
  const out = new Map<string, string>();
  for (const k of parent.keys()) out.set(k, find(k));
  return out;
}

/** Point-to-segment distance on the XZ plane. */
function pointSegDist(x: number, z: number, s: LaneSegment): number {
  const dx = s.bx - s.ax;
  const dz = s.bz - s.az;
  const len2 = dx * dx + dz * dz;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((x - s.ax) * dx + (z - s.az) * dz) / len2));
  return Math.hypot(x - (s.ax + dx * t), z - (s.az + dz * t));
}

function isEndpointOf(x: number, z: number, s: LaneSegment): boolean {
  return (
    (Math.abs(x - s.ax) < EPS && Math.abs(z - s.az) < EPS) ||
    (Math.abs(x - s.bx) < EPS && Math.abs(z - s.bz) < EPS)
  );
}

/** Shared law pack run against any town shape. */
function expectLaneLaws(places: Place[]) {
  const { lanes } = computeTownLayout(places);
  expect(lanes.length).toBeGreaterThan(0);

  // every place is a lane endpoint (no orphans) and all in ONE component
  const comp = components(lanes);
  const roots = new Set<string>();
  for (const p of places) {
    const w = placeToWorld(p);
    const key = ptKey(w.x, w.z);
    expect(comp.has(key), `${p.id} must be on the lane graph`).toBe(true);
    roots.add(comp.get(key)!);
  }
  expect(roots.size).toBe(1);

  // no duplicate / zero-length segments
  const keys = lanes.map((l) => {
    const a = ptKey(l.ax, l.az);
    const b = ptKey(l.bx, l.bz);
    return a < b ? `${a}|${b}` : `${b}|${a}`;
  });
  expect(new Set(keys).size).toBe(lanes.length);
  for (const l of lanes) {
    expect(Math.hypot(l.bx - l.ax, l.bz - l.az)).toBeGreaterThan(0.05);
  }

  // clearance: lanes route AROUND every place they don't terminate at
  for (const p of places) {
    const w = placeToWorld(p);
    for (const l of lanes) {
      if (isEndpointOf(w.x, w.z, l)) continue;
      expect(
        pointSegDist(w.x, w.z, l),
        `lane through ${p.id}'s clearance disc`,
      ).toBeGreaterThanOrEqual(LANE_PLACE_CLEAR - 1e-6);
    }
  }
}

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
    const a = computeTownLayout(TOWN);
    const b = computeTownLayout(shuffled);
    // identical zone set and identical segment set (order-independent)
    expect(b.zones).toEqual(a.zones);
    const keyOf = (l: LaneSegment) => {
      const ka = ptKey(l.ax, l.az);
      const kb = ptKey(l.bx, l.bz);
      return ka < kb ? `${ka}|${kb}|${l.kind}` : `${kb}|${ka}|${l.kind}`;
    };
    expect(new Set(b.lanes.map(keyOf))).toEqual(new Set(a.lanes.map(keyOf)));
  });
});

describe('lane graph (Wave C district town)', () => {
  it('satisfies the lane laws: reachable, deduped, clearance-respecting', () => {
    expectLaneLaws(TOWN);
  });

  it('builds a spine plus connectors', () => {
    const { lanes } = computeTownLayout(TOWN);
    const spine = lanes.filter((l) => l.kind === 'spine');
    const connectors = lanes.filter((l) => l.kind === 'connector');
    // 5 districts → a ≥5-segment loop (bends may add segments)
    expect(spine.length).toBeGreaterThanOrEqual(5);
    // 15 places − 5 anchors = 10 MST edges minimum
    expect(connectors.length).toBeGreaterThanOrEqual(10);
  });

  it('emits junction patches at lane endpoints, sized from the lane widths', () => {
    const { lanes, junctions } = computeTownLayout(TOWN);
    expect(junctions.length).toBeGreaterThan(0);
    const endpointKeys = new Set<string>();
    for (const l of lanes) {
      endpointKeys.add(ptKey(l.ax, l.az));
      endpointKeys.add(ptKey(l.bx, l.bz));
    }
    expect(junctions.length).toBe(endpointKeys.size);
    const maxR = Math.max(...junctions.map((j) => j.r));
    const minR = Math.min(...junctions.map((j) => j.r));
    expect(maxR).toBeLessThanOrEqual(LANE_WIDTHS.spine);
    expect(minR).toBeGreaterThan(LANE_WIDTHS.connector / 2);
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

  it('legacy towns still satisfy the full lane laws', () => {
    expectLaneLaws(LEGACY);
  });

  it('mixed towns (some places districted, some not) connect everyone', () => {
    const mixed = TOWN.map((p, i) => (i % 3 === 0 ? { ...p, district: undefined } : p));
    expectLaneLaws(mixed);
  });

  it('groups districted places by their district verbatim', () => {
    const groups = groupByDistrict(TOWN);
    const keys = groups.map((g) => g.key).sort();
    expect(keys).toEqual(['civic', 'core', 'farm', 'market', 'residential']);
    const core = groups.find((g) => g.key === 'core')!;
    expect(core.members.map((m) => m.id).sort()).toEqual(['plaza', 'well']);
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

  it('handles two places: a single street between them', () => {
    const pair = [LEGACY[0], LEGACY[1]];
    const plan = computeTownLayout(pair);
    expect(plan.lanes.length).toBe(1);
    expect(plan.lanes[0].kind).toBe('spine');
    expectLaneLaws(pair);
  });
});
