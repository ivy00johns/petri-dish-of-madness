/**
 * worldSpace multi-city helpers (EM-109/110):
 *   • toLogicalX/Y are exact inverses of toWorldX/Z (the 2D WorldMap converts a
 *     world-frame settlement center back to its logical 0..1000 draw frame);
 *   • settlementTint is deterministic per id, from the curated palette, so the
 *     3D ground rim and 2D map marker read as the SAME color for a given city.
 * Pure functions only.
 */

import { describe, expect, it } from 'vitest';
import {
  SIZE,
  toWorldX,
  toWorldZ,
  toLogicalX,
  toLogicalY,
  SETTLEMENT_TINTS,
  settlementTint,
} from './worldSpace';

describe('logical↔world inverses (EM-109)', () => {
  it('toLogicalX(toWorldX(x)) === x across the logical range', () => {
    for (const x of [0, 123.4, 500, 777, 1000]) {
      expect(toLogicalX(toWorldX(x))).toBeCloseTo(x, 6);
    }
  });

  it('toLogicalY(toWorldZ(y)) === y across the logical range', () => {
    for (const y of [0, 250, 500.5, 999]) {
      expect(toLogicalY(toWorldZ(y))).toBeCloseTo(y, 6);
    }
  });

  it('maps the world origin to the logical center (500)', () => {
    expect(toLogicalX(0)).toBeCloseTo(500, 6);
    expect(toLogicalY(0)).toBeCloseTo(500, 6);
  });

  it('maps a world-frame edge (±SIZE/2) to the logical extremes', () => {
    expect(toLogicalX(SIZE / 2)).toBeCloseTo(1000, 6);
    expect(toLogicalX(-SIZE / 2)).toBeCloseTo(0, 6);
  });
});

describe('settlementTint (EM-109)', () => {
  it('is deterministic for a given id', () => {
    expect(settlementTint('stl_alpha')).toBe(settlementTint('stl_alpha'));
  });

  it('always returns a palette color', () => {
    for (const id of ['a', 'stl_1', 'genesis', 'ZZZ', 'stl_beta']) {
      expect(SETTLEMENT_TINTS).toContain(settlementTint(id));
    }
  });

  it('distinguishes at least two different cities across a handful of ids', () => {
    const tints = new Set(
      ['stl_1', 'stl_2', 'stl_3', 'genesis', 'larkspur', 'hearthford'].map(settlementTint),
    );
    expect(tints.size).toBeGreaterThan(1);
  });
});
