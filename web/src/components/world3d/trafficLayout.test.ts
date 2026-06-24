import { describe, expect, it } from 'vitest';
import { computeStreets } from './cityLayout';
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
