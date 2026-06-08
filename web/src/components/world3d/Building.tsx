/**
 * Building — a cute, rounded low-poly structure for one place, distinct per
 * kind, with a floating name label billboarded above it.
 *
 * All geometry is procedural (drei <RoundedBox>, cones, cylinders) — no
 * external assets. Warm WebGL colors (not bound by the CSS token system).
 */

import { Billboard, RoundedBox, Text } from '@react-three/drei';
import type { Place } from '../../types';
import { PLACE_STYLES, placeToWorld } from './worldSpace';

interface BuildingProps {
  place: Place;
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

/** social — open plaza with a little fountain + lanterns. */
function PlazaStructure({ accent }: { accent: string }) {
  return (
    <group>
      {/* paved round base */}
      <mesh position={[0, 0.05, 0]} receiveShadow>
        <cylinderGeometry args={[2.6, 2.6, 0.1, 24]} />
        <meshStandardMaterial color="#d9c7a0" roughness={1} />
      </mesh>
      {/* fountain basin */}
      <mesh position={[0, 0.3, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[1.0, 1.1, 0.5, 20]} />
        <meshStandardMaterial color="#bfc8d4" roughness={0.6} />
      </mesh>
      {/* water */}
      <mesh position={[0, 0.55, 0]}>
        <cylinderGeometry args={[0.85, 0.85, 0.08, 20]} />
        <meshStandardMaterial color="#6fc5d6" roughness={0.2} metalness={0.1} />
      </mesh>
      {/* center spout */}
      <mesh position={[0, 0.9, 0]} castShadow>
        <cylinderGeometry args={[0.12, 0.16, 0.7, 12]} />
        <meshStandardMaterial color="#bfc8d4" roughness={0.6} />
      </mesh>
      <mesh position={[0, 1.3, 0]} castShadow>
        <sphereGeometry args={[0.22, 16, 16]} />
        <meshStandardMaterial color={accent} roughness={0.5} />
      </mesh>
      {/* a couple of cozy lanterns on posts */}
      {[
        [1.9, 1.9],
        [-1.9, -1.9],
        [1.9, -1.9],
        [-1.9, 1.9],
      ].map(([lx, lz], i) => (
        <group key={i} position={[lx, 0, lz]}>
          <mesh position={[0, 0.6, 0]} castShadow>
            <cylinderGeometry args={[0.06, 0.06, 1.2, 8]} />
            <meshStandardMaterial color="#6b4f32" roughness={1} />
          </mesh>
          <mesh position={[0, 1.3, 0]} castShadow>
            <sphereGeometry args={[0.18, 12, 12]} />
            <meshStandardMaterial
              color="#ffd27f"
              emissive="#ffb347"
              emissiveIntensity={0.8}
              roughness={0.4}
            />
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
      >
        <meshStandardMaterial color={body} roughness={0.9} />
      </RoundedBox>
      {/* posts */}
      {[-1.4, 1.4].map((px) => (
        <mesh key={px} position={[px, 1.4, -0.6]} castShadow>
          <cylinderGeometry args={[0.08, 0.08, 1.8, 8]} />
          <meshStandardMaterial color="#7a5a38" roughness={1} />
        </mesh>
      ))}
      {/* striped awning (slightly tilted box, stripes faked with two slabs) */}
      <group position={[0, 2.2, 0.2]} rotation={[-0.35, 0, 0]}>
        <mesh castShadow>
          <boxGeometry args={[3.6, 0.08, 1.8]} />
          <meshStandardMaterial color={accent} roughness={0.8} />
        </mesh>
        {[-1.2, 0, 1.2].map((sx) => (
          <mesh key={sx} position={[sx, 0.05, 0]}>
            <boxGeometry args={[0.6, 0.04, 1.85]} />
            <meshStandardMaterial color="#fff3e0" roughness={0.8} />
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
      >
        <meshStandardMaterial color="#c98b3a" roughness={1} />
      </RoundedBox>
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
      >
        <meshStandardMaterial color={body} roughness={0.9} />
      </RoundedBox>
      {/* pitched roof */}
      <mesh position={[0, 3.1, 0]} rotation={[0, Math.PI / 4, 0]} castShadow>
        <coneGeometry args={[2.9, 1.3, 4]} />
        <meshStandardMaterial color={accent} roughness={0.8} />
      </mesh>
      {/* spire / clock tower */}
      <mesh position={[0, 3.9, 0]} castShadow>
        <cylinderGeometry args={[0.55, 0.6, 1.4, 12]} />
        <meshStandardMaterial color={body} roughness={0.9} />
      </mesh>
      {/* clock face */}
      <mesh position={[0, 4.1, 0.62]}>
        <circleGeometry args={[0.3, 20]} />
        <meshStandardMaterial color="#fff8e7" roughness={0.5} />
      </mesh>
      {/* spire cap */}
      <mesh position={[0, 5.0, 0]} castShadow>
        <coneGeometry args={[0.6, 1.0, 12]} />
        <meshStandardMaterial color={accent} roughness={0.8} />
      </mesh>
      {/* door */}
      <mesh position={[0, 0.8, 1.52]}>
        <planeGeometry args={[0.8, 1.5]} />
        <meshStandardMaterial color="#7a5a38" roughness={1} />
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
      >
        <meshStandardMaterial color={body} roughness={0.95} />
      </RoundedBox>
      {/* pitched roof */}
      <mesh position={[0, 2.3, 0]} rotation={[0, Math.PI / 4, 0]} castShadow>
        <coneGeometry args={[2.2, 1.3, 4]} />
        <meshStandardMaterial color={accent} roughness={0.85} />
      </mesh>
      {/* chimney */}
      <mesh position={[0.8, 2.7, 0.5]} castShadow>
        <boxGeometry args={[0.4, 1.0, 0.4]} />
        <meshStandardMaterial color="#b56a4a" roughness={1} />
      </mesh>
      {/* door */}
      <mesh position={[0, 0.6, 1.22]}>
        <planeGeometry args={[0.6, 1.1]} />
        <meshStandardMaterial color="#7a5a38" roughness={1} />
      </mesh>
      {/* glowing window */}
      <mesh position={[0.7, 1.1, 1.22]}>
        <planeGeometry args={[0.5, 0.5]} />
        <meshStandardMaterial
          color="#ffe0a3"
          emissive="#ffcf7a"
          emissiveIntensity={0.6}
          roughness={0.5}
        />
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
            <mesh position={[0, h / 2, 0]} castShadow>
              <cylinderGeometry args={[0.18, 0.24, h, 8]} />
              <meshStandardMaterial color="#7a5230" roughness={1} />
            </mesh>
            <mesh position={[0, h + 0.5, 0]} castShadow>
              <sphereGeometry args={[0.95, 14, 14]} />
              <meshStandardMaterial color="#5fa05f" roughness={1} />
            </mesh>
            <mesh position={[0.3, h + 1.0, 0.2]} castShadow>
              <sphereGeometry args={[0.55, 12, 12]} />
              <meshStandardMaterial color="#6fb56f" roughness={1} />
            </mesh>
          </group>
        );
      })}
      {/* berry bushes */}
      {[
        [-0.4, 0.6],
        [1.0, -0.9],
      ].map(([bx, bz], i) => (
        <mesh key={i} position={[bx, 0.4, bz]} castShadow receiveShadow>
          <sphereGeometry args={[0.5, 12, 12]} />
          <meshStandardMaterial color="#4f8f4f" roughness={1} />
        </mesh>
      ))}
    </group>
  );
}

export function Building({ place }: BuildingProps) {
  const { x, z } = placeToWorld(place);
  const style = PLACE_STYLES[place.kind];

  // label height tuned per structure footprint
  const labelY =
    place.kind === 'governance' ? 6.2 : place.kind === 'social' ? 2.6 : 3.4;

  return (
    <group position={[x, 0, z]}>
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

      <NameLabel text={place.name} y={labelY} color="#fff3e0" />
    </group>
  );
}
