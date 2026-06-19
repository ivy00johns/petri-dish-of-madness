/**
 * PlazaBanner (Wave I / EM-213, I4) — the civic artwork the town VOTED to hang
 * over its plaza. A standalone textured plane: a `planeGeometry` +
 * `meshToonMaterial { map: useTexture(url) }`, raised on two posts over the
 * plaza anchor (reusing buildingSpot/placeToWorld so it sits beside, not on,
 * the fountain).
 *
 * It reads `world.plaza_banner_ref` → the promoted image's id → that gallery
 * entry's RELATIVE `url` (`/assets/images/<id>.png`, straight from the payload —
 * no host hardcoded). When the ref is unset (the common pre-vote case) OR the
 * referenced image isn't in the gallery, it shows a PROCEDURAL "civic canvas"
 * fallback — a blank toon-tinted banner with a carved label — so the plaza
 * always has a banner frame, never a hole. A 404 on the texture ALSO falls back
 * (ModelBoundary: Suspense while streaming, error boundary on failure), so the
 * banner is never a blank/erroring mesh (EM-148 invariant).
 *
 * Colors are WebGL material colors (THREE.Color), explicitly OUTSIDE the CSS
 * design-token system — the same GPU-palette convention as NoticeBoard/
 * Building/Structure (the 3D scene owns its warm palette; design-token-guard
 * governs DOM/CSS only). Centralized inks are reused from toon.ts (LABEL_INK/
 * LABEL_OUTLINE).
 */

import { Billboard, Text, useTexture } from '@react-three/drei';
import { ModelBoundary } from './ModelBoundary';
import { toonMaterial, LABEL_INK, LABEL_OUTLINE } from './toon';
import { BUILDING_STYLES } from './worldSpace';

interface PlazaBannerProps {
  /** World position of the banner (a satellite spot near the plaza center). */
  x: number;
  z: number;
  /**
   * The promoted image's RELATIVE url, or null/undefined when no image is
   * promoted (pre-vote) — then the procedural civic-canvas fallback renders.
   */
  url?: string | null;
}

// GPU palette — REUSED from the centralized BUILDING_STYLES village palette
// (WebGL material colors, outside the CSS token system per the established
// village convention; see the module header) so the banner frame reads in the
// same warm family as the structures around it, no new sprinkled hex:
//   • POST        — library roof (warm wood) for the support posts;
//   • CANVAS_BLANK — the neutral `building` body (warm cream) for the blank canvas;
//   • FRAME       — library accent (timber) for the top frame bar.
const POST = BUILDING_STYLES.library.roof;
const CANVAS_BLANK = BUILDING_STYLES.building.body;
const FRAME = BUILDING_STYLES.library.accent;

// Banner geometry — wide landscape canvas raised on two posts over the plaza.
const BANNER_SIZE: [number, number] = [3.2, 1.9];
const BANNER_Y = 3.0;
const POST_HALF_SPAN = 1.7;

/** The promoted artwork, textured onto the banner canvas (suspends / may 404). */
function TexturedBanner({ url }: { url: string }) {
  const map = useTexture(url);
  return (
    <mesh position={[0, BANNER_Y, 0]}>
      <planeGeometry args={BANNER_SIZE} />
      <meshToonMaterial map={map} />
    </mesh>
  );
}

/**
 * The procedural civic-canvas fallback: a blank toon banner + a carved label,
 * shown when no image is promoted (or while one streams / if it 404s). Keeps a
 * banner frame over the plaza so the spot always reads as "civic art goes here".
 */
function ProceduralBanner() {
  return (
    <>
      <mesh position={[0, BANNER_Y, 0]} material={toonMaterial(CANVAS_BLANK)}>
        <planeGeometry args={BANNER_SIZE} />
      </mesh>
      <Billboard position={[0, BANNER_Y, 0.02]}>
        <Text
          fontSize={0.32}
          color={LABEL_INK}
          anchorX="center"
          anchorY="middle"
          outlineWidth={0.01}
          outlineColor={LABEL_OUTLINE}
          maxWidth={3}
        >
          🖼 PLAZA BANNER
        </Text>
      </Billboard>
    </>
  );
}

export function PlazaBanner({ x, z, url }: PlazaBannerProps) {
  return (
    <group position={[x, 0, z]}>
      {/* two support posts framing the banner */}
      {[-POST_HALF_SPAN, POST_HALF_SPAN].map((px) => (
        <mesh key={px} position={[px, BANNER_Y - 0.7, 0]} castShadow material={toonMaterial(POST)}>
          <cylinderGeometry args={[0.09, 0.11, 2.4, 8]} />
        </mesh>
      ))}
      {/* a slim frame bar across the top of the canvas */}
      <mesh position={[0, BANNER_Y + BANNER_SIZE[1] / 2 + 0.06, 0]} castShadow material={toonMaterial(FRAME)}>
        <boxGeometry args={[BANNER_SIZE[0] + 0.3, 0.12, 0.16]} />
      </mesh>

      {/* the canvas itself — promoted artwork when set, else the civic fallback;
          a 404 / in-flight load also shows the fallback (EM-148). */}
      {url ? (
        // key={url}: the boundary latches `failed` forever once a texture 404s
        // (no internal reset). Keying it to the url remounts a FRESH boundary
        // when the promoted image changes/retries, so one transient 404 doesn't
        // permanently pin the procedural canvas for the rest of the session
        // (matches the CityScape keyed-remount idiom).
        <ModelBoundary key={url} fallback={<ProceduralBanner />}>
          <TexturedBanner url={url} />
        </ModelBoundary>
      ) : (
        <ProceduralBanner />
      )}
    </group>
  );
}
