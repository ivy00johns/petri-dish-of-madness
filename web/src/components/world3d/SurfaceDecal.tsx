/**
 * SurfaceDecal (EM-298) — an agent-authored facade decal: the mural / sign /
 * graffiti an agent painted onto a building (action_paint_surface). It is the
 * building-facade sibling of PlazaBanner's TexturedBanner: a flat `planeGeometry`
 * + `meshToonMaterial { map: useTexture(url) }`, offset just in front of the
 * structure's front (+z) face, wrapped in ModelBoundary.
 *
 * It reads `world.surface_decals[building_id]` → the gallery image id → that
 * entry's RELATIVE `url` (`/assets/images/<id>.png`, straight from the payload —
 * no host hardcoded). CozyWorld resolves the id→url and renders one SurfaceDecal
 * per building that has a decal, at the building's own lot spot.
 *
 * EM-302b: the plane no longer sits at a FIXED z=1.06 (which buried it inside
 * deep GLBs like the theater, z-fought shallow ones, and floated in front of
 * the dock) — decalLayout.decalPlacement resolves the SAME GLB the Structure
 * renderer picked (kind+id) and places the plane at that model's MEASURED
 * front face + a surface-normal epsilon, centered on the measured facade
 * x (x-offset GLBs like the dock hull would otherwise hang the mural half
 * off the wall), shrinking/lowering the canvas on short models so the mural
 * stays on the facade instead of hovering over it.
 *
 * UNLIKE PlazaBanner there is NO procedural fallback: a facade with no decal
 * simply renders nothing (CozyWorld skips it), and a decal that is still
 * streaming OR 404s falls back to `null` (an invisible plane) so the facade stays
 * clean — never a placeholder box or an erroring mesh (EM-148 invariant, via
 * ModelBoundary: Suspense while streaming, error boundary on failure).
 *
 * Colors are WebGL material colors — the same GPU-palette convention as
 * PlazaBanner/Structure (the 3D scene owns its palette; design-token-guard
 * governs DOM/CSS only). This component sets none; the texture map IS the color.
 */

import { useMemo } from 'react';
import { useTexture } from '@react-three/drei';
import type { Building } from '../../types';
import { ModelBoundary } from './ModelBoundary';
import { DECAL_SIZE, decalPlacement, type DecalPlacement } from './decalLayout';

interface SurfaceDecalProps {
  /** World position of the building the decal is painted on (its lot spot). */
  x: number;
  z: number;
  /** The painted image's RELATIVE url (`/assets/images/<id>.png`). */
  url: string;
  /** The painted building — drives the measured facade placement (EM-302b). */
  building: Pick<Building, 'id' | 'kind' | 'status'>;
}

/** The painted artwork, textured onto the facade plane (suspends / may 404). */
function TexturedDecal({ url, placement }: { url: string; placement: DecalPlacement }) {
  const map = useTexture(url);
  return (
    <mesh
      position={[placement.x, placement.y, placement.z]}
      scale={[placement.scale, placement.scale, 1]}
    >
      <planeGeometry args={DECAL_SIZE} />
      <meshToonMaterial map={map} />
    </mesh>
  );
}

export function SurfaceDecal({ x, z, url, building }: SurfaceDecalProps) {
  const placement = useMemo(
    () => decalPlacement(building),
    [building.id, building.kind, building.status], // eslint-disable-line react-hooks/exhaustive-deps
  );
  return (
    <group position={[x, 0, z]}>
      {/* key={url}: the boundary latches `failed` forever once a texture 404s
          (no internal reset). Keying it to the url remounts a FRESH boundary
          when the decal changes/retries, so one transient 404 doesn't
          permanently blank a facade for the rest of the session (matches the
          PlazaBanner keyed-remount idiom). A null fallback keeps the facade
          clean while streaming / on failure. */}
      <ModelBoundary key={url} fallback={null}>
        <TexturedDecal url={url} placement={placement} />
      </ModelBoundary>
    </group>
  );
}
