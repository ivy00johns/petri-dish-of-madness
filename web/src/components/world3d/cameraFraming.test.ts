/**
 * cameraFraming tests (EM-121) — the multi-city camera framing math:
 *   • fitDistance frames a ground extent within the vertical fov (with margin)
 *     and is clamped to the OrbitControls zoom range, so every result is a
 *     distance the controls can actually hold;
 *   • SETTLEMENT_FOCUS_DIST frames one WHOLE settlement cluster (the wash
 *     footprint) — the zoom-to-city dolly, wider than the single-building one;
 *   • settlementOverview is the reset-view home: null under two centers (the
 *     single-city reset stays byte-identical), bounding-box-centered target,
 *     never tighter than the default framing, growing with spread, clamped at
 *     the zoom-out limit.
 * Pure functions only; no three, no R3F.
 */

import { describe, expect, it } from 'vitest';
import {
  CAMERA_FOV_DEG,
  FIT_MARGIN,
  MIN_ORBIT_DIST,
  MAX_ORBIT_DIST,
  fitDistance,
  SETTLEMENT_FOCUS_DIST,
  settlementOverview,
} from './cameraFraming';
import { SETTLEMENT_WASH_RADIUS } from './SettlementGrounds';

/** The unclamped vertical-fov fit — the formula the module must implement. */
function rawFit(radius: number): number {
  return (radius * FIT_MARGIN) / Math.tan((CAMERA_FOV_DEG * Math.PI) / 360);
}

describe('fitDistance (EM-121)', () => {
  it('is the vertical-fov fit with margin for in-range extents', () => {
    expect(fitDistance(17)).toBeCloseTo(rawFit(17), 6);
    expect(fitDistance(30)).toBeCloseTo(rawFit(30), 6);
  });

  it('clamps to the OrbitControls zoom range (always a holdable distance)', () => {
    expect(fitDistance(0)).toBe(MIN_ORBIT_DIST);
    expect(fitDistance(1000)).toBe(MAX_ORBIT_DIST);
  });

  it('is monotonic in the framed extent', () => {
    expect(fitDistance(10)).toBeLessThan(fitDistance(20));
    expect(fitDistance(20)).toBeLessThan(fitDistance(40));
  });
});

describe('SETTLEMENT_FOCUS_DIST (zoom-to-city dolly)', () => {
  it('frames the whole cluster footprint (the wash radius), within range', () => {
    expect(SETTLEMENT_FOCUS_DIST).toBe(fitDistance(SETTLEMENT_WASH_RADIUS));
    expect(SETTLEMENT_FOCUS_DIST).toBeGreaterThan(MIN_ORBIT_DIST);
    expect(SETTLEMENT_FOCUS_DIST).toBeLessThan(MAX_ORBIT_DIST);
  });
});

describe('settlementOverview (multi-settlement reset-view home)', () => {
  const MIN_D = 88; // the default single-city framing distance, roughly

  it('is null under two centers — single-/no-settlement reset is unchanged', () => {
    expect(settlementOverview([], MIN_D)).toBeNull();
    expect(settlementOverview([[3, -4]], MIN_D)).toBeNull();
  });

  it('targets the bounding-box center of ALL settlement centers', () => {
    const o = settlementOverview([[0, 0], [24, 18]], MIN_D)!;
    expect(o.x).toBeCloseTo(12, 6);
    expect(o.z).toBeCloseTo(9, 6);
    // Three cities: the bbox center, not the centroid.
    const o3 = settlementOverview([[0, 0], [24, 18], [24, 0]], MIN_D)!;
    expect(o3.x).toBeCloseTo(12, 6);
    expect(o3.z).toBeCloseTo(9, 6);
  });

  it('fits the farthest cluster + its wash footprint, never tighter than the default', () => {
    // Spread demands more than the default framing → fitted distance wins.
    const wide = settlementOverview([[0, 0], [24, 18]], MIN_D)!;
    const spread = Math.hypot(12, 9); // farthest center from the bbox center
    expect(wide.distance).toBeCloseTo(rawFit(spread + SETTLEMENT_WASH_RADIUS), 6);
    expect(wide.distance).toBeGreaterThan(MIN_D);
    // Two near-coincident cities → the default framing already fits.
    const tight = settlementOverview([[0, 0], [2, 2]], MIN_D)!;
    expect(tight.distance).toBe(MIN_D);
  });

  it('grows with spread and clamps at the zoom-out limit', () => {
    const near = settlementOverview([[0, 0], [20, 0]], 0)!;
    const far = settlementOverview([[0, 0], [40, 0]], 0)!;
    expect(near.distance).toBeLessThan(far.distance);
    const corners = settlementOverview([[-33, -33], [33, 33]], MIN_D)!;
    expect(corners.distance).toBe(MAX_ORBIT_DIST);
  });
});
