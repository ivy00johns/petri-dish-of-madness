/**
 * Building — a cute, rounded low-poly structure for one place, distinct per
 * kind, with a floating name label billboarded above it.
 *
 * EM-102 declutter: the full name label only renders while the camera is near
 * (useProximity), the building is hovered, or it's the camera-focus target
 * (EM-095 zoom-to-place reveals the focused building's full label). Otherwise
 * a minimal accent marker keeps the place locatable without burying villager
 * chips. EM-095: clicking the building zooms the orbit target to it.
 *
 * All geometry is procedural (drei <RoundedBox>, cones, cylinders) — no
 * external assets. Warm WebGL colors (not bound by the CSS token system).
 *
 * EM-111: lit surfaces use the shared cached warm-toon materials (toon.ts) for
 * the banded golden-hour cel look; meshBasicMaterial labels/markers stay as-is.
 */

import { useCallback, useState } from 'react';
import { Billboard, RoundedBox, Text, useCursor } from '@react-three/drei';
import type { ThreeEvent } from '@react-three/fiber';
import type { Place } from '../../types';
import { PLACE_STYLES, placeToWorld } from './worldSpace';
import { toonMaterial } from './toon';
import { useProximity, PLACE_LABEL_DIST } from './useProximity';

interface BuildingProps {
  place: Place;
  /** EM-095/102: the current focus id (a place or building id), or null. */
  focusedId?: string | null;
  /** EM-095: clicked → zoom-to-place. */
  onPick?: (placeId: string) => void;
}

/** Floating name label above a structure. */
function NameLabel({ text, y, color }: { text: string; y: number; color: string }) {
  return (
    <Billboard position={[0, y, 0]}>
      {/* soft backing plate */}
      <mesh position={[0, 0, -0.02]}>
        <planeGeometry args={[Math.max(2.4, text.length * 0.34), 0.85]} />
        <meshBasicMaterial color="#3a2f25" transparent opacity={0.72} />
      </mesh>
      <Text
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

export function Building({ place, focusedId, onPick }: BuildingProps) {
  const { x, z } = placeToWorld(place);
  const style = PLACE_STYLES[place.kind];
  const [hovered, setHovered] = useState(false);
  useCursor(hovered && Boolean(onPick));

  // EM-102: full label only when near / hovered / the camera-focus target.
  const near = useProximity(useCallback(() => ({ x, z }), [x, z]), PLACE_LABEL_DIST);
  const showFull = near || hovered || focusedId === place.id;

  // label height tuned per structure footprint
  const labelY =
    place.kind === 'governance' ? 6.2 : place.kind === 'social' ? 2.6 : 3.4;

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (!onPick) return;
    e.stopPropagation();
    onPick(place.id);
  };

  return (
    <group
      position={[x, 0, z]}
      onClick={handleClick}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}
    >
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

      {showFull ? (
        <NameLabel text={place.name} y={labelY} color="#fff3e0" />
      ) : (
        <MiniMarker y={labelY} color={style.accent} />
      )}
    </group>
  );
}
