/**
 * SettlementLabels (EM-269 F2) — floating settlement-name markers in the 3-D
 * world, one per agent-founded settlement (world.settlements).
 *
 * Render law:
 *   • WORLD-FRAME DIRECT: a settlement's `center` is already the ±33 world
 *     frame the backend founded it in (converted ONCE, backend-side — the
 *     anti-EM-243 discipline). Rendered as-is, zero conversion here.
 *   • EXISTING LABEL CHROME: drei <Billboard> + <Text> with the shared toon
 *     label inks (LABEL_INK/LABEL_OUTLINE) — the Building place-label
 *     treatment, not a new system. No hex literals; the GPU palette stays
 *     centralized in toon.ts.
 *   • ALWAYS VISIBLE (no proximity gate): settlements are the emergent
 *     multi-city signature — a far-corner town must read from the default
 *     framing, exactly what a zoom gate would hide. There are at most a
 *     handful of settlements (founding is claimed-ground-gated), so the
 *     sparse-label law holds without gating.
 *   • CLICK = ZOOM-TO-CITY (EM-121): with `onPick` wired, clicking a marker
 *     focuses its settlement (the Building onPick pattern — stopPropagation +
 *     hover cursor). Without it the markers stay inert set dressing.
 *   • TOLERANT: absent/null map, malformed center, or an empty name ⇒ that
 *     entry is skipped (never a hole, never a crash) — old backends and
 *     partial snapshots render nothing.
 *
 * Mounted by CozyWorld INSIDE the <Canvas> beside StreetLabels.
 */

import { useState } from 'react';
import { Billboard, Text, useCursor } from '@react-three/drei';
import type { Settlement } from '../../types';
import { LABEL_INK, LABEL_OUTLINE } from './toon';

/** Marker hover height (world units): above every structure + floating place
 *  label (structures top out well below this), so names never collide. */
export const SETTLEMENT_LABEL_Y = 7.5;

/** Pure: the render-safe entries of a settlements map (skip malformed). */
export function settlementLabelEntries(
  settlements?: Record<string, Settlement> | null,
): Array<[string, Settlement]> {
  return Object.entries(settlements ?? {}).filter(
    ([, s]) =>
      !!s &&
      typeof s.name === 'string' &&
      s.name.length > 0 &&
      Array.isArray(s.center) &&
      s.center.length === 2 &&
      Number.isFinite(s.center[0]) &&
      Number.isFinite(s.center[1]),
  );
}

/** All settlement-name markers. Absent/empty map ⇒ renders nothing. */
export function SettlementLabels({
  settlements,
  onPick,
}: {
  settlements?: Record<string, Settlement> | null;
  /** EM-121: a settlement marker was clicked (zoom-to-city). */
  onPick?: (settlementId: string) => void;
}) {
  const [hovered, setHovered] = useState(false);
  useCursor(hovered && Boolean(onPick));
  const entries = settlementLabelEntries(settlements);
  if (entries.length === 0) return null;
  return (
    <group name="settlement-labels">
      {entries.map(([id, s]) => (
        <Billboard
          key={id}
          position={[s.center[0], SETTLEMENT_LABEL_Y, s.center[1]]}
          onClick={
            onPick
              ? (e) => {
                  e.stopPropagation();
                  onPick(id);
                }
              : undefined
          }
          onPointerOver={
            onPick
              ? (e) => {
                  e.stopPropagation();
                  setHovered(true);
                }
              : undefined
          }
          onPointerOut={onPick ? () => setHovered(false) : undefined}
        >
          <Text
            fontSize={1.1}
            color={LABEL_INK}
            anchorX="center"
            anchorY="middle"
            outlineWidth={0.04}
            outlineColor={LABEL_OUTLINE}
            whiteSpace="nowrap"
            letterSpacing={0.08}
            fillOpacity={0.9}
          >
            {s.name}
          </Text>
        </Billboard>
      ))}
    </group>
  );
}
