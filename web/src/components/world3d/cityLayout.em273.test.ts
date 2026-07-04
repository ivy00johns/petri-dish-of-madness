/**
 * EM-273 regression — phantom streets + off-road cars/labels.
 *
 * Pre-fix, street lines (and thus ambient traffic + street-name labels) were
 * derived from every graph NODE coordinate, so a lone junction, an east stub, a
 * demolished/thinned road line, or a diagonal pentagon/radial spoke minted a
 * NAMED street with no road under it — and cars swept it. The fix derives street
 * lines from the graph's EDGES: a street names only a line carrying a real
 * axis-aligned road segment, and its mid-block labels clip to the paved span.
 *
 * The no-graph / classic_grid baseline stays byte-identical (covered by the
 * EM-188 goldens in cityLayout.test.ts); these pin the post-morph behavior.
 */

import { describe, it, expect } from 'vitest';
import type { CityGraph } from '../../types';
import { TILE, BLOCK_PITCH, DEFAULT_CITY_SEED, computeStreets } from './cityLayout';
import { computeTraffic } from './trafficLayout';

const ROAD_IDX = [-13, -8, -3, 2, 7, 12];
const tc = (i: number) => (i + 0.5) * TILE;

/** The classic_grid graph (mirrors backend engine/citygraph.py). */
function classicGridGraph(seed = DEFAULT_CITY_SEED): CityGraph {
  const nodes = [];
  for (const j of ROAD_IDX)
    for (const i of ROAD_IDX)
      nodes.push({ id: `n:${i}:${j}`, x: tc(i), z: tc(j), kind: 'junction' as const });
  const edges = [];
  for (const j of ROAD_IDX)
    for (let k = 0; k < ROAD_IDX.length - 1; k++) {
      const a = `n:${ROAD_IDX[k]}:${j}`, b = `n:${ROAD_IDX[k + 1]}:${j}`;
      edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
    }
  for (const i of ROAD_IDX)
    for (let k = 0; k < ROAD_IDX.length - 1; k++) {
      const a = `n:${i}:${ROAD_IDX[k]}`, b = `n:${i}:${ROAD_IDX[k + 1]}`;
      edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
    }
  return { version: 1, seed, car_policy: 'cars', nodes, edges };
}

/** A diamond (axis-aligned square rotated 45°): every edge runs diagonally in
 *  both world and tile space, so the axis-aligned street model names none of
 *  them — the shape a pentagon/radial morph presents to the street namer. */
function diamondGraph(seed = DEFAULT_CITY_SEED): CityGraph {
  const nodes = [
    { id: 'n', x: 0, z: 13, kind: 'junction' as const },
    { id: 'e', x: 13, z: 0, kind: 'junction' as const },
    { id: 's', x: 0, z: -13, kind: 'junction' as const },
    { id: 'w', x: -13, z: 0, kind: 'junction' as const },
  ];
  const edge = (a: string, b: string) =>
    ({ id: `e:${a}${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
  const edges = [edge('n', 'e'), edge('e', 's'), edge('s', 'w'), edge('w', 'n')];
  return { version: 1, seed, car_policy: 'cars', nodes, edges };
}

describe('EM-273 — streets/labels/cars derive from EDGES, not node coords', () => {
  const seed = DEFAULT_CITY_SEED;

  it('an east stub (an EW extension) mints NO phantom NS street at its x-column', () => {
    const g = classicGridGraph(seed);
    // apply_build_road east one block off the right ring: node n:17:2 + the EW
    // edge e:n:12:2->n:17:2. Pre-fix, node n:17:2 (x = tc(17)) minted `ns:17`.
    g.nodes.push({ id: 'n:17:2', x: tc(17), z: tc(2), kind: 'junction' as const });
    g.edges.push({ id: 'e:n:12:2->n:17:2', a: 'n:12:2', b: 'n:17:2', road_class: 'street' as const, car_policy: 'inherit' as const });

    const streets = computeStreets(seed, g);
    expect(streets.some((s) => s.id === 'ns:17')).toBe(false); // no phantom column
    expect(streets).toHaveLength(12); // ew:2 already existed ⇒ still 12 streets
    // the ambient fleet never spawns a car on the phantom line either
    expect(computeTraffic(seed, streets, g).some((c) => c.id === 'car:ns:17')).toBe(false);
  });

  it('a demolished vertical column drops its NS street (and its cars)', () => {
    const base = computeStreets(seed, classicGridGraph(seed));
    expect(base.some((s) => s.id === 'ns:7')).toBe(true); // present before demolition

    // Demolish every vertical edge on column i=7; the column-7 nodes survive
    // (they still anchor EW rows), so pre-fix `ns:7` persisted with no road.
    const g = classicGridGraph(seed);
    g.edges = g.edges.filter((e) => !(e.a.startsWith('n:7:') && e.b.startsWith('n:7:')));

    const streets = computeStreets(seed, g);
    expect(streets.some((s) => s.id === 'ns:7')).toBe(false); // the road is gone ⇒ so is the street
    expect(streets.filter((s) => s.axis === 'ns')).toHaveLength(5); // 6 − 1
    expect(streets.filter((s) => s.axis === 'ew')).toHaveLength(6); // EW rows untouched
    expect(computeTraffic(seed, streets, g).some((c) => c.id === 'car:ns:7')).toBe(false);
  });

  it('labels clip to the paved span — no anchor floats over roadless terrain', () => {
    // A single partial NS street on column 2, spanning only z-tiles −3..7.
    const col = 2;
    const zs = [-3, 2, 7];
    const nodes = zs.map((z) => ({ id: `n:${col}:${z}`, x: tc(col), z: tc(z), kind: 'junction' as const }));
    const edges = [
      { id: 'e0', a: `n:${col}:${zs[0]}`, b: `n:${col}:${zs[1]}`, road_class: 'street' as const, car_policy: 'inherit' as const },
      { id: 'e1', a: `n:${col}:${zs[1]}`, b: `n:${col}:${zs[2]}`, road_class: 'street' as const, car_policy: 'inherit' as const },
    ];
    const g: CityGraph = { version: 1, seed, car_policy: 'cars', nodes, edges };

    const streets = computeStreets(seed, g);
    expect(streets).toHaveLength(1);
    const s = streets[0];
    expect(s.id).toBe('ns:2');
    expect(s.main).toBe(true);
    // STREET_LABEL_CROSS is [−2·pitch, 0, +2·pitch]; only z=0 lands within the
    // paved span [tc(−3), tc(7)] = [−6.5, 19.5]. ±26 would float off the road.
    expect(BLOCK_PITCH * 2).toBeGreaterThan(tc(7)); // sanity: +26 is past the span
    expect(s.labels).toHaveLength(1);
    expect(s.labels[0].z).toBeCloseTo(0, 9);
    expect(s.labels[0].x).toBeCloseTo(tc(2), 9);
  });

  it('a fully diagonal morph (diamond) names NO axis-aligned streets (⇒ no cars)', () => {
    const g = diamondGraph(seed);
    const streets = computeStreets(seed, g);
    expect(streets).toEqual([]); // the street/traffic model is axis-aligned only
    expect(computeTraffic(seed, streets, g)).toEqual([]);
  });

  it('is deterministic + input-order independent (partial graph)', () => {
    const g = classicGridGraph(seed);
    g.edges = g.edges.filter((e) => !(e.a.startsWith('n:7:') && e.b.startsWith('n:7:')));
    const shuffled: CityGraph = { ...g, nodes: [...g.nodes].reverse(), edges: [...g.edges].reverse() };
    expect(computeStreets(seed, shuffled)).toEqual(computeStreets(seed, g));
  });
});
