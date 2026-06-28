/**
 * Building — a cute, rounded low-poly structure for one place, distinct per
 * kind, with a floating name label billboarded above it.
 *
 * Wave D1.6 legibility: the 15 places ARE the city's landmarks — the user
 * navigates by their names — so the landmark label is ALWAYS on, scaled up
 * with camera distance (so it stays readable at the default ~89u city
 * framing) and gently distance-faded toward the zoom-out limit. The tight
 * EM-102 proximity gate remains the law for AGENT-BUILT building labels
 * (Structure.tsx) and generated fill is never labeled (CityScape).
 * EM-095: clicking the building zooms the orbit target to it.
 *
 * EM-150: place anchors with a PLACE_MODELS registry entry (work/governance/
 * home) render the real GLB inside <Suspense> whose fallback is the procedural
 * structure below — while the GLB streams (or for null entries: social/wild),
 * the procedural anchor stands; the scene never shows a hole (Wave C rule 7).
 *
 * All fallback geometry is procedural (drei <RoundedBox>, cones, cylinders).
 * Warm WebGL colors (not bound by the CSS token system).
 *
 * EM-111: lit surfaces use the shared cached warm-toon materials (toon.ts) for
 * the banded golden-hour cel look; meshBasicMaterial labels/markers stay as-is.
 */

import { useRef, useState } from 'react';
import { Billboard, RoundedBox, Text, useCursor } from '@react-three/drei';
import { useFrame, type ThreeEvent } from '@react-three/fiber';
import type { Group, MeshBasicMaterial } from 'three';
import type { Place } from '../../types';
import { PLACE_STYLES, placeToWorld } from './worldSpace';
import { toonMaterial } from './toon';
import { Model } from './assets/Model';
import { ModelBoundary } from './ModelBoundary';
import { placeModelRotationY, resolvePlaceModel } from './structureModel';

interface BuildingProps {
  place: Place;
  /** EM-095/102: the current focus id (a place or building id), or null. */
  focusedId?: string | null;
  /** EM-095: clicked → zoom-to-place. */
  onPick?: (placeId: string) => void;
}

// ── Landmark label tuning (Wave D1.6 — see landmarkLabelTransform) ───────────

/** Camera distance at which the label renders at its natural (1×) scale. */
export const LANDMARK_LABEL_REF_DIST = 34;
/** Scale ceiling — at the default ~89u framing the label hits this cap,
 *  ≈ 15px of text on a typical canvas; bigger would collide with neighbors
 *  one 13u block over. */
export const LANDMARK_LABEL_MAX_SCALE = 2.6;
/** Fade window: full ink through the default framing, thinning toward the
 *  130u zoom-out limit so a pulled-back city reads calm, never billboard-y. */
export const LANDMARK_FADE_START = 95;
export const LANDMARK_FADE_END = 165;
export const LANDMARK_MIN_OPACITY = 0.45;

/**
 * Pure scale/fade law for a landmark label at camera distance `d` — kept
 * separate from the component so the tuning is unit-testable.
 */
export function landmarkLabelTransform(d: number): { scale: number; fade: number } {
  const scale = Math.min(
    LANDMARK_LABEL_MAX_SCALE,
    Math.max(1, d / LANDMARK_LABEL_REF_DIST),
  );
  const fade = Math.min(
    1,
    Math.max(
      LANDMARK_MIN_OPACITY,
      1 - (d - LANDMARK_FADE_START) / (LANDMARK_FADE_END - LANDMARK_FADE_START),
    ),
  );
  return { scale, fade };
}

/**
 * The always-on landmark name label (Wave D1.6): billboarded above the place,
 * scaled with camera distance so it stays readable at the default city
 * framing, distance-faded toward the zoom-out limit. Per-frame work is two
 * cheap imperative mutations (group scale + material opacity) — no setState.
 */
