/**
 * PlacedProps — the Wave K (EM-218) renderer for agent/god-placed `Prop`s.
 *
 * Reads `world.props` and draws each one at its place center plus the engine-
 * assigned in-place offset (placeToWorld(place) + (dx, dz)), so co-located
 * props fan out around the anchor instead of stacking. Each prop renders its
 * vendored GLB through the shared <Model> wrapper, wrapped in a <ModelBoundary>
 * whose fallback is a small PROCEDURAL marker — the Wave C/EM-148 fallback
 * invariant: a prop is NEVER a hole (it shows while the GLB streams, forever if
 * the load fails, and as the only render for an unknown/off-menu kind).
 *
 * Placement is pure: it reads place coordinates + the prop's own (dx,dz). No
 * Math.random / Date on this path (the city-layout determinism invariant — the
 * offsets are engine-assigned and serialized; the frontend only reads them).
 */

import { useMemo } from 'react';
import type { Place, Prop } from '../../types';
import { placeToWorld } from './worldSpace';
import { toonMaterial } from './toon';
import { Model } from './assets/Model';
import { ModelBoundary } from './ModelBoundary';
import { propModel } from './assets/propModels';

interface PlacedPropsProps {
  places: Place[];
  props: Prop[] | undefined;
}

/** Warm fallback tints (golden-hour family) for the procedural marker. */
const FALLBACK_STONE = '#a8a095';
const FALLBACK_TOP = '#c9b58a';

/**
 * The procedural stand-in for a prop with no GLB (unknown kind) or while its
 * GLB streams / if it fails: a tiny low-poly cairn — a stone base capped by a
 * warm nub. Small footprint (≈0.5u) so it reads as "a little something here",
 * never an empty patch and never a building-sized block.
 */
function ProceduralProp() {
  return (
    <group>
      <mesh position={[0, 0.12, 0]} castShadow receiveShadow material={toonMaterial(FALLBACK_STONE)}>
        <cylinderGeometry args={[0.22, 0.28, 0.24, 8]} />
      </mesh>
      <mesh position={[0, 0.34, 0]} castShadow material={toonMaterial(FALLBACK_TOP)}>
        <sphereGeometry args={[0.16, 10, 10]} />
      </mesh>
    </group>
  );
}

/** One prop: GLB via <Model> with a procedural fallback (never a hole). */
function PlacedProp({ prop, x, z }: { prop: Prop; x: number; z: number }) {
  // EM-216b: prop.id drives the variety-pool pick (deterministic, replay-safe).
  const spec = useMemo(() => propModel(prop.kind, prop.id), [prop.kind, prop.id]);
  return (
    <group position={[x, 0, z]}>
      {spec ? (
        <ModelBoundary fallback={<ProceduralProp />}>
          <Model spec={spec} />
        </ModelBoundary>
      ) : (
        <ProceduralProp />
      )}
    </group>
  );
}

export function PlacedProps({ places, props }: PlacedPropsProps) {
  const placeCenters = useMemo(() => {
    const m = new Map<string, { x: number; z: number }>();
    for (const p of places) m.set(p.id, placeToWorld(p));
    return m;
  }, [places]);

  // Pure projection: prop → world point (place center + serialized offset).
  // A prop whose place no longer exists is skipped (no free-floating render).
  const placed = useMemo(() => {
    const out: Array<{ prop: Prop; x: number; z: number }> = [];
    for (const prop of props ?? []) {
      const center = placeCenters.get(prop.place);
      if (!center) continue;
      out.push({ prop, x: center.x + (prop.dx ?? 0), z: center.z + (prop.dz ?? 0) });
    }
    return out;
  }, [props, placeCenters]);

  if (placed.length === 0) return null;

  return (
    <group>
      {placed.map(({ prop, x, z }) => (
        <PlacedProp key={prop.id} prop={prop} x={x} z={z} />
      ))}
    </group>
  );
}
