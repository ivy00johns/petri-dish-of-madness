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
// @ts-ignore -- node builtin without @types/node
import { readFileSync } from 'node:fs';
// @ts-ignore -- node builtin without @types/node
import { resolve } from 'node:path';
import type { CityGraph, CityGraphNode, CityGraphEdge } from '../../types';
import type { CityZone } from './cityLayout';
import { planarFaces, buildZonesFromFaces, type CityFace, type ZoneRule } from './cityFaces';

// The app tsconfig ships no @types/node; node builtins are real under vitest.
// vitest runs from web/ (the toolchain `cd web && npx vitest`), so cwd()/.. is
// the repo root — the sanctioned pattern from cityModels.test.ts.
declare const process: { cwd(): string };

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

// ── EM-264 SA defect regression: angular ties must never drop a region ─────────
// An adversarial review found triggers where a vertex gets two outgoing half-
// edges at an IDENTICAL atan2 angle — coincident nodes, or a node sitting ON
// another edge (collinear overlap). The next-by-angle walk then tangles the
// bounded face into the outer face and the `area > 0` keep-filter silently drops
// the whole enclosed region (the FORBIDDEN failure). The fix sanitizes first:
// merge coincident nodes, split collinear overlaps, distance tie-break, and a
// whole-graph [] backstop. For each clearly-enclosed arrangement we require
// EITHER full representation OR a clean whole-graph [] — NEVER a partial drop.

function sumArea(faces: CityFace[]): number {
  return faces.reduce((s, f) => s + f.area, 0);
}

function polyArea(poly: { x: number; z: number }[]): number {
  let a = 0;
  for (let i = 0; i < poly.length; i++) {
    const p = poly[i];
    const q = poly[(i + 1) % poly.length];
    a += p.x * q.z - q.x * p.z;
  }
  return Math.abs(a) / 2;
}

/** Pillar-2 contract: either nothing (clean grid fallback) or the WHOLE enclosed
 *  area is represented — never some-but-not-all (a silent partial drop). */
function assertNoPartialDrop(faces: CityFace[], expected: number): void {
  if (faces.length === 0) return; // sanctioned clean whole-graph [] fallback
  for (const f of faces) expect(f.area).toBeGreaterThan(0); // no outer face leaked
  expect(Math.abs(sumArea(faces) - expected)).toBeLessThan(
    1e-6 * Math.max(1, expected),
  );
}

/** Stronger: the fix RESOLVES this case (merge/split) → the region must be fully
 *  represented (non-empty + full area), NOT bailed to the [] backstop. */
function assertEnclosed(faces: CityFace[], expected: number): void {
  expect(faces.length).toBeGreaterThan(0);
  assertNoPartialDrop(faces, expected);
}

/** Mirrors backend master_plan('radial'): two concentric rings of `spokes`
 *  nodes + a SHARED center; every outer spoke (center→o{k}) passes straight
 *  through the inner node i{k} at the same angle ⇒ collinear overlap + angular
 *  tie at the center. The split must planarize it into real sectors. */
function radialGraph(spokes: number, R: number): CityGraph {
  const nodes: CityGraphNode[] = [node('c', 0, 0)]; // shared center
  const edges: CityGraphEdge[] = [];
  const inner = R * 0.5;
  for (let k = 0; k < spokes; k++) {
    const ang = (k / spokes) * Math.PI * 2;
    nodes.push(node(`o${k}`, R * Math.cos(ang), R * Math.sin(ang)));
    nodes.push(node(`i${k}`, inner * Math.cos(ang), inner * Math.sin(ang)));
  }
  for (let k = 0; k < spokes; k++) {
    const k2 = (k + 1) % spokes;
    edges.push(edge(`or${k}`, `o${k}`, `o${k2}`)); // outer ring
    edges.push(edge(`ir${k}`, `i${k}`, `i${k2}`)); // inner ring
    edges.push(edge(`os${k}`, `o${k}`, 'c')); // outer spoke (through i{k})
    edges.push(edge(`is${k}`, `i${k}`, 'c')); // inner spoke
  }
  return graph(nodes, edges);
}

