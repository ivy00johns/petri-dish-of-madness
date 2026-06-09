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
/** Villager/critter info cards readable within this distance (default framing
 *  ~40 units keeps them visible; only a real zoom-out collapses them). */
export const ENTITY_LABEL_DIST = 48;
