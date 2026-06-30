/**
 * cityFaces tests — EM-264 (SA) planar-face keystone.
 *
 * The law (contract §0):
 *   • Deterministic (EM-155): node/edge INPUT ORDER must not affect output —
 *     planarFaces & buildZonesFromFaces are deep-equal under a shuffle.
 *   • Never throws, never silently drops an enclosed region (pillar 2): a
 *     corrupt / stub / disconnected / degenerate graph returns loose data or
 *     [], never a throw; a discarded enclosed face is the FORBIDDEN failure.
 *   • No special-casing the core (pillar 4): the pentagon inner face is just
 *     another zone.
 *
 * The matrix (contract §2):
 *   • classic 5×5 grid graph → exactly 25 enclosed faces (no outer face).
 *   • pentagon master-plan graph → 5 outer faces + 1 core face (6 total).
 *   • dangling stub (degree-1 node) → no spurious face, no crash.
 *   • disconnected components → every enclosing component yields its zone(s).
 *   • concave / near-collinear face → returned as a loose polygon (NOT
 *     discarded); buildZonesFromFaces clips lots into it without crashing.
 *   • empty / corrupt / no-edge graph → [].
 *   • determinism: shuffled input ⇒ identical planarFaces + buildZonesFromFaces.
 */

import { describe, it, expect } from 'vitest';
import type { CityGraph, CityGraphNode, CityGraphEdge } from '../../types';
import type { CityZone } from './cityLayout';
import { planarFaces, buildZonesFromFaces, type CityFace } from './cityFaces';

// ── graph builders ──────────────────────────────────────────────────────────

function node(id: string, x: number, z: number): CityGraphNode {
  return { id, x, z, kind: 'junction' };
}

function edge(id: string, a: string, b: string): CityGraphEdge {
  return { id, a, b, road_class: 'street', car_policy: 'inherit' };
}

function graph(nodes: CityGraphNode[], edges: CityGraphEdge[]): CityGraph {
  return { version: 1, seed: 7, car_policy: 'cars', nodes, edges };
}

/**
 * A (blocks+1)×(blocks+1) lattice of junctions with axis-aligned street edges
 * between neighbors — `blocks`×`blocks` unit faces (blocks=5 ⇒ 25 faces).
 */
function gridGraph(blocks: number, unit: number): CityGraph {
  const nodes: CityGraphNode[] = [];
  const edges: CityGraphEdge[] = [];
  const n = blocks + 1;
  const nid = (i: number, j: number) => `n_${i}_${j}`;
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      nodes.push(node(nid(i, j), i * unit, j * unit));
    }
  }
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      if (i + 1 < n) edges.push(edge(`h_${i}_${j}`, nid(i, j), nid(i + 1, j)));
      if (j + 1 < n) edges.push(edge(`v_${i}_${j}`, nid(i, j), nid(i, j + 1)));
    }
  }
  return graph(nodes, edges);
}

/**
 * A nested-pentagon master plan: an inner ring (the core face) + an outer ring,
 * joined by 5 spokes ⇒ 5 outer trapezoid faces + 1 core face = 6 bounded faces.
 */
function pentagonGraph(): CityGraph {
  const nodes: CityGraphNode[] = [];
  const edges: CityGraphEdge[] = [];
  const inner = 5;
  const outer = 10;
  for (let k = 0; k < 5; k++) {
    const a = (k / 5) * Math.PI * 2 + Math.PI / 2;
    nodes.push(node(`i${k}`, inner * Math.cos(a), inner * Math.sin(a)));
    nodes.push(node(`o${k}`, outer * Math.cos(a), outer * Math.sin(a)));
  }
  for (let k = 0; k < 5; k++) {
    const k2 = (k + 1) % 5;
    edges.push(edge(`ir${k}`, `i${k}`, `i${k2}`)); // inner ring
    edges.push(edge(`or${k}`, `o${k}`, `o${k2}`)); // outer ring
    edges.push(edge(`sp${k}`, `i${k}`, `o${k}`));  // spoke
  }
  return graph(nodes, edges);
}

/** Deterministic, content-preserving reordering (proves order-independence). */
function shuffled<T>(arr: T[]): T[] {
  const out = [...arr].reverse();
  if (out.length > 2) out.push(out.shift()!); // rotate by one too
  return out;
}

const zoneAlways = (_x: number, _z: number): CityZone => 'residential';
const zoneByX = (x: number, _z: number): CityZone =>
  x < 25 ? 'residential' : 'commercial';

function totalLots(faces: CityFace[], seed = 7): number {
  return buildZonesFromFaces(faces, seed, zoneAlways).reduce(
    (s, z) => s + z.suggestedLots.length,
    0,
  );
}

// ── planarFaces: the count matrix ─────────────────────────────────────────────

