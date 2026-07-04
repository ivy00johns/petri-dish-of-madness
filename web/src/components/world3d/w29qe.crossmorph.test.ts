/**
 * W29 QE cross-lane probe 3 — EM-273 (phantom streets / off-road cars) × EM-284
 * (car ban applies post-morph), exercised TOGETHER on one mid-morph graph.
 *
 * The lane tests assert each fix on its own; this probe stresses the seam: a
 * mid-morph graph (axis-aligned grid + diagonal spokes) under a city-wide
 * 'pedestrian' ban must simultaneously produce ZERO cars AND ZERO phantom named
 * streets, and a fully-demolished line must drop both. It also characterizes one
 * residual of EM-273's "cars sweep the full ±span" clause that the fix did NOT
 * close (documented, non-blocking — see the last test).
 *
 * QE gate agent; new file (never edits a lane test).
 */
import { describe, it, expect } from 'vitest';
import type { CityGraph } from '../../types';
import { TILE, DEFAULT_CITY_SEED, computeStreets, pedestrianStreetIds } from './cityLayout';
import { computeTraffic, trafficSpan } from './trafficLayout';

const ROAD_IDX = [-13, -8, -3, 2, 7, 12];
const tc = (i: number) => (i + 0.5) * TILE;
const SEED = DEFAULT_CITY_SEED;

/** The frozen axis-aligned grid: nodes at each intersection, edges along every
 *  line between adjacent intersections. Optionally SKIP some segments to model a
 *  partially demolished / thinned line. */
function gridGraph(
  carPolicy: CityGraph['car_policy'] = 'cars',
  skip: (a: string, b: string) => boolean = () => false,
): CityGraph {
  const nodes: CityGraph['nodes'] = [];
  for (const j of ROAD_IDX)
    for (const i of ROAD_IDX)
      nodes.push({ id: `n:${i}:${j}`, x: tc(i), z: tc(j), kind: 'junction' as const });
  const edges: CityGraph['edges'] = [];
  const push = (a: string, b: string) => {
    if (!skip(a, b))
      edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
  };
  for (const j of ROAD_IDX)
    for (let k = 0; k < ROAD_IDX.length - 1; k++)
      push(`n:${ROAD_IDX[k]}:${j}`, `n:${ROAD_IDX[k + 1]}:${j}`);
  for (const i of ROAD_IDX)
    for (let k = 0; k < ROAD_IDX.length - 1; k++)
      push(`n:${i}:${ROAD_IDX[k]}`, `n:${i}:${ROAD_IDX[k + 1]}`);
  return { version: 1, seed: SEED, car_policy: carPolicy, nodes, edges };
}

/** 'adds-before-removes' mid-morph: the grid stands while two DIAGONAL spokes of
 *  the incoming topology have been spliced in (crossings + non-axis edges). */
function midMorphGraph(carPolicy: CityGraph['car_policy']): CityGraph {
  const g = gridGraph(carPolicy);
  g.nodes.push({ id: 'x0', x: 3.1, z: -3.3, kind: 'junction' as const });
  g.nodes.push({ id: 'x1', x: -4.7, z: 5.9, kind: 'junction' as const });
  g.edges.push({ id: 'sp0', a: 'n:2:2', b: 'x0', road_class: 'street' as const, car_policy: 'inherit' as const });
  g.edges.push({ id: 'sp1', a: 'x0', b: 'x1', road_class: 'street' as const, car_policy: 'inherit' as const });
  return g;
}

/** The street ids the pure axis-aligned grid mints (6 ns + 6 ew). */
const GRID_STREET_IDS = new Set<string>([
  ...ROAD_IDX.map((i) => `ns:${i}`),
  ...ROAD_IDX.map((j) => `ew:${j}`),
]);

