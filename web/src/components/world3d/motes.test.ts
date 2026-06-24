import { describe, expect, it } from 'vitest';
import { computeMotes, motePosition } from './motes';

const HALF = 38;
const Y_MIN = 0.6;
const Y_MAX = 9;
const field = computeMotes(1337);

describe('computeMotes (EM-127)', () => {
  it('is deterministic for a seed', () => {
    expect(computeMotes(1337)).toEqual(field);
  });

  it('honours count and scatters within bounds', () => {
    const f = computeMotes(7, { count: 50 });
    expect(f).toHaveLength(50);
    for (const m of f) {
      expect(Math.abs(m.x)).toBeLessThanOrEqual(HALF);
      expect(Math.abs(m.z)).toBeLessThanOrEqual(HALF);
      expect(m.y).toBeGreaterThanOrEqual(Y_MIN);
      expect(m.y).toBeLessThanOrEqual(Y_MAX);
      expect(m.ax).toBeGreaterThan(0);
      expect(m.ay).toBeGreaterThan(0);
      expect(m.az).toBeGreaterThan(0);
      expect(m.speed).toBeGreaterThan(0);
    }
  });

  it('different seeds yield a different field', () => {
    const key = (f: ReturnType<typeof computeMotes>) =>
      f.map((m) => `${m.x.toFixed(3)},${m.z.toFixed(3)}`).join('|');
    expect(key(computeMotes(99))).not.toBe(key(field));
  });
});

describe('motePosition (EM-127)', () => {
  it('stays within base ± drift amplitude for all t', () => {
    for (const m of field.slice(0, 20)) {
      for (const t of [0, 2.5, 31.7, 600]) {
        const p = motePosition(m, t);
        expect(Math.abs(p.x - m.x)).toBeLessThanOrEqual(m.ax + 1e-9);
        expect(Math.abs(p.y - m.y)).toBeLessThanOrEqual(m.ay + 1e-9);
        expect(Math.abs(p.z - m.z)).toBeLessThanOrEqual(m.az + 1e-9);
      }
    }
  });

  it('is deterministic in time', () => {
    const m = field[0];
    expect(motePosition(m, 12.34)).toEqual(motePosition(m, 12.34));
  });
});
