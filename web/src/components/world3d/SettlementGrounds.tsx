/**
 * SettlementGrounds (EM-109) — a distinct GROUND footprint per agent-founded
 * settlement, so each city reads as its own place, not one origin grid + far
 * scattered buildings + a floating label.
 *
 * Why a pad, not a full re-centered CityScape: the compact Kenney city grid is
 * frozen origin-centered (cityLayout's plan, CityScape GRID_CENTER {0,0}), and
 * re-plating a whole grid per settlement in one pass would churn the EM-155
 * byte-identical goldens + the instanced perf budget. The contract's minimum
 * bar is "a distinct ground pad + that settlement's buildings + its label,
 * visually separated per center" — buildings already free-place near their
 * settlement (F1 SETTLEMENT_R) and SettlementLabels already floats the name, so
 * this component supplies the missing GROUND anchor: a paved town-square core +
 * a per-settlement grass wash + an accent rim at each `center`.
 *
 * Render law (mirrors SettlementLabels + Ground):
 *   • WORLD-FRAME DIRECT: `center` is already the ±33 world frame — rendered
 *     as-is, zero logical conversion (anti-EM-243).
 *   • Ground-disc vocabulary: translucent toon discs (the Ground.tsx district
 *     tint pattern), just above the grass, BELOW the road tiles — so the origin
 *     grid stays crisp and a distant settlement gets its own town square.
 *   • DETERMINISTIC per-settlement accent: hashUnit(id) picks a fixed tint, so
 *     two cities read distinctly and a replay renders identically. No RNG/clock.
 *   • NON-INTERACTIVE set dressing: plain decorative meshes, no pointer
 *     handlers ⇒ never raycast-picked (the Ground-disc precedent).
 *   • TOLERANT: reuses settlementLabelEntries — an absent/empty map or a
 *     malformed entry contributes nothing (never a hole, never a crash), and a
 *     settlements-OFF world renders NOTHING here (single-settlement/no-settlement
 *     worlds are unchanged).
 *
 * These are WebGL material colors (THREE.Color), explicitly OUTSIDE the CSS
 * design-token system — the same convention as Ground/CityScape/BUILDING_STYLES.
 */

import { toonMaterial } from './toon';
import { settlementTint } from './worldSpace';
import { settlementLabelEntries } from './SettlementLabels';
import type { Settlement } from '../../types';

/** Radius of the paved town-square core (world units). */
export const SETTLEMENT_CORE_RADIUS = 6.5;
/** Radius of the surrounding grass wash — the city's ground extent. */
export const SETTLEMENT_WASH_RADIUS = 17;

/** Warm paving stone for the town square (kin to CityScape PAD_COLOR). */
export const SETTLEMENT_PAVING = '#cabfa8';

// The per-settlement accent palette + tint resolver live in worldSpace
// (settlementTint) so the 2D WorldMap shares the SAME per-city color without
// importing three/drei. Re-exported here for the 3D render + its tests.
export { SETTLEMENT_TINTS, settlementTint } from './worldSpace';

/** A renderable ground footprint for one settlement (world-frame center). */
export interface SettlementGroundEntry {
  id: string;
  x: number;
  z: number;
  tint: string;
}

/**
 * The render-safe ground footprints, one per valid settlement. Reuses
 * settlementLabelEntries so the ground and the floating label always agree 1:1
 * (same tolerance: junk center / empty name skipped). The accent tint is a pure
 * function of the settlement id, so it's stable across ticks, reloads, and
 * replays.
 */
export function settlementGroundEntries(
  settlements?: Record<string, Settlement> | null,
): SettlementGroundEntry[] {
  return settlementLabelEntries(settlements).map(([id, s]) => ({
    id,
    x: s.center[0],
    z: s.center[1],
    tint: settlementTint(id),
  }));
}

/** Opacity of the wide grass wash (subtle, the Ground district-disc register). */
const WASH_OPACITY = 0.26;
/** Opacity of the paved core — reads as a real town square, not a tint. */
const CORE_OPACITY = 0.82;

/**
 * All settlement ground footprints. Absent/empty map ⇒ renders nothing (a
 * settlements-OFF world is unchanged). Mounted by CozyWorld's Scene beside
 * <Ground>, so it shares the world space + layers on the grass.
 */
export function SettlementGrounds({
  settlements,
}: {
  settlements?: Record<string, Settlement> | null;
}) {
  const entries = settlementGroundEntries(settlements);
  if (entries.length === 0) return null;
  return (
    <group name="settlement-grounds">
      {entries.map((e) => (
        <group key={e.id} name={`settlement-ground-${e.id}`}>
          {/* Grass wash — the city's ground tone (Ground district-disc register). */}
          <mesh
            rotation={[-Math.PI / 2, 0, 0]}
            position={[e.x, 0.006, e.z]}
            receiveShadow
            material={toonMaterial(e.tint, {
              transparent: true,
              opacity: WASH_OPACITY,
              depthWrite: false,
              polygonOffset: true,
            })}
          >
            <circleGeometry args={[SETTLEMENT_WASH_RADIUS, 48]} />
          </mesh>
          {/* Paved town-square core — sits ABOVE the wash, BELOW the road tiles. */}
          <mesh
            rotation={[-Math.PI / 2, 0, 0]}
            position={[e.x, 0.012, e.z]}
            receiveShadow
            material={toonMaterial(SETTLEMENT_PAVING, {
              transparent: true,
              opacity: CORE_OPACITY,
              depthWrite: false,
              polygonOffset: true,
            })}
          >
            <circleGeometry args={[SETTLEMENT_CORE_RADIUS, 40]} />
          </mesh>
          {/* Accent rim — the per-settlement tint ringing the square, so two
              cities read distinctly at a glance. */}
          <mesh
            rotation={[-Math.PI / 2, 0, 0]}
            position={[e.x, 0.014, e.z]}
            material={toonMaterial(e.tint, {
              transparent: true,
              opacity: 0.9,
              depthWrite: false,
              polygonOffset: true,
            })}
          >
            <ringGeometry args={[SETTLEMENT_CORE_RADIUS * 0.92, SETTLEMENT_CORE_RADIUS, 48]} />
          </mesh>
        </group>
      ))}
    </group>
  );
}