describe('W29 probe 3 — EM-273 × EM-284 on one mid-morph graph', () => {
  it('city-wide ban ⇒ ZERO cars AND ZERO phantom streets, simultaneously', () => {
    // Sanity: with cars enabled the same mid-morph graph HAS a fleet and streets.
    const carsGraph = midMorphGraph('cars');
    const carsStreets = computeStreets(SEED, carsGraph);
    expect(computeTraffic(SEED, carsStreets, carsGraph).length).toBeGreaterThan(0);

    const banned = midMorphGraph('pedestrian');
    const streets = computeStreets(SEED, banned);
    const fleet = computeTraffic(SEED, streets, banned);

    // Zero cars: the ratified ban reaches every street the fleet runs on.
    expect(fleet).toEqual([]);
    // Zero phantom streets: every street sits on a REAL axis-aligned road line;
    // the diagonal spokes (and stray nodes) mint nothing.
    for (const s of streets) expect(GRID_STREET_IDS.has(s.id), s.id).toBe(true);
    expect(new Set(streets.map((s) => s.id))).toEqual(GRID_STREET_IDS);
    // And the ban set covers exactly those streets (nothing runnable left un-banned).
    const ped = pedestrianStreetIds(banned);
    for (const s of streets) expect(ped.has(s.id), s.id).toBe(true);
  });

  it('diagonal spokes mint no street and no car (off-road cars gone)', () => {
    const g = midMorphGraph('cars');
    const streets = computeStreets(SEED, g);
    // No street id references the diagonal spoke nodes' off-grid positions.
    expect(streets.every((s) => GRID_STREET_IDS.has(s.id))).toBe(true);
    // Every car rides a real grid street (cars only ever attach to streets).
    for (const car of computeTraffic(SEED, streets, g)) {
      const sid = car.id.replace(/^car:/, '');
      expect(GRID_STREET_IDS.has(sid), sid).toBe(true);
    }
  });

  it('demolishing a WHOLE line drops its street and its car (no phantom post-morph)', () => {
    // Remove every edge on the x=2 vertical line ⇒ the ns:2 street must vanish.
    const skipLineX2 = (a: string, b: string) => a.startsWith('n:2:') && b.startsWith('n:2:');
    const g = gridGraph('cars', skipLineX2);
    const streets = computeStreets(SEED, g);
    expect(streets.some((s) => s.id === 'ns:2')).toBe(false); // no phantom named street
    const fleet = computeTraffic(SEED, streets, g);
    expect(fleet.some((c) => c.id === 'car:ns:2')).toBe(false); // no ghost car on it
  });

  // ── Residual (DOCUMENTED, non-blocking) ──────────────────────────────────────
  // EM-273 clipped street LABELS to the paved span, but ambient CARS still sweep
  // the GLOBAL trafficSpan (CityStreet carries no paved extent; carOffset ranges
  // over ±trafficSpan(streets)). So a PARTIALLY demolished/thinned line keeps a
  // car that overshoots into its now-roadless portion — the "cars sweep the full
  // ±span → drive through roadless terrain" clause of EM-273, for the partial
  // case. Purely visual (traffic is never in the sim/replay surface); the phantom
  // -street + FULLY-off-road-car symptoms ARE fixed. Characterized here as a repro.
  it('CHARACTERIZATION: labels clip to the paved span but the car sweep does not', () => {
    // Pave x=2 only for z ≤ tc(2); the upper segments (2,2)->(2,7)->(2,12) are gone.
    const upper = new Set(['n:2:7', 'n:2:12']);
    const skipUpperX2 = (a: string, b: string) =>
      a.startsWith('n:2:') && b.startsWith('n:2:') && (upper.has(a) || upper.has(b));
    const g = gridGraph('cars', skipUpperX2);
    const streets = computeStreets(SEED, g);
    const ns2 = streets.find((s) => s.id === 'ns:2');
    expect(ns2).toBeDefined();

    // EM-273 win: labels are clipped to the paved extent (none past z = tc(2)).
    const pavedMaxZ = tc(2);
    for (const lbl of ns2!.labels) expect(lbl.z).toBeLessThanOrEqual(pavedMaxZ + 1e-6);

    // Residual: the car sweep envelope still reaches the global grid extent, well
    // past this line's paved max — any car on ns:2 drives over roadless z > tc(2).
    const span = trafficSpan(streets);
    expect(span).toBeGreaterThan(pavedMaxZ + TILE); // envelope overshoots the pavement
  });
});
