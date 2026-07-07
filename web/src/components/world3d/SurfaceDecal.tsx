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

import { useTexture } from '@react-three/drei';
import { ModelBoundary } from './ModelBoundary';

interface SurfaceDecalProps {
  /** World position of the building the decal is painted on (its lot spot). */
  x: number;
  z: number;
  /** The painted image's RELATIVE url (`/assets/images/<id>.png`). */
  url: string;
}

// Decal geometry — a modest canvas on the structure's front (+z) facade. The
// Structure body footprint is ~2.0 wide with its face near z≈1.0; we sit the
// plane just in front (z past the face) at torso height so it reads as painted
// ON the wall without z-fighting the box behind it.
const DECAL_SIZE: [number, number] = [1.5, 1.1];
const DECAL_Y = 1.35;
const DECAL_Z = 1.06;

/** The painted artwork, textured onto the facade plane (suspends / may 404). */
function TexturedDecal({ url }: { url: string }) {
  const map = useTexture(url);
  return (
    <mesh position={[0, DECAL_Y, DECAL_Z]}>
      <planeGeometry args={DECAL_SIZE} />
      <meshToonMaterial map={map} />
    </mesh>
  );
}

export function SurfaceDecal({ x, z, url }: SurfaceDecalProps) {
  return (
    <group position={[x, 0, z]}>
      {/* key={url}: the boundary latches `failed` forever once a texture 404s
          (no internal reset). Keying it to the url remounts a FRESH boundary
          when the decal changes/retries, so one transient 404 doesn't
          permanently blank a facade for the rest of the session (matches the
          PlazaBanner keyed-remount idiom). A null fallback keeps the facade
          clean while streaming / on failure. */}
      <ModelBoundary key={url} fallback={null}>
        <TexturedDecal url={url} />
      </ModelBoundary>
    </group>
  );
}
