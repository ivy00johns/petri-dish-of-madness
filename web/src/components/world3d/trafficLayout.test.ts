import { describe, expect, it } from 'vitest';
import { computeStreets, TILE } from './cityLayout';
import type { CityGraph } from '../../types';
import {
  CAR_KINDS,
  carOffset,
  computeTraffic,
  trafficSpan,
  type TrafficCar,
} from './trafficLayout';

const HALF_PI = Math.PI / 2;
const streets = computeStreets(1337);
const cars = computeTraffic(1337, streets);
const span = trafficSpan(streets);

describe('computeTraffic (EM-169)', () => {
  it('is deterministic for a seed + streets', () => {
    expect(computeTraffic(1337, streets)).toEqual(cars);
  });

  it('spawns a modest fleet, only on interior (main) streets', () => {
    const mainCount = streets.filter((s) => s.main).length;
    expect(cars.length).toBeGreaterThan(0);
    expect(cars.length).toBeLessThanOrEqual(mainCount);
    const mainIds = new Set(streets.filter((s) => s.main).map((s) => s.id));
    for (const c of cars) {
      expect(mainIds.has(c.id.replace(/^car:/, ''))).toBe(true);
    }
  });

  it('uses real car kinds and headings consistent with axis + direction', () => {
    for (const c of cars) {
      expect(CAR_KINDS).toContain(c.kind);
      const expected =
        c.axis === 'ns' ? (c.dir === 1 ? 0 : Math.PI) : c.dir === 1 ? HALF_PI : -HALF_PI;
      expect(c.rotY).toBe(expected);
      expect(c.speed).toBeGreaterThan(0);
      expect(c.phase).toBeGreaterThanOrEqual(0);
      expect(c.phase).toBeLessThan(1);
    }
  });

  it('different seeds yield a different fleet', () => {
    const other = computeTraffic(99, streets);
    const key = (f: TrafficCar[]) => f.map((c) => `${c.id}:${c.dir}:${c.kind}`).join('|');
    expect(key(other)).not.toBe(key(cars));
  });
});

describe('carOffset (EM-169)', () => {
  it('keeps a car on its street axis and within the wrapped span', () => {
    for (const c of cars) {
      for (const t of [0, 1.3, 7.7, 50, 123.4]) {
        const { x, z } = carOffset(c, span, t);
        if (c.axis === 'ns') {
          expect(x).toBe(c.at); // constant cross-axis
          expect(z).toBeGreaterThanOrEqual(-span - 1e-6);
          expect(z).toBeLessThanOrEqual(span + 1e-6);
        } else {
          expect(z).toBe(c.at);
          expect(x).toBeGreaterThanOrEqual(-span - 1e-6);
          expect(x).toBeLessThanOrEqual(span + 1e-6);
        }
      }
    }
  });

  it('is periodic (wraps) and deterministic in time', () => {
    const c = cars[0];
    const L = 2 * span;
    const period = L / c.speed;
    const a = carOffset(c, span, 2.0);
    const b = carOffset(c, span, 2.0 + period);
    expect(a.x).toBeCloseTo(b.x, 4);
    expect(a.z).toBeCloseTo(b.z, 4);
  });
});

// ── EM-244 (S3a) — car policy gates ambient traffic ──────────────────────────
//
// A 'pedestrian' street loses its cars; a city-scope 'pedestrian' graph zeroes
// the fleet (the headline ban). The CRITICAL invariant: no graph / a city
// 'cars' graph yields the byte-identical fleet (the EM-169 baseline).

const ROAD_IDX = [-13, -8, -3, 2, 7, 12];
const tc = (i: number) => (i + 0.5) * TILE;
/** The classic_grid graph (mirrors backend citygraph.py) at a city policy. */
function gridGraph(carPolicy: 'cars' | 'pedestrian' | 'mixed' = 'cars'): CityGraph {
  const nodes = [];
  for (const j of ROAD_IDX) for (const i of ROAD_IDX)
    nodes.push({ id: `n:${i}:${j}`, x: tc(i), z: tc(j), kind: 'junction' as const });
  const edges = [];
  for (const j of ROAD_IDX) for (let k = 0; k < ROAD_IDX.length - 1; k++) {
    const a = `n:${ROAD_IDX[k]}:${j}`, b = `n:${ROAD_IDX[k + 1]}:${j}`;
    edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
  }
  for (const i of ROAD_IDX) for (let k = 0; k < ROAD_IDX.length - 1; k++) {
    const a = `n:${i}:${ROAD_IDX[k]}`, b = `n:${i}:${ROAD_IDX[k + 1]}`;
    edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
  }
  return { version: 1, seed: 1337, car_policy: carPolicy, nodes, edges };
}

describe('computeTraffic — EM-244 (S3a) car policy', () => {
  it('CRITICAL: no graph (or a cars graph) yields the byte-identical fleet', () => {
    expect(computeTraffic(1337, streets, null)).toEqual(cars);
    expect(computeTraffic(1337, streets, undefined)).toEqual(cars);
    const gCars = gridGraph('cars');
    expect(computeTraffic(1337, computeStreets(1337, gCars), gCars)).toEqual(cars);
  });

  it('city-scope pedestrian zeroes the whole fleet (the headline ban)', () => {
    const gPed = gridGraph('pedestrian');
    const pedStreets = computeStreets(1337, gPed);
    expect(cars.length).toBeGreaterThan(0); // sanity: there WAS a fleet
    expect(computeTraffic(1337, pedStreets, gPed)).toEqual([]);
  });

  it("'mixed' city policy keeps the cars (only 'pedestrian' bans them)", () => {
    const gMixed = gridGraph('mixed');
    expect(computeTraffic(1337, computeStreets(1337, gMixed), gMixed)).toEqual(cars);
  });

  it('a single pedestrian street drops only that street’s car', () => {
    const g = gridGraph('cars');
    g.edges.find((e) => e.id === 'e:n:7:2->n:12:2')!.car_policy = 'pedestrian';
    const gated = computeTraffic(1337, streets, g);
    const baseIds = new Set(cars.map((c) => c.id));
    const gatedIds = new Set(gated.map((c) => c.id));
    // the pedestrianized ew:2 street never carries a car…
    expect(gatedIds.has('car:ew:2')).toBe(false);
    // …and every other baseline car is untouched.
    for (const id of baseIds) if (id !== 'car:ew:2') expect(gatedIds.has(id)).toBe(true);
    expect(gated.length).toBe(cars.length - (baseIds.has('car:ew:2') ? 1 : 0));
  });
});
