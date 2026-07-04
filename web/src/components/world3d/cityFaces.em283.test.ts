/**
 * EM-283 regression — planarFaces handles segment×segment crossings.
 *
 * The sanitizer merged coincident nodes and split node-on-edge overlaps, but NOT
 * two edges crossing at a non-node point — the state a morph guarantees when it
 * ADDS the new topology before REMOVING the old (adds-before-removes). The
 * next-by-angle walk assumes a clean planar embedding, so a transversal crossing
 * tangled a bounded face into the outer face: it could silently DROP an enclosed
 * block or emit a self-intersecting face whose lots sit on a road.
 *
 * We split only at existing nodes (never invent a vertex), so a crossing can't
 * be planarized in place; the fix DETECTS any proper crossing and bails the
 * whole graph to [] (the caller falls back to the grid plat, EM-282). A clean
 * whole-graph [] is sanctioned; a silent partial drop is the forbidden failure.
 */

import { describe, it, expect } from 'vitest';
import type { CityGraph, CityGraphNode, CityGraphEdge } from '../../types';
import { planarFaces } from './cityFaces';

function node(id: string, x: number, z: number): CityGraphNode {
  return { id, x, z, kind: 'junction' };
}
function edge(id: string, a: string, b: string): CityGraphEdge {
  return { id, a, b, road_class: 'street', car_policy: 'inherit' };
}
function graph(nodes: CityGraphNode[], edges: CityGraphEdge[]): CityGraph {
  return { version: 1, seed: 7, car_policy: 'cars', nodes, edges };
}
function shuffled<T>(arr: T[]): T[] {
  const out = [...arr].reverse();
  if (out.length > 2) out.push(out.shift()!);
  return out;
}

describe('planarFaces — EM-283 segment×segment crossings', () => {
  it('two crossing diagonals → clean whole-graph [] (no throw, no partial drop)', () => {
    // a□ b□  with diagonals a→c and b→d crossing at the non-node point (5,5).
    const g = graph(
      [node('a', 0, 0), node('b', 10, 0), node('c', 10, 10), node('d', 0, 10)],
      [edge('ac', 'a', 'c'), edge('bd', 'b', 'd')],
    );
    let faces;
    expect(() => {
      faces = planarFaces(g);
    }).not.toThrow();
    expect(faces).toEqual([]);
  });

  it('a real square PLUS a crossing pair → whole [], never a PARTIAL drop', () => {
    // The square a-b-c-d encloses a clean 100-area face, but the crossing pair
    // e→g / f→h taints the embedding. The contract forbids returning ONLY the
    // square (a silent partial drop) — bail the whole graph so the caller falls
    // back to the grid plat.
    const g = graph(
      [
        node('a', 0, 0), node('b', 10, 0), node('c', 10, 10), node('d', 0, 10),
        node('e', 20, 0), node('f', 30, 0), node('gg', 30, 10), node('h', 20, 10),
      ],
      [
        edge('1', 'a', 'b'), edge('2', 'b', 'c'), edge('3', 'c', 'd'), edge('4', 'd', 'a'),
        edge('x1', 'e', 'gg'), edge('x2', 'f', 'h'), // cross at (25,5)
      ],
    );
    expect(planarFaces(g)).toEqual([]);
  });

  it('the crossing backstop is deterministic under a node/edge shuffle', () => {
    const g = graph(
      [node('a', 0, 0), node('b', 10, 0), node('c', 10, 10), node('d', 0, 10)],
      [edge('ac', 'a', 'c'), edge('bd', 'b', 'd')],
    );
    const sh = graph(shuffled(g.nodes), shuffled(g.edges));
    expect(planarFaces(sh)).toEqual(planarFaces(g)); // both [] — order-independent
  });

  it('control: a clean square (no crossing) is UNAFFECTED — still 1 face', () => {
    const g = graph(
      [node('a', 0, 0), node('b', 10, 0), node('c', 10, 10), node('d', 0, 10)],
      [edge('1', 'a', 'b'), edge('2', 'b', 'c'), edge('3', 'c', 'd'), edge('4', 'd', 'a')],
    );
    const faces = planarFaces(g);
    expect(faces).toHaveLength(1);
    expect(faces[0].area).toBeGreaterThan(0);
  });

  it("control: sharing an endpoint is NOT a crossing (adjacent edges keep their faces)", () => {
    // two unit squares meeting edge-to-edge at the shared b→c wall — many shared
    // endpoints, zero transversal crossings ⇒ both faces survive.
    const g = graph(
      [
        node('a', 0, 0), node('b', 10, 0), node('c', 10, 10), node('d', 0, 10),
        node('e', 20, 0), node('f', 20, 10),
      ],
      [
        edge('1', 'a', 'b'), edge('2', 'b', 'c'), edge('3', 'c', 'd'), edge('4', 'd', 'a'),
        edge('5', 'b', 'e'), edge('6', 'e', 'f'), edge('7', 'f', 'c'),
      ],
    );
    expect(planarFaces(g)).toHaveLength(2);
  });
});