describe('planarFaces — face counting', () => {
  it('classic 5×5 grid → exactly 25 enclosed faces (no outer face)', () => {
    const faces = planarFaces(gridGraph(5, 10));
    expect(faces.length).toBe(25);
    // every kept face encloses area (outer face dropped by sign)
    for (const f of faces) expect(f.area).toBeGreaterThan(0);
  });

  it('pentagon master plan → 5 outer faces + 1 core = 6 (core not special-cased)', () => {
    const faces = planarFaces(pentagonGraph());
    expect(faces.length).toBe(6);
    for (const f of faces) expect(f.area).toBeGreaterThan(0);
  });

  it('disconnected components → every enclosing region kept, none dropped', () => {
    const sq = (p: string, ox: number, oz: number) =>
      graph(
        [
          node(`${p}a`, ox + 0, oz + 0),
          node(`${p}b`, ox + 4, oz + 0),
          node(`${p}c`, ox + 4, oz + 4),
          node(`${p}d`, ox + 0, oz + 4),
        ],
        [
          edge(`${p}1`, `${p}a`, `${p}b`),
          edge(`${p}2`, `${p}b`, `${p}c`),
          edge(`${p}3`, `${p}c`, `${p}d`),
          edge(`${p}4`, `${p}d`, `${p}a`),
        ],
      );
    const g1 = sq('p', 0, 0);
    const g2 = sq('q', 100, 100); // far away — disconnected
    const merged = graph(
      [...g1.nodes, ...g2.nodes],
      [...g1.edges, ...g2.edges],
    );
    const faces = planarFaces(merged);
    expect(faces.length).toBe(2); // one bounded face per component, neither dropped
    for (const f of faces) expect(f.area).toBeGreaterThan(0);
  });
});

// ── planarFaces: defensive / pillar-2 cases ───────────────────────────────────

describe('planarFaces — defensive (never throws, never drops a region)', () => {
  it('dangling stub (degree-1 node) → no spurious face, no crash', () => {
    // a square plus an outward spike off one corner
    const g = graph(
      [
        node('a', 0, 0),
        node('b', 4, 0),
        node('c', 4, 4),
        node('d', 0, 4),
        node('e', -3, -3), // the stub tip, outside the square
      ],
      [
        edge('1', 'a', 'b'),
        edge('2', 'b', 'c'),
        edge('3', 'c', 'd'),
        edge('4', 'd', 'a'),
        edge('5', 'a', 'e'), // dangling
      ],
    );
    let faces: CityFace[] = [];
    expect(() => {
      faces = planarFaces(g);
    }).not.toThrow();
    expect(faces.length).toBe(1); // just the square; the spike spawns no face
    expect(faces[0].area).toBeGreaterThan(0);
  });

  it('empty / corrupt / no-edge graphs → [] (never throws)', () => {
    expect(planarFaces(null)).toEqual([]);
    expect(planarFaces(undefined)).toEqual([]);
    expect(planarFaces({} as unknown as CityGraph)).toEqual([]);
    expect(planarFaces(graph([], []))).toEqual([]);
    expect(planarFaces(graph([node('a', 0, 0)], []))).toEqual([]); // nodes, no edges
    expect(
      planarFaces({ nodes: 'x', edges: 5 } as unknown as CityGraph),
    ).toEqual([]);
    // edges referencing missing nodes don't crash and enclose nothing
    expect(planarFaces(graph([node('a', 0, 0)], [edge('1', 'a', 'ghost')]))).toEqual([]);
    // a pure tree (all stubs) encloses no area → []
    expect(
      planarFaces(
        graph(
          [node('a', 0, 0), node('b', 1, 0), node('c', 2, 0)],
          [edge('1', 'a', 'b'), edge('2', 'b', 'c')],
        ),
      ),
    ).toEqual([]);
  });

  it('concave / near-collinear face → kept as a loose polygon (NOT discarded)', () => {
    // a big concave "L" with a near-collinear vertex on the bottom edge
    const g = graph(
      [
        node('a', 0, 0),
        node('m', 6, 0.001), // near-collinear with a→b
        node('b', 12, 0),
        node('c', 12, 6),
        node('d', 6, 6),
        node('e', 6, 12),
        node('f', 0, 12),
      ],
      [
        edge('1', 'a', 'm'),
        edge('2', 'm', 'b'),
        edge('3', 'b', 'c'),
        edge('4', 'c', 'd'),
        edge('5', 'd', 'e'),
        edge('6', 'e', 'f'),
        edge('7', 'f', 'a'),
      ],
    );
    let faces: CityFace[] = [];
    expect(() => {
      faces = planarFaces(g);
    }).not.toThrow();
    expect(faces.length).toBe(1); // the concave interior is NOT dropped
    expect(faces[0].area).toBeGreaterThan(0);

    // buildZonesFromFaces must clip lots into the concave interior w/o crashing
    let zones = buildZonesFromFaces(faces, 7, zoneAlways);
    expect(() => {
      zones = buildZonesFromFaces(faces, 7, zoneAlways);
    }).not.toThrow();
    expect(zones.length).toBe(1);
    // every suggested lot lands inside the concave polygon
    const poly = faces[0].poly;
    for (const lot of zones[0].suggestedLots) {
      expect(pointInPoly(lot.x, lot.z, poly)).toBe(true);
    }
  });

  it('thin near-collinear triangle (tiny area) → kept, not discarded', () => {
    const g = graph(
      [node('a', 0, 0), node('b', 10, 0), node('c', 5, 0.02)],
      [edge('1', 'a', 'b'), edge('2', 'b', 'c'), edge('3', 'c', 'a')],
    );
    const faces = planarFaces(g);
    expect(faces.length).toBe(1); // an enclosed sliver is still a region
    expect(faces[0].area).toBeGreaterThan(0);
  });
});

