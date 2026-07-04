/**
 * EM-284 regression — a city-wide 'pedestrian' ban reaches the whole fleet after
 * a morph.
 *
 * `pedestrianStreetIds` (the set of streets that lose their cars) mapped an edge
 * to a street line with a bare `ai === bi` / `else if aj === bj`, silently
 * skipping non-axis-aligned edges and mis-flagging degenerate single-tile ones.
 * The fix uses the SAME axis test as the street set (roadLinesFrom, EM-273):
 * `ai === bi && aj !== bj` ⇒ ns, `aj === bj && ai !== bi` ⇒ ew, checked
 * independently. Together with EM-273 (streets/cars derive from edges) a ratified
 * ban now zeroes every street the fleet actually runs on, regardless of the
 * post-morph topology — a purely diagonal edge maps to no axis-aligned street,
 * so the fleet never runs there and there is nothing to ban.
 */

import { describe, it, expect } from 'vitest';
import type { CityGraph } from '../../types';
import { TILE, DEFAULT_CITY_SEED, computeStreets, pedestrianStreetIds } from './cityLayout';
import { computeTraffic } from './trafficLayout';

const ROAD_IDX = [-13, -8, -3, 2, 7, 12];
const tc = (i: number) => (i + 0.5) * TILE;

function classicGridGraph(carPolicy: CityGraph['car_policy'] = 'cars', seed = DEFAULT_CITY_SEED): CityGraph {
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
  return { version: 1, seed, car_policy: carPolicy, nodes, edges };
}

/** Mid-morph 'adds-before-removes': the grid still stands while two diagonal
 *  spokes of the new topology have been added. */
function midMorphGraph(carPolicy: CityGraph['car_policy']): CityGraph {
  const g = classicGridGraph(carPolicy);
  g.nodes.push({ id: 'x0', x: 3.1, z: -3.3, kind: 'junction' as const });
  g.nodes.push({ id: 'x1', x: -4.7, z: 5.9, kind: 'junction' as const });
  g.edges.push({ id: 'sp0', a: 'n:2:2', b: 'x0', road_class: 'street' as const, car_policy: 'inherit' as const });
  g.edges.push({ id: 'sp1', a: 'x0', b: 'x1', road_class: 'street' as const, car_policy: 'inherit' as const });
  return g;
}

describe('EM-284 — car policy applies regardless of edge orientation', () => {
  const seed = DEFAULT_CITY_SEED;

  it('a city-wide pedestrian ban zeroes the fleet even mid-morph (grid + diagonals)', () => {
    const carsFleet = computeTraffic(seed, computeStreets(seed, midMorphGraph('cars')), midMorphGraph('cars'));
    expect(carsFleet.length).toBeGreaterThan(0); // sanity: there WAS a fleet

    const g = midMorphGraph('pedestrian');
    const banned = computeTraffic(seed, computeStreets(seed, g), g);
    expect(banned).toEqual([]); // the ratified ban reaches every axis-aligned street
  });

  it('pedestrianStreetIds covers every street the fleet runs on (city-wide ban)', () => {
    const g = midMorphGraph('pedestrian');
    const ped = pedestrianStreetIds(g);
    for (const s of computeStreets(seed, g)) {
      expect(ped.has(s.id), s.id).toBe(true);
    }
  });

  it('maps each edge by its true orientation (vertical→ns, horizontal→ew, diagonal→none)', () => {
    const mk = (a: [number, number], b: [number, number]): CityGraph => ({
      version: 1, seed, car_policy: 'pedestrian',
      nodes: [
        { id: 'a', x: a[0], z: a[1], kind: 'junction' },
        { id: 'b', x: b[0], z: b[1], kind: 'junction' },
      ],
      edges: [{ id: 'e', a: 'a', b: 'b', road_class: 'street', car_policy: 'inherit' }],
    });
    // vertical (constant x): flags only the ns line, never an ew line
    expect([...pedestrianStreetIds(mk([tc(2), tc(-3)], [tc(2), tc(7)]))]).toEqual(['ns:2']);
    // horizontal (constant z): flags only the ew line
    expect([...pedestrianStreetIds(mk([tc(-3), tc(2)], [tc(7), tc(2)]))]).toEqual(['ew:2']);
    // diagonal: no axis-aligned street ⇒ nothing to ban (no phantom flag)
    expect([...pedestrianStreetIds(mk([tc(2), tc(2)], [tc(7), tc(7)]))]).toEqual([]);
    // degenerate single-tile edge (both ends in one tile): no phantom ns flag
    expect([...pedestrianStreetIds(mk([tc(2), tc(2)], [tc(2), tc(2)]))]).toEqual([]);
  });

  it('is input-order independent', () => {
    const g = midMorphGraph('pedestrian');
    const shuffled: CityGraph = { ...g, edges: [...g.edges].reverse(), nodes: [...g.nodes].reverse() };
    expect([...pedestrianStreetIds(shuffled)].sort()).toEqual([...pedestrianStreetIds(g)].sort());
  });
});
