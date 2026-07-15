/**
 * cameraFraming (EM-121) — pure framing math for the multi-city camera:
 *   • fitDistance: the orbit radius at which a ground disc of a given radius
 *     fills the vertical field of view (with margin), clamped to the
 *     OrbitControls zoom range;
 *   • SETTLEMENT_FOCUS_DIST: the zoom-to-city dolly distance — frames one whole
 *     settlement cluster (the SETTLEMENT_WASH_RADIUS footprint), not the tight
 *     single-building FOCUS_DOLLY_DIST;
 *   • settlementOverview: the reset-view home for a MULTI-settlement world —
 *     the bounding center of ALL settlement centers plus the orbit distance
 *     that fits every cluster. Fewer than two centers ⇒ null, so the caller
 *     keeps the existing single-city home (EM-183 civic center) unchanged.
 *
 * Pure + deterministic (no three, no R3F) so the framing is unit-testable.
 * Coordinates are WORLD-frame (±33), the same frame Settlement.center is
 * stored in (anti-EM-243).
 */

import { SETTLEMENT_WASH_RADIUS } from './SettlementGrounds';

// MIRROR of CozyWorld's camera chrome (Canvas fov, OrbitControls min/max
// distance) — change them TOGETHER or the fit math frames the wrong extent.
/** Vertical field of view (CozyWorld <Canvas camera fov>). */
export const CAMERA_FOV_DEG = 42;
/** OrbitControls minDistance (CozyWorld <OrbitControls>). */
export const MIN_ORBIT_DIST = 14;
/** OrbitControls maxDistance (CozyWorld <OrbitControls>). */
export const MAX_ORBIT_DIST = 130;

/** Breathing room around the framed extent (1 = edges touch the frustum). */
export const FIT_MARGIN = 1.12;

/**
 * The orbit distance at which a ground extent of `radius` world units fits the
 * vertical fov (with FIT_MARGIN), clamped to the OrbitControls zoom range —
 * so the result is always a distance the controls can actually hold.
 */
export function fitDistance(radius: number): number {
  const halfFov = (CAMERA_FOV_DEG * Math.PI) / 360;
  const d = (radius * FIT_MARGIN) / Math.tan(halfFov);
  return Math.min(MAX_ORBIT_DIST, Math.max(MIN_ORBIT_DIST, d));
}

/**
 * Zoom-to-city dolly distance: frames one whole settlement cluster (paved core
 * + grass wash), where the single-building zoom-to-place distance would crop it.
 */
export const SETTLEMENT_FOCUS_DIST = fitDistance(SETTLEMENT_WASH_RADIUS);

/** The multi-settlement reset-view home: orbit target (x,z) + orbit radius. */
export interface OverviewFrame {
  x: number;
  z: number;
  distance: number;
}

/**
 * The default multi-settlement overview: centers the orbit target on the
 * bounding box of ALL settlement centers and picks the orbit distance that
 * fits the farthest cluster (its center distance + the cluster's own
 * SETTLEMENT_WASH_RADIUS footprint), never tighter than `minDistance` (the
 * default single-city framing) and never beyond the controls' zoom range.
 * Fewer than two valid centers ⇒ null — the caller keeps the existing
 * single-/no-settlement home, so those worlds reset exactly as before.
 */
export function settlementOverview(
  centers: ReadonlyArray<readonly [number, number]>,
  minDistance: number,
): OverviewFrame | null {
  if (centers.length < 2) return null;
  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (const [x, z] of centers) {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (z < minZ) minZ = z;
    if (z > maxZ) maxZ = z;
  }
  const cx = (minX + maxX) / 2;
  const cz = (minZ + maxZ) / 2;
  let spread = 0;
  for (const [x, z] of centers) {
    const d = Math.hypot(x - cx, z - cz);
    if (d > spread) spread = d;
  }
  const distance = Math.max(
    minDistance,
    fitDistance(spread + SETTLEMENT_WASH_RADIUS),
  );
  return { x: cx, z: cz, distance };
}