function LandmarkLabel({
  text,
  x,
  y,
  z,
  color,
}: {
  text: string;
  /** World position of the label (the parent group sits at (x, 0, z)). */
  x: number;
  y: number;
  z: number;
  color: string;
}) {
  const scaleRef = useRef<Group>(null);
  const plateRef = useRef<MeshBasicMaterial>(null);
  // drei's <Text> ref is the troika mesh; fillOpacity is applied per-render
  // without a glyph re-sync (troika uniform-only property).
  const textRef = useRef<{ fillOpacity: number } | null>(null);

  useFrame(({ camera }) => {
    const d = Math.hypot(
      camera.position.x - x,
      camera.position.y - y,
      camera.position.z - z,
    );
    const { scale, fade } = landmarkLabelTransform(d);
    if (scaleRef.current) scaleRef.current.scale.setScalar(scale);
    if (plateRef.current) plateRef.current.opacity = 0.72 * fade;
    if (textRef.current) textRef.current.fillOpacity = fade;
  });

  return (
    <Billboard position={[0, y, 0]}>
      <group ref={scaleRef}>
        {/* soft backing plate */}
        <mesh position={[0, 0, -0.02]}>
          <planeGeometry args={[Math.max(2.4, text.length * 0.34), 0.85]} />
          <meshBasicMaterial ref={plateRef} color="#3a2f25" transparent opacity={0.72} />
        </mesh>
        <Text
          ref={textRef as never}
          fontSize={0.5}
          color={color}
          anchorX="center"
          anchorY="middle"
          outlineWidth={0.015}
          outlineColor="#241b14"
          maxWidth={10}
        >
          {text}
        </Text>
      </group>
    </Billboard>
  );
}

/** EM-102: the minimal far-away marker — a small floating accent diamond. */
export function MiniMarker({ y, color }: { y: number; color: string }) {
  return (
    <mesh position={[0, y, 0]}>
      <octahedronGeometry args={[0.22]} />
      <meshBasicMaterial color={color} transparent opacity={0.85} />
    </mesh>
  );
}