describe('planarFaces — angular-tie regression (no silent partial drop)', () => {
  it('A6: coincident nodes (e ≡ c) → the square survives (merge), not dropped', () => {
    // a clean unit square a-b-c-d (area 36) PLUS a node e at the exact coords of
    // c, with edges b-e and e-d (an EM-245 merge artifact). Pre-fix: returns [].
    const g = graph(
      [
        node('a', 0, 0),
        node('b', 6, 0),
        node('c', 6, 6),
        node('d', 0, 6),
        node('e', 6, 6), // coincident with c (the cliff)
      ],
      [
        edge('1', 'a', 'b'),
        edge('2', 'b', 'c'),
        edge('3', 'c', 'd'),
        edge('4', 'd', 'a'),
        edge('5', 'b', 'e'),
        edge('6', 'e', 'd'),
      ],
    );
    let faces: CityFace[] = [];
    expect(() => {
      faces = planarFaces(g);
    }).not.toThrow();
    assertEnclosed(faces, 36); // 6×6 square fully represented
  });

  it('A5 control: nudging e to (6.001,6.001) also yields the face (no over-merge)', () => {
    // The exact-coincidence is the cliff; a 0.001 nudge must NOT merge and the
    // face is still found via the plain angle walk.
    const g = graph(
      [
        node('a', 0, 0),
        node('b', 6, 0),
        node('c', 6, 6),
        node('d', 0, 6),
        node('e', 6.001, 6.001), // nudged → distinct node
      ],
      [
        edge('1', 'a', 'b'),
        edge('2', 'b', 'c'),
        edge('3', 'c', 'd'),
        edge('4', 'd', 'a'),
        edge('5', 'b', 'e'),
        edge('6', 'e', 'd'),
      ],
    );
    const faces = planarFaces(g);
    expect(faces.length).toBeGreaterThan(0); // the enclosed region is present
    for (const f of faces) expect(f.area).toBeGreaterThan(0);
  });

  it('B3: duplicated shared junction (e ≡ e2) → both squares survive', () => {
    // Two adjacent squares sharing a corner that got split into coincident e and
    // e2 (a realistic morph/merge artifact). Both 6×6 squares must come back.
    //   left square:  a(0,0) b(6,0) e(6,6) d(0,6)
    //   right square: e2(6,6) f(12,6) g(12,0) b(6,0)
    const g = graph(
      [
        node('a', 0, 0),
        node('b', 6, 0),
        node('d', 0, 6),
        node('e', 6, 6),
        node('e2', 6, 6), // coincident duplicate of e
        node('f', 12, 6),
        node('g', 12, 0),
      ],
      [
        // left square via e
        edge('l1', 'a', 'b'),
        edge('l2', 'b', 'e'),
        edge('l3', 'e', 'd'),
        edge('l4', 'd', 'a'),
        // right square via e2
        edge('r1', 'b', 'g'),
        edge('r2', 'g', 'f'),
        edge('r3', 'f', 'e2'),
        edge('r4', 'e2', 'b'),
      ],
    );
    let faces: CityFace[] = [];
    expect(() => {
      faces = planarFaces(g);
    }).not.toThrow();
    assertEnclosed(faces, 72); // two 6×6 squares, neither tangled away
  });

  it('B1: pure collinear overlap (no coincident nodes) → both blocks survive', () => {
    // b(6,0) has two edges straight up — b→c(6,6) and b→e(6,12) — at the same
    // +π/2 angle; likewise f→a overlaps d→a on the x=0 line. Encloses 72.
    const g = graph(
      [
        node('a', 0, 0),
        node('b', 6, 0),
        node('c', 6, 6),
        node('d', 0, 6),
        node('e', 6, 12),
        node('f', 0, 12),
      ],
      [
        edge('1', 'a', 'b'),
        edge('2', 'b', 'e'), // long vertical, overlaps b→c
        edge('3', 'e', 'f'),
        edge('4', 'f', 'a'), // long vertical, overlaps d→a
        edge('5', 'b', 'c'),
        edge('6', 'c', 'd'),
        edge('7', 'd', 'a'),
      ],
    );
    let faces: CityFace[] = [];
    expect(() => {
      faces = planarFaces(g);
    }).not.toThrow();
    assertEnclosed(faces, 72); // lower + upper 6×6 squares, neither dropped
  });

  it('radial master plan → decomposes into real sectors (not one tangled face)', () => {
    const SPOKES = 6;
    const R = 26;
    const g = radialGraph(SPOKES, R);
    let faces: CityFace[] = [];
    expect(() => {
      faces = planarFaces(g);
    }).not.toThrow();
    // expected total enclosed = the outer-ring polygon (sectors tile it exactly)
    const outerPoly = Array.from({ length: SPOKES }, (_, k) => {
      const ang = (k / SPOKES) * Math.PI * 2;
      return { x: R * Math.cos(ang), z: R * Math.sin(ang) };
    });
    const expected = polyArea(outerPoly);
    assertNoPartialDrop(faces, expected); // contract: full coverage or clean []
    // the split RESOLVES the radial tie into 2·spokes sectors (inner triangles +
    // outer trapezoids) — NOT the [] backstop, NOT one garbage tangled face.
    expect(faces.length).toBe(2 * SPOKES);
    assertEnclosed(faces, expected);
  });

  it('determinism: new tie cases are deep-equal under a node/edge shuffle', () => {
    const cases: CityGraph[] = [
      graph(
        [
          node('a', 0, 0),
          node('b', 6, 0),
          node('c', 6, 6),
          node('d', 0, 6),
          node('e', 6, 6),
        ],
        [
          edge('1', 'a', 'b'),
          edge('2', 'b', 'c'),
          edge('3', 'c', 'd'),
          edge('4', 'd', 'a'),
          edge('5', 'b', 'e'),
          edge('6', 'e', 'd'),
        ],
      ),
      graph(
        [
          node('a', 0, 0),
          node('b', 6, 0),
          node('c', 6, 6),
          node('d', 0, 6),
          node('e', 6, 12),
          node('f', 0, 12),
        ],
        [
          edge('1', 'a', 'b'),
          edge('2', 'b', 'e'),
          edge('3', 'e', 'f'),
          edge('4', 'f', 'a'),
          edge('5', 'b', 'c'),
          edge('6', 'c', 'd'),
          edge('7', 'd', 'a'),
        ],
      ),
      radialGraph(6, 26),
    ];
    for (const g of cases) {
      const sh = graph(shuffled(g.nodes), shuffled(g.edges));
      expect(planarFaces(sh)).toEqual(planarFaces(g));
      // and the zones derived from them are byte-identical too
      const za = buildZonesFromFaces(planarFaces(g), 7, zoneByX);
      const zb = buildZonesFromFaces(planarFaces(sh), 7, zoneByX);
      expect(JSON.stringify(zb)).toBe(JSON.stringify(za));
    }
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

// ── EM-265 (SB) — zone-rule attach by id ──────────────────────────────────────
// buildZonesFromFaces gains an optional `zoneRules` param; each zone gets the
// rules whose `zone_id` equals its `id`. Absent/empty ⇒ every `rules: []`
// (byte-identical to SA — the no-rules path, law §0.1). The cross-language zone
// id formula is IDENTICAL both sides (sorted boundary node ids joined, law §0.2),
// so a backend-ratified rule lands on exactly the matching rendered block.

describe('EM-265 (SB) — buildZonesFromFaces attaches zone_rules by id', () => {
  it('a rule whose zone_id matches a zone lands on that zone (and no other)', () => {
    const faces = planarFaces(gridGraph(5, 10));
    const ids = buildZonesFromFaces(faces, 7, zoneAlways).map((z) => z.id);
    const targetId = ids[3];
    const rule: ZoneRule = { zone_id: targetId, hint: 'market', density_cap: 4 };
    const zones = buildZonesFromFaces(faces, 7, zoneAlways, [rule]);
    for (const z of zones) {
      if (z.id === targetId) expect(z.rules).toEqual([rule]);
      else expect(z.rules).toEqual([]);
    }
    // exactly one zone carries the rule
    expect(zones.filter((z) => z.rules.length > 0)).toHaveLength(1);
  });

  it('absent / empty / non-matching rules ⇒ byte-identical to SA (rules: [])', () => {
    const faces = planarFaces(gridGraph(5, 10));
    const sa = buildZonesFromFaces(faces, 7, zoneAlways); // SA default (no param)
    const emptyParam = buildZonesFromFaces(faces, 7, zoneAlways, []);
    const ghost = buildZonesFromFaces(faces, 7, zoneAlways, [
      { zone_id: 'no-such-zone', hint: 'civic', density_cap: null },
    ]);
    // [] param == SA default == an unmatched rule ⇒ all three are byte-identical
    expect(JSON.stringify(emptyParam)).toBe(JSON.stringify(sa));
    expect(JSON.stringify(ghost)).toBe(JSON.stringify(sa));
    for (const z of sa) expect(z.rules).toEqual([]);
  });

  it('density_cap (number AND null) round-trips onto the attached rule', () => {
    const faces = planarFaces(gridGraph(5, 10));
    const ids = buildZonesFromFaces(faces, 7, zoneAlways).map((z) => z.id);
    const rules: ZoneRule[] = [
      { zone_id: ids[0], hint: 'open', density_cap: null },
      { zone_id: ids[1], hint: 'residential', density_cap: 0 },
    ];
    const zones = buildZonesFromFaces(faces, 7, zoneAlways, rules);
    const z0 = zones.find((z) => z.id === ids[0])!;
    const z1 = zones.find((z) => z.id === ids[1])!;
    expect(z0.rules[0]).toEqual({ zone_id: ids[0], hint: 'open', density_cap: null });
    expect(z1.rules[0].density_cap).toBe(0);
  });

  it('attach is deterministic under a shuffle (same rule lands on the same id)', () => {
    const g = gridGraph(5, 10);
    const sh = graph(shuffled(g.nodes), shuffled(g.edges));
    const id = buildZonesFromFaces(planarFaces(g), 7, zoneAlways)[2].id;
    const rules: ZoneRule[] = [{ zone_id: id, hint: 'civic', density_cap: 2 }];
    const za = buildZonesFromFaces(planarFaces(g), 7, zoneAlways, rules);
    const zb = buildZonesFromFaces(planarFaces(sh), 7, zoneAlways, rules);
    expect(JSON.stringify(zb)).toBe(JSON.stringify(za));
  });
});

// ── EM-265 (SB) — cross-language zone-id consistency (law §0.2) ────────────────
// Lane 1 emits contracts/em265-zone-id-fixture.json: canonical graphs + the
// zone-id SET the BACKEND planar_faces computes. The TS planarFaces here MUST
// compute the SAME set on the SAME nodes/edges, or a ratified rule's zone_id
// won't tint the right block. This pins the two ports together (the keystone).

describe('EM-265 (SB) — cross-language zone-id consistency (law §0.2)', () => {
  const fixturePath = resolve(process.cwd(), '..', 'contracts/em265-zone-id-fixture.json');
  const fixture = JSON.parse(readFileSync(fixturePath, 'utf8')) as {
    cases: { name: string; graph: CityGraph; zone_ids: string[] }[];
  };

  it('the fixture carries the 3 generator cases', () => {
    expect(fixture.cases.map((c) => c.name).sort()).toEqual(
      ['classic_grid', 'pentagon', 'radial'],
    );
  });

  for (const c of fixture.cases) {
    it(`TS planarFaces zone-id set equals the backend fixture — ${c.name}`, () => {
      const faces = planarFaces(c.graph);
      // zone id = sorted boundary node ids joined (the SAME formula both sides)
      const tsIds = faces.map((f) => [...f.boundary].sort().join('|')).sort();
      const want = [...c.zone_ids].sort();
      expect(tsIds).toEqual(want);
      // and the SAME ids flow out of buildZonesFromFaces (the rendered BuildZone.id)
      const zoneIds = buildZonesFromFaces(faces, 7, zoneAlways)
        .map((z) => z.id)
        .sort();
      expect(zoneIds).toEqual(want);
    });
  }
});