// ── buildZonesFromFaces ───────────────────────────────────────────────────────

describe('buildZonesFromFaces', () => {
  it('builds one zone per face with a stable, rotation-independent id', () => {
    const faces = planarFaces(gridGraph(5, 10));
    const zones = buildZonesFromFaces(faces, 7, zoneByX);
    expect(zones.length).toBe(25);
    for (const z of zones) {
      // id = sorted boundary joined — rotation/direction independent
      expect(z.id).toBe([...z.face.boundary].sort().join('|'));
      expect(z.rules).toEqual([]); // SA never populates rules
      expect(['residential', 'commercial']).toContain(z.zoneHint);
    }
    // ids are unique across the 25 blocks
    expect(new Set(zones.map((z) => z.id)).size).toBe(25);
  });

  it('zoneHint comes from the injected callback at the face centroid', () => {
    const faces = planarFaces(gridGraph(5, 10));
    const seen: Array<{ x: number; z: number }> = [];
    const spy = (x: number, z: number): CityZone => {
      seen.push({ x, z });
      return 'civic';
    };
    const zones = buildZonesFromFaces(faces, 7, spy);
    expect(seen.length).toBe(zones.length);
    expect(zones.every((z) => z.zoneHint === 'civic')).toBe(true);
    // the callback was handed each face's centroid
    zones.forEach((z, k) => {
      expect(seen[k].x).toBeCloseTo(z.face.centroid.x, 9);
      expect(seen[k].z).toBeCloseTo(z.face.centroid.z, 9);
    });
  });

  it('suggestedLots are seeded pads inset inside the face', () => {
    const faces = planarFaces(gridGraph(3, 14)); // 9 roomy faces
    const zones = buildZonesFromFaces(faces, 7, zoneAlways);
    const lots = zones.flatMap((z) => z.suggestedLots);
    expect(lots.length).toBeGreaterThan(0);
    // each lot lands inside its own face polygon
    for (const z of zones) {
      for (const lot of z.suggestedLots) {
        expect(pointInPoly(lot.x, lot.z, z.face.poly)).toBe(true);
        expect(Number.isFinite(lot.rotY)).toBe(true);
      }
    }
  });

  it('a different seed moves the seeded pads (seed is load-bearing)', () => {
    const faces = planarFaces(gridGraph(3, 14));
    const a = buildZonesFromFaces(faces, 1, zoneAlways);
    const b = buildZonesFromFaces(faces, 2, zoneAlways);
    expect(JSON.stringify(a)).not.toBe(JSON.stringify(b));
  });

  it('tolerates an empty / non-array faces input', () => {
    expect(buildZonesFromFaces([], 7, zoneAlways)).toEqual([]);
    expect(
      buildZonesFromFaces(undefined as unknown as CityFace[], 7, zoneAlways),
    ).toEqual([]);
  });
});

// ── determinism (EM-155): input order must not affect output ───────────────────

describe('determinism — shuffled node/edge order ⇒ identical output', () => {
  it('planarFaces is deep-equal under a node/edge shuffle (grid)', () => {
    const g = gridGraph(5, 10);
    const sh = graph(shuffled(g.nodes), shuffled(g.edges));
    expect(planarFaces(sh)).toEqual(planarFaces(g));
  });

  it('planarFaces is deep-equal under a shuffle (pentagon)', () => {
    const g = pentagonGraph();
    const sh = graph(shuffled(g.nodes), shuffled(g.edges));
    expect(planarFaces(sh)).toEqual(planarFaces(g));
  });

  it('buildZonesFromFaces is deep-equal under a shuffle', () => {
    const g = gridGraph(4, 12);
    const sh = graph(shuffled(g.nodes), shuffled(g.edges));
    const za = buildZonesFromFaces(planarFaces(g), 7, zoneByX);
    const zb = buildZonesFromFaces(planarFaces(sh), 7, zoneByX);
    expect(zb).toEqual(za);
    expect(JSON.stringify(zb)).toBe(JSON.stringify(za));
  });

  it('shuffling does not change the lot count or face count', () => {
    const g = pentagonGraph();
    const sh = graph(shuffled(g.nodes), shuffled(g.edges));
    expect(planarFaces(sh).length).toBe(planarFaces(g).length);
    expect(totalLots(planarFaces(sh))).toBe(totalLots(planarFaces(g)));
  });
});

// ── local point-in-polygon for assertions (independent of the impl) ───────────

function pointInPoly(
  x: number,
  z: number,
  poly: { x: number; z: number }[],
): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i].x;
    const zi = poly[i].z;
    const xj = poly[j].x;
    const zj = poly[j].z;
    const hit =
      zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi;
    if (hit) inside = !inside;
  }
  return inside;
}