/** social — open plaza with a little fountain + lanterns. */
function PlazaStructure({ accent }: { accent: string }) {
  return (
    <group>
      {/* paved round base */}
      <mesh position={[0, 0.05, 0]} receiveShadow material={toonMaterial('#d9c7a0')}>
        <cylinderGeometry args={[2.6, 2.6, 0.1, 24]} />
      </mesh>
      {/* fountain basin */}
      <mesh position={[0, 0.3, 0]} castShadow receiveShadow material={toonMaterial('#bfc8d4')}>
        <cylinderGeometry args={[1.0, 1.1, 0.5, 20]} />
      </mesh>
      {/* water — a soft self-glow keeps it reading bright at golden hour */}
      <mesh
        position={[0, 0.55, 0]}
        material={toonMaterial('#6fc5d6', { emissive: '#2e8fa3', emissiveIntensity: 0.2 })}
      >
        <cylinderGeometry args={[0.85, 0.85, 0.08, 20]} />
      </mesh>
      {/* center spout */}
      <mesh position={[0, 0.9, 0]} castShadow material={toonMaterial('#bfc8d4')}>
        <cylinderGeometry args={[0.12, 0.16, 0.7, 12]} />
      </mesh>
      <mesh position={[0, 1.3, 0]} castShadow material={toonMaterial(accent)}>
        <sphereGeometry args={[0.22, 16, 16]} />
      </mesh>
      {/* a couple of cozy lanterns on posts */}
      {[
        [1.9, 1.9],
        [-1.9, -1.9],
        [1.9, -1.9],
        [-1.9, 1.9],
      ].map(([lx, lz], i) => (
        <group key={i} position={[lx, 0, lz]}>
          <mesh position={[0, 0.6, 0]} castShadow material={toonMaterial('#6b4f32')}>
            <cylinderGeometry args={[0.06, 0.06, 1.2, 8]} />
          </mesh>
          {/* lantern globe — emissive glow preserved */}
          <mesh
            position={[0, 1.3, 0]}
            castShadow
            material={toonMaterial('#ffd27f', { emissive: '#ffb347', emissiveIntensity: 0.8 })}
          >
            <sphereGeometry args={[0.18, 12, 12]} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

/** work — market stall with a striped awning. */
function MarketStructure({ body, accent }: { body: string; accent: string }) {
  return (
    <group>
      {/* counter */}
      <RoundedBox
        args={[3.2, 1.0, 1.6]}
        radius={0.12}
        smoothness={3}
        position={[0, 0.5, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(body)}
      />
      {/* posts */}
      {[-1.4, 1.4].map((px) => (
        <mesh key={px} position={[px, 1.4, -0.6]} castShadow material={toonMaterial('#7a5a38')}>
          <cylinderGeometry args={[0.08, 0.08, 1.8, 8]} />
        </mesh>
      ))}
      {/* striped awning (slightly tilted box, stripes faked with two slabs) */}
      <group position={[0, 2.2, 0.2]} rotation={[-0.35, 0, 0]}>
        <mesh castShadow material={toonMaterial(accent)}>
          <boxGeometry args={[3.6, 0.08, 1.8]} />
        </mesh>
        {[-1.2, 0, 1.2].map((sx) => (
          <mesh key={sx} position={[sx, 0.05, 0]} material={toonMaterial('#fff3e0')}>
            <boxGeometry args={[0.6, 0.04, 1.85]} />
          </mesh>
        ))}
      </group>
      {/* a little crate of goods */}
      <RoundedBox
        args={[0.7, 0.6, 0.7]}
        radius={0.06}
        smoothness={2}
        position={[1.0, 1.3, 0.2]}
        castShadow
        material={toonMaterial('#c98b3a')}
      />
    </group>
  );
}

/** governance — larger town hall with a spire/clock. */
function TownHallStructure({ body, accent }: { body: string; accent: string }) {
  return (
    <group>
      {/* main hall */}
      <RoundedBox
        args={[3.6, 2.6, 3.0]}
        radius={0.18}
        smoothness={3}
        position={[0, 1.3, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(body)}
      />
      {/* pitched roof */}
      <mesh position={[0, 3.1, 0]} rotation={[0, Math.PI / 4, 0]} castShadow material={toonMaterial(accent)}>
        <coneGeometry args={[2.9, 1.3, 4]} />
      </mesh>
      {/* spire / clock tower */}
      <mesh position={[0, 3.9, 0]} castShadow material={toonMaterial(body)}>
        <cylinderGeometry args={[0.55, 0.6, 1.4, 12]} />
      </mesh>
      {/* clock face */}
      <mesh position={[0, 4.1, 0.62]} material={toonMaterial('#fff8e7')}>
        <circleGeometry args={[0.3, 20]} />
      </mesh>
      {/* spire cap */}
      <mesh position={[0, 5.0, 0]} castShadow material={toonMaterial(accent)}>
        <coneGeometry args={[0.6, 1.0, 12]} />
      </mesh>
      {/* door */}
      <mesh position={[0, 0.8, 1.52]} material={toonMaterial('#7a5a38')}>
        <planeGeometry args={[0.8, 1.5]} />
      </mesh>
    </group>
  );
}

/** home — cozy cottage: pitched roof + chimney. */
function CottageStructure({ body, accent }: { body: string; accent: string }) {
  return (
    <group>
      {/* walls */}
      <RoundedBox
        args={[2.6, 1.8, 2.4]}
        radius={0.16}
        smoothness={3}
        position={[0, 0.9, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(body)}
      />
      {/* pitched roof */}
      <mesh position={[0, 2.3, 0]} rotation={[0, Math.PI / 4, 0]} castShadow material={toonMaterial(accent)}>
        <coneGeometry args={[2.2, 1.3, 4]} />
      </mesh>
      {/* chimney */}
      <mesh position={[0.8, 2.7, 0.5]} castShadow material={toonMaterial('#b56a4a')}>
        <boxGeometry args={[0.4, 1.0, 0.4]} />
      </mesh>
      {/* door */}
      <mesh position={[0, 0.6, 1.22]} material={toonMaterial('#7a5a38')}>
        <planeGeometry args={[0.6, 1.1]} />
      </mesh>
      {/* glowing window — emissive glow preserved */}
      <mesh
        position={[0.7, 1.1, 1.22]}
        material={toonMaterial('#ffe0a3', { emissive: '#ffcf7a', emissiveIntensity: 0.6 })}
      >
        <planeGeometry args={[0.5, 0.5]} />
      </mesh>
    </group>
  );
}

/** wild — cluster of trees & bushes (foraging patch). */
function CommonsStructure() {
  const trees: Array<[number, number]> = [
    [-1.4, -0.8],
    [1.3, 0.6],
    [0.2, -1.4],
  ];
  return (
    <group>
      {trees.map(([tx, tz], i) => {
        const h = 1.4 + (i % 2) * 0.5;
        return (
          <group key={i} position={[tx, 0, tz]}>
            <mesh position={[0, h / 2, 0]} castShadow material={toonMaterial('#7a5230')}>
              <cylinderGeometry args={[0.18, 0.24, h, 8]} />
            </mesh>
            <mesh position={[0, h + 0.5, 0]} castShadow material={toonMaterial('#5fa05f')}>
              <sphereGeometry args={[0.95, 14, 14]} />
            </mesh>
            <mesh position={[0.3, h + 1.0, 0.2]} castShadow material={toonMaterial('#6fb56f')}>
              <sphereGeometry args={[0.55, 12, 12]} />
            </mesh>
          </group>
        );
      })}
      {/* berry bushes */}
      {[
        [-0.4, 0.6],
        [1.0, -0.9],
      ].map(([bx, bz], i) => (
        <mesh key={i} position={[bx, 0.4, bz]} castShadow receiveShadow material={toonMaterial('#4f8f4f')}>
          <sphereGeometry args={[0.5, 12, 12]} />
        </mesh>
      ))}
    </group>
  );
}

export function Building({ place, onPick }: BuildingProps) {
  const { x, z } = placeToWorld(place);
  const style = PLACE_STYLES[place.kind];
  const [hovered, setHovered] = useState(false);
  useCursor(hovered && Boolean(onPick));

  // EM-150: the place-anchor GLB, or null = stay procedural (social/wild).
  // EM-248: thread place.id so the anchor draws from its PLACE_POOLS variety.
  const spec = resolvePlaceModel(place.kind, place.id);

  // label height tuned per structure footprint (GLB anchors measure shorter
  // than the procedural town hall but TALLER than the market/cottage: the
  // lumbermill tops out at ~3.4, home_b at ~2.9 — lift their labels clear).
  const baseLabelY =
    place.kind === 'governance'
      ? 6.2
      : place.kind === 'social'
        ? 2.6
        : spec
          ? place.kind === 'work'
            ? 4.5
            : 3.9
          : 3.4;

  // Wave D1.6: stagger label heights by block parity so the scaled-up labels
  // of ADJACENT landmark blocks (13u apart, plates up to ~16u wide at max
  // scale) never sit on the same horizon line.
  const blockParity =
    ((Math.round(x / 13) + Math.round(z / 13)) % 2 + 2) % 2;
  const labelY = baseLabelY + blockParity * 1.6;

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (!onPick) return;
    e.stopPropagation();
    onPick(place.id);
  };

  // The procedural anchor: the render when spec is null AND the Suspense
  // fallback while a GLB streams (Wave C fallback invariant — never a hole).
  const procedural = (
    <>
      {place.kind === 'social' && <PlazaStructure accent={style.accent} />}
      {place.kind === 'work' && (
        <MarketStructure body={style.body} accent={style.accent} />
      )}
      {place.kind === 'governance' && (
        <TownHallStructure body={style.body} accent={style.accent} />
      )}
      {place.kind === 'home' && (
        <CottageStructure body={style.body} accent={style.accent} />
      )}
      {place.kind === 'wild' && <CommonsStructure />}
    </>
  );

  return (
    <group
      position={[x, 0, z]}
      onClick={handleClick}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}
    >
      {spec ? (
        // ModelBoundary = Suspense + error boundary: the procedural anchor
        // stands while the GLB streams AND if it fails to load.
        <ModelBoundary fallback={procedural}>
          <Model spec={spec} rotation-y={placeModelRotationY(place.kind)} />
        </ModelBoundary>
      ) : (
        procedural
      )}

      {/* Wave D1.6: the landmark name is ALWAYS on — the user navigates by
          it. Distance-scaled + faded; agent-built Structure labels keep the
          tight EM-102 gate, generated fill is never labeled. */}
      <LandmarkLabel text={place.name} x={x} y={labelY} z={z} color="#fff3e0" />
    </group>
  );
}
