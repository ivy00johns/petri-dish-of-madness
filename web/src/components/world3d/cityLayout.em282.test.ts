/**
 * EM-282 regression — graph-lots grid fallback when planarFaces yields nothing.
 *
 * On the graph-lots path (opts.graphLots + a real CityGraph), buildable blocks
 * came straight from the road graph's bounded planar faces. When that set is
 * EMPTY — an open path with no enclosed block, or a sanctioned planarFaces
 * backstop (angular tie / segment×segment crossing mid-morph, EM-283) — the plan
 * shipped ZERO blocks/blockLots/emptyLots (a hole). The fix falls through to the
 * fixed-grid plat: never a hole, never a crash, and the additive `zones` key
 * stays omitted so consumers see a plain grid plan.
 */

import { describe, it, expect } from 'vitest';
import type { Place, CityGraph } from '../../types';
import { TILE, GRID_BLOCKS, DEFAULT_CITY_SEED, computeCityPlan } from './cityLayout';

const tc = (i: number) => (i + 0.5) * TILE;
const PLACES: Place[] = [
  { id: 'plaza', name: 'Plaza', x: 500, y: 500, kind: 'social', description: '' },
  { id: 'market', name: 'Market', x: 760, y: 420, kind: 'work', description: '' },
];

/** An open axis-aligned path (three colinear junctions) — encloses no face. */
function pathGraph(seed = DEFAULT_CITY_SEED): CityGraph {
  const nodes = [2, 7, 12].map((i) => ({ id: `n:${i}:2`, x: tc(i), z: tc(2), kind: 'junction' as const }));
  const edges = [
    { id: 'e0', a: 'n:2:2', b: 'n:7:2', road_class: 'street' as const, car_policy: 'inherit' as const },
    { id: 'e1', a: 'n:7:2', b: 'n:12:2', road_class: 'street' as const, car_policy: 'inherit' as const },
  ];
  return { version: 1, seed, car_policy: 'cars', nodes, edges };
}

/** Two diagonals of a square that cross at (5,5) — a non-node transversal
 *  crossing; planarFaces bails the whole graph to [] (EM-283). */
function crossingGraph(seed = DEFAULT_CITY_SEED): CityGraph {
  const nodes = [
    { id: 'a', x: 0, z: 0, kind: 'junction' as const },
    { id: 'b', x: 10, z: 0, kind: 'junction' as const },
    { id: 'c', x: 10, z: 10, kind: 'junction' as const },
    { id: 'd', x: 0, z: 10, kind: 'junction' as const },
  ];
  const edges = [
    { id: 'ac', a: 'a', b: 'c', road_class: 'street' as const, car_policy: 'inherit' as const },
    { id: 'bd', a: 'b', b: 'd', road_class: 'street' as const, car_policy: 'inherit' as const },
  ];
  return { version: 1, seed, car_policy: 'cars', nodes, edges };
}

describe('EM-282 — graphLots falls back to the grid plat when there are no faces', () => {
  const seed = DEFAULT_CITY_SEED;

  for (const [label, mk] of [
    ['open path (no enclosed block)', pathGraph],
    ['segment×segment crossing (planarFaces backstop)', crossingGraph],
  ] as const) {
    it(`${label}: ships the 25-block grid plat, not a hole`, () => {
      const g = mk(seed);
      const plan = computeCityPlan({ places: PLACES, city_seed: seed, city_graph: g }, { graphLots: true });

      // The forbidden failure was zero blocks/lots; the fallback restores them.
      expect(plan.blocks.length).toBe(GRID_BLOCKS * GRID_BLOCKS); // 25
      expect(plan.blockLots.length).toBeGreaterThan(0);
      expect(plan.emptyLots.length).toBeGreaterThan(0);
      // Fell back to the grid ⇒ the additive zones key is omitted (grid contract).
      expect(plan.zones).toBeUndefined();

      // The fallback plan is byte-identical to the plain grid path on the SAME
      // graph (flag off): the ONLY difference graphLots makes here is none.
      const gridPath = computeCityPlan({ places: PLACES, city_seed: seed, city_graph: g }, { graphLots: false });
      expect(JSON.stringify(plan)).toBe(JSON.stringify(gridPath));
    });
  }

  it('a real enclosed graph still takes the graph-lots path (fallback is targeted)', () => {
    // A single 10×10 block: planarFaces returns 1 bounded face ⇒ zones present.
    const nodes = [
      { id: 'a', x: 0, z: 0, kind: 'junction' as const },
      { id: 'b', x: 10, z: 0, kind: 'junction' as const },
      { id: 'c', x: 10, z: 10, kind: 'junction' as const },
      { id: 'd', x: 0, z: 10, kind: 'junction' as const },
    ];
    const edges = [
      { id: '1', a: 'a', b: 'b', road_class: 'street' as const, car_policy: 'inherit' as const },
      { id: '2', a: 'b', b: 'c', road_class: 'street' as const, car_policy: 'inherit' as const },
      { id: '3', a: 'c', b: 'd', road_class: 'street' as const, car_policy: 'inherit' as const },
      { id: '4', a: 'd', b: 'a', road_class: 'street' as const, car_policy: 'inherit' as const },
    ];
    const g: CityGraph = { version: 1, seed, car_policy: 'cars', nodes, edges };
    const plan = computeCityPlan({ places: PLACES, city_seed: seed, city_graph: g }, { graphLots: true });
    expect(plan.zones).toBeDefined();
    expect(plan.zones!.length).toBe(1);
    expect(plan.blocks.length).toBe(1); // the face, not the 25-grid
  });
});
