/**
 * WorldMap multi-city tests (EM-109) — the 2D macro map draws SETTLEMENTS.
 *
 * settlementMapPoints is the data the canvas plots: each founded city's
 * WORLD-frame center converted back to the map's LOGICAL (0..1000) draw frame,
 * with the per-city tint shared with the 3D SettlementGrounds rim. Tolerant like
 * SettlementLabels (junk skipped) and free of any R3F import.
 */

import { describe, expect, it } from 'vitest';
import { settlementMapPoints } from './WorldMap';
import { settlementTint } from '../world3d/worldSpace';
import type { Settlement } from '../../types';

describe('settlementMapPoints (EM-109)', () => {
  it('converts each settlement world-frame center to the logical draw frame', () => {
    const pts = settlementMapPoints({
      genesis: { name: 'Hearthford', center: [0, 0] },      // origin → logical center
      east: { name: 'Larkspur', center: [16.5, 0] },        // +SIZE/4 → logical 750
    });
    expect(pts).toHaveLength(2);
    const byId = Object.fromEntries(pts.map((p) => [p.id, p]));
    expect(byId.genesis.lx).toBeCloseTo(500, 4);
    expect(byId.genesis.ly).toBeCloseTo(500, 4);
    expect(byId.east.lx).toBeCloseTo(750, 4);
    expect(byId.east.ly).toBeCloseTo(500, 4);
  });

  it('carries the name + the per-city tint (shared with the 3D rim)', () => {
    const pts = settlementMapPoints({ stl_2: { name: 'Larkspur', center: [10, -10] } });
    expect(pts[0].name).toBe('Larkspur');
    expect(pts[0].tint).toBe(settlementTint('stl_2'));
  });

  it('draws two DISTINCT cities (the macro "cities on the grid")', () => {
    const pts = settlementMapPoints({
      a: { name: 'Alpha', center: [-20, -20] },
      b: { name: 'Beta', center: [20, 20] },
    });
    expect(pts).toHaveLength(2);
    expect(pts[0].lx).not.toBeCloseTo(pts[1].lx, 2);
  });

  it('is tolerant: junk skipped, empty/absent ⇒ []', () => {
    const junk = {
      ok: { name: 'Keep', center: [0, 0] },
      noname: { name: '', center: [1, 2] },
      badcenter: { name: 'X', center: [Number.NaN, 0] },
      nocenter: { name: 'Y' },
    } as unknown as Record<string, Settlement>;
    expect(settlementMapPoints(junk).map((p) => p.id)).toEqual(['ok']);
    expect(settlementMapPoints({})).toEqual([]);
    expect(settlementMapPoints(null)).toEqual([]);
    expect(settlementMapPoints(undefined)).toEqual([]);
  });
});
