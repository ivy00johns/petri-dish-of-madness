/**
 * useProximity (EM-102) — distance-gated label visibility for the 3D village.
 *
 * Every new building used to add another always-on floating label until they
 * overlapped each other AND the villager/critter chips. This hook tells a
 * label whether the camera is close enough for the FULL card; beyond the
 * threshold callers render a minimal marker (or nothing) instead.
 *
 * Implementation notes:
 *   • The position is read through a getter so MOVING entities (villagers,
 *     critters — their anim refs mutate every frame) gate correctly without
 *     re-subscribing.
 *   • Hysteresis (show at `dist`, hide at `dist + HYSTERESIS`) prevents
 *     flicker while orbiting right on the boundary.
 *   • setState fires ONLY on threshold crossings — per-frame cost is one
 *     distance computation, no re-renders while nothing changes.
 */

import { useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';

const HYSTERESIS = 4;

export interface ProximityPoint {
  x: number;
  z: number;
}

/**
 * True while the camera is within `dist` world units of the (ground-plane)
 * point — full 3D distance to (x, 0, z), so zooming out vertically also
 * collapses labels.
 */
export function useProximity(getPoint: () => ProximityPoint, dist: number): boolean {
  const [near, setNear] = useState(false);
  const nearRef = useRef(false);

  useFrame(({ camera }) => {
    const p = getPoint();
    const dx = camera.position.x - p.x;
    const dz = camera.position.z - p.z;
    const dy = camera.position.y;
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
    const next = nearRef.current ? d < dist + HYSTERESIS : d < dist;
    if (next !== nearRef.current) {
      nearRef.current = next;
      setNear(next);
    }
  });

  return near;
}

/** Full place/structure label readable within this camera distance. */
export const PLACE_LABEL_DIST = 32;

/**
 * NEAR-fade (zoom-in declutter). Every floating label used to sit at FULL opacity
 * all the way down to the camera's closest zoom (minDistance 14) — so a deep zoom
 * onto a dense plaza stacked a dozen world-space labels into an unreadable wall of
 * text that BURIED the buildings and villagers behind it. This law fades labels OUT
 * as the camera closes in past `NEAR_LABEL_FADE_FULL`, reaching 0 at
 * `NEAR_LABEL_FADE_GONE`, so zooming all the way in reveals the geometry (the whole
 * point of zooming in). It multiplies the existing FAR laws (landmarkLabelTransform,
 * structureLabelFade) — no effect at the default framing (~95u) or any zoom-out.
 * Tunable; calibrated against minDistance 14 / default framing ~95.
 */
export const NEAR_LABEL_FADE_GONE = 18;
export const NEAR_LABEL_FADE_FULL = 34;

/** 0 at/below NEAR_LABEL_FADE_GONE (labels cleared for a clean close-up), 1 at/above
 *  NEAR_LABEL_FADE_FULL (no near suppression), linear between. Pure + unit-testable. */
export function nearLabelFade(d: number): number {
  if (d >= NEAR_LABEL_FADE_FULL) return 1;
  if (d <= NEAR_LABEL_FADE_GONE) return 0;
  return (d - NEAR_LABEL_FADE_GONE) / (NEAR_LABEL_FADE_FULL - NEAR_LABEL_FADE_GONE);
}
/** Villager/critter info cards readable within this distance (default framing
 *  ~40 units keeps them visible; only a real zoom-out collapses them). */
export const ENTITY_LABEL_DIST = 48;

/**
 * EM-192(c): the fade BAND past `PLACE_LABEL_DIST` over which a proximity-gated
 * structure label ramps from full opacity to 0. The boolean `useProximity`
 * (with HYSTERESIS) decides WHETHER the full card mounts; this law decides how
 * SOLID it is while it's up, so a label dissolves over the last few world units
 * before the marker takes over instead of popping out.
 */
export const STRUCTURE_LABEL_FADE_BAND = 6;

/**
 * Pure distance→opacity law for a proximity-gated structure label. Full ink
 * (1) while the camera is inside `PLACE_LABEL_DIST`; a linear ramp down to 0
 * across the next `STRUCTURE_LABEL_FADE_BAND` world units; clamped 0..1 beyond.
 * Kept a pure function (separate from the component) so the fade is unit-testable.
 */
export function structureLabelFade(
  d: number,
  dist: number = PLACE_LABEL_DIST,
  band: number = STRUCTURE_LABEL_FADE_BAND,
): number {
  if (d <= dist) return 1;
  if (band <= 0) return 0;
  return Math.max(0, Math.min(1, 1 - (d - dist) / band));
}
