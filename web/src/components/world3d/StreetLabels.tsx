/**
 * StreetLabels (EM-188) — small in-world street-name labels for the named
 * streets of the frozen city grid (cityLayout.computeStreets).
 *
 * Render law:
 *   • PAINTED ON THE ROAD: each label lies FLAT on its road surface (the
 *     classic painted street-name treatment) at a mid-block anchor, aligned
 *     along the street's axis. Flat-on-ground by construction means street
 *     names can NEVER collide with the floating Billboard labels of places
 *     (Building) or agent-built structures (Structure) — they live in a
 *     different plane entirely.
 *   • ZOOM-GATED exactly like the EM-102 pattern: each anchor reuses the
 *     existing `useProximity` hook at the existing PLACE_LABEL_DIST
 *     threshold (32u) — no new gating system. The default city framing sits
 *     ~89u out, so the default zoom shows ZERO street labels; names fade in
 *     (mount) only when the camera dives toward a street.
 *   • SPARSE: only `main` streets (interior avenues) carry anchors — the
 *     outer ring road is unlabeled (cityLayout's sparse-label law), and
 *     anchors sit mid-block, never on intersections.
 *
 * Mounted by CozyWorld INSIDE the <Canvas> (useProximity needs the R3F
 * frame loop — this is why it does not live in CityScape, whose jsdom smoke
 * tests render without an R3F root). Colors come from the shared toon label
 * inks (LABEL_INK/LABEL_OUTLINE) — no hex literals here; the GPU scene's
 * palette stays centralized in toon.ts (design-token-guard governs DOM/CSS).
 */

import { useCallback } from 'react';
import { Text } from '@react-three/drei';
import type { CityStreet, StreetLabelAnchor } from './cityLayout';
import { useProximity, PLACE_LABEL_DIST } from './useProximity';
import { LABEL_INK, LABEL_OUTLINE } from './toon';

/** EM-188 gate = the existing EM-102 place-label threshold (reused, not a
 *  new system). Default framing ≈ 89u ⇒ no street labels at default zoom. */
export const STREET_LABEL_DIST = PLACE_LABEL_DIST;

/** Hover height above the road tiles (~0.02–0.05 tall) — clears z-fighting. */
export const STREET_LABEL_Y = 0.12;

/**
 * Pure: the flat-on-ground rotation for a street label. Euler XYZ — Rz spins
 * the text in its plane first, then Rx(-π/2) lays it onto the road:
 *   • 'ew' streets run along X → text baseline stays on X.
 *   • 'ns' streets run along Z → in-plane quarter turn first.
 * Readable from above in the default camera hemisphere (+X/+Z side).
 */
export function streetLabelRotation(axis: CityStreet['axis']): [number, number, number] {
  return axis === 'ns' ? [-Math.PI / 2, 0, Math.PI / 2] : [-Math.PI / 2, 0, 0];
}

/** One proximity-gated painted label at a single road anchor. */
function StreetLabel({
  street,
  anchor,
}: {
  street: CityStreet;
  anchor: StreetLabelAnchor;
}) {
  const { x, z } = anchor;
  const near = useProximity(useCallback(() => ({ x, z }), [x, z]), STREET_LABEL_DIST);
  if (!near) return null;
  return (
    <group position={[x, STREET_LABEL_Y, z]} rotation={streetLabelRotation(street.axis)}>
      <Text
        fontSize={0.6}
        color={LABEL_INK}
        anchorX="center"
        anchorY="middle"
        outlineWidth={0.02}
        outlineColor={LABEL_OUTLINE}
        whiteSpace="nowrap"
        letterSpacing={0.08}
        fillOpacity={0.85}
      >
        {street.name}
      </Text>
    </group>
  );
}

/** All street-name labels of a plan: main streets × mid-block anchors. */
export function StreetLabels({ streets }: { streets: CityStreet[] }) {
  return (
    <group name="street-labels">
      {streets
        .filter((s) => s.main)
        .flatMap((s) =>
          s.labels.map((a, i) => (
            <StreetLabel key={`${s.id}:${i}`} street={s} anchor={a} />
          )),
        )}
    </group>
  );
}
