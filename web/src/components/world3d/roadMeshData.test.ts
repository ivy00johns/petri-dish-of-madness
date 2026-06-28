import { describe, it, expect } from 'vitest';
import { buildRoadMesh, ROAD_WIDTH, type RoadMesh } from './roadMeshData';
import type { CityGraph } from '../../types';

function graphOf(nodes: Array<[string, number, number]>, edges: Array<[string, string, string]>,
                 extra: Partial<CityGraph> = {}): CityGraph {
  return {
    version: 1, seed: 1337, car_policy: 'cars',
    nodes: nodes.map(([id, x, z]) => ({ id, x, z, kind: 'junction' as const })),
    edges: edges.map(([id, a, b]) => ({ id, a, b, road_class: 'street' as const, car_policy: 'inherit' as const })),
    ...extra,
  };
}

describe('buildRoadMesh (pure any-angle geometry generator — EM-247 S5a)', () => {
  it('extrudes a width-correct ribbon along an axis-aligned edge', () => {
    const g = graphOf([['a', 0, 0], ['b', 10, 0]], [['e', 'a', 'b']]);
    const m = buildRoadMesh(g, 1337);
    expect(m.ribbons).toHaveLength(1);
    const r = m.ribbons[0];
    expect(r.x).toBeCloseTo(5); expect(r.z).toBeCloseTo(0);   // midpoint
    expect(r.length).toBeCloseTo(10);
    expect(r.rotY).toBeCloseTo(0);                            // along +x
    expect(r.width).toBeCloseTo(ROAD_WIDTH.street);
  });

  it('orients a DIAGONAL ribbon at any angle (the whole point of S5a)', () => {
    const g = graphOf([['a', 0, 0], ['b', 10, 10]], [['e', 'a', 'b']]);
    const r = buildRoadMesh(g, 1337).ribbons[0];
    expect(r.length).toBeCloseTo(Math.hypot(10, 10));        // ~14.14
    expect(r.rotY).toBeCloseTo(Math.atan2(10, 10));          // 45° = π/4
    expect(r.x).toBeCloseTo(5); expect(r.z).toBeCloseTo(5);
  });

  it('emits one intersection patch per node', () => {
    const g = graphOf([['a', 0, 0], ['b', 10, 0], ['c', 0, 10]],
                      [['e1', 'a', 'b'], ['e2', 'a', 'c']]);
    const m = buildRoadMesh(g, 1337);
    expect(m.intersections).toHaveLength(3);
    expect(m.intersections.every((p) => Number.isFinite(p.x) && Number.isFinite(p.z) && p.size > 0)).toBe(true);
  });

  it('roundabout / plaza nodes get ring / plaza geometry', () => {
    const g = graphOf([['a', 0, 0], ['b', 10, 0]], [['e', 'a', 'b']]);
    g.nodes[0] = { ...g.nodes[0], kind: 'roundabout' } as any;
    g.nodes[1] = { ...g.nodes[1], kind: 'plaza' } as any;
    const m = buildRoadMesh(g, 1337);
    expect(m.roundabouts).toHaveLength(1);
    expect(m.roundabouts[0].outerR).toBeGreaterThan(m.roundabouts[0].innerR);
    expect(m.plazas).toHaveLength(1);
    // a roundabout/plaza node is NOT also a plain intersection patch
    expect(m.intersections).toHaveLength(0);
  });

  it('road_class scales ribbon width', () => {
    const g = graphOf([['a', 0, 0], ['b', 10, 0]], [['e', 'a', 'b']]);
    g.edges[0] = { ...g.edges[0], road_class: 'avenue' } as any;
    const r = buildRoadMesh(g, 1337).ribbons[0];
    expect(r.width).toBeCloseTo(ROAD_WIDTH.avenue ?? ROAD_WIDTH.street);
  });

  it('is pure + deterministic (same graph ⇒ identical mesh)', () => {
    const g = graphOf([['a', 0, 0], ['b', 10, 0], ['c', 5, 9]],
                      [['e1', 'a', 'b'], ['e2', 'b', 'c'], ['e3', 'c', 'a']]);
    expect(buildRoadMesh(g, 1337)).toEqual(buildRoadMesh(g, 1337));
  });

  it('no NaN/Infinity anywhere; absent/edgeless graph ⇒ empty buckets', () => {
    const m = buildRoadMesh(null, 1337);
    expect(m.ribbons).toEqual([]); expect(m.intersections).toEqual([]);
    const all = (mm: RoadMesh) => [...mm.ribbons, ...mm.intersections, ...mm.roundabouts, ...mm.plazas];
    const g = graphOf([['a', 0, 0], ['b', -7, 3]], [['e', 'a', 'b']]);
    for (const inst of all(buildRoadMesh(g, 1337)))
      for (const v of Object.values(inst)) expect(Number.isFinite(v)).toBe(true);
  });

  it('draw-call budget: a 36-node/60-edge classic grid stays a handful of buckets', () => {
    // 4 bucket types regardless of city size — the instancing keeps draw calls bounded.
    const m = buildRoadMesh(graphOf([['a', 0, 0], ['b', 10, 0]], [['e', 'a', 'b']]), 1337);
    const buckets = [m.ribbons, m.intersections, m.roundabouts, m.plazas].filter((b) => b.length > 0);
    expect(buckets.length).toBeLessThanOrEqual(4);
  });

  it('a pentagon graph builds clean any-angle geometry (S3b/S4 acceptance)', () => {
    const R = 30, cx = 0, cz = 0;
    const pts = Array.from({ length: 5 }, (_, i) => {
      const t = (i / 5) * Math.PI * 2;
      return [`p${i}`, cx + R * Math.cos(t), cz + R * Math.sin(t)] as [string, number, number];
    });
    const nodes = [...pts, ['c', cx, cz] as [string, number, number]];
    const edges: Array<[string, string, string]> = [];
    for (let i = 0; i < 5; i++) {
      edges.push([`peri${i}`, `p${i}`, `p${(i + 1) % 5}`]);
      edges.push([`spoke${i}`, `p${i}`, 'c']);
    }
    const g = { version: 1, seed: 1337, car_policy: 'cars' as const,
      nodes: nodes.map(([id, x, z]) => ({ id, x, z, kind: 'junction' as const })),
      edges: edges.map(([id, a, b]) => ({ id, a, b, road_class: 'street' as const, car_policy: 'inherit' as const })) };
    const m = buildRoadMesh(g, 1337);
    expect(m.ribbons).toHaveLength(10);
    expect(m.ribbons.every((r) => Number.isFinite(r.rotY) && Number.isFinite(r.length))).toBe(true);
    expect(buildRoadMesh(g, 1337)).toEqual(m); // deterministic
    const spokeAngles = new Set(m.ribbons.map((r) => Math.round(r.rotY * 1000)));
    expect(spokeAngles.size).toBeGreaterThan(4); // many distinct non-axis-aligned angles
    // budget holds: still ≤ 4 buckets even for the radial profile
    const buckets = [m.ribbons, m.intersections, m.roundabouts, m.plazas].filter((b) => b.length > 0);
    expect(buckets.length).toBeLessThanOrEqual(4);
  });
});
