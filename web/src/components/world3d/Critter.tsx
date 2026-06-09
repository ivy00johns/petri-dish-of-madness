/**
 * Critter — the W8 Animal renderer: a roaming cat or dog in the cozy village.
 *
 * Animals are a DISTINCT entity type (world-model.md §W8), not human agents:
 * they share the world mechanically but act impulsively. Here they're charming
 * low-poly critters that WANDER near their place on a slow, looping path (not
 * the ring-distributed villager layout — animals roam). Species are visually
 * distinct:
 *   cat → slim body, pointed upright ears, a long curling tail.
 *   dog → chunkier body, floppy droop ears, a short stubby wagging tail.
 *
 * A CHAOTIC animal (one that recently invoked a crime/structure-targeting or
 * other low-prior action — see the chaos heuristic in CozyWorld) gets a subtle
 * MAGENTA accent: a glowing collar + an emissive tint on its ears, the same
 * magenta as the Animal Chaos Feed + the replay timeline markers, so the chaos
 * register agrees across the 3D village and the 2D inspector.
 *
 * All geometry is procedural (drei <RoundedBox>, spheres, cones) — no external
 * assets. Colors are WebGL material colors (THREE.Color), explicitly OUTSIDE the
 * CSS design-token system (same convention as Building/Structure/Villager: the
 * GPU scene owns its warm palette; design-token-guard governs DOM/CSS only).
 */

import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Billboard, Html, RoundedBox } from '@react-three/drei';
import * as THREE from 'three';
import type { Animal } from '../../types';
import {
  animalStyle,
  hashUnit,
  type AnimalStyle,
  ANIMAL_CHAOS_MAGENTA,
} from './worldSpace';

export interface CritterPos {
  x: number;
  z: number;
}

interface CritterProps {
  animal: Animal;
  /** World center of the animal's current place (it wanders around this). */
  center: CritterPos;
  /** Shared mutable animated position (mutated in useFrame, survives re-renders). */
  animRef: CritterPos;
  /** Whether this animal is currently in a chaotic streak (magenta accent). */
  chaotic: boolean;
}

const LABEL_Y = 1.5;
// Radius the critter roams around its place center.
const WANDER_RADIUS = 3.2;

/** The floating info card above a critter: name, species, mood, energy. */
function CritterLabel({ animal, chaotic }: { animal: Animal; chaotic: boolean }) {
  const energy = Math.max(0, Math.min(100, animal.energy));
  const icon = animal.species === 'cat' ? '🐱' : '🐶';
  // Data-driven border: magenta while chaotic, else a soft warm rim. Inline
  // style here is a 3D-overlay (Html drei) card, in the same WebGL-overlay
  // register as VillagerLabel — the GPU scene's own palette, not the DOM theme.
  const border = chaotic ? ANIMAL_CHAOS_MAGENTA : '#caa873';

  return (
    <Billboard position={[0, LABEL_Y, 0]}>
      <Html center distanceFactor={12} zIndexRange={[28, 0]} style={{ pointerEvents: 'none' }}>
        <div
          style={{
            opacity: animal.alive ? 1 : 0.45,
            minWidth: 78,
            padding: '3px 7px 4px',
            borderRadius: 10,
            background: 'rgba(40,32,26,0.86)',
            color: '#f4ecdf',
            fontFamily: '"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif',
            fontSize: 11,
            lineHeight: 1.25,
            textAlign: 'center',
            boxShadow: chaotic
              ? `0 0 10px ${ANIMAL_CHAOS_MAGENTA}88, 0 3px 9px rgba(0,0,0,0.3)`
              : '0 3px 9px rgba(0,0,0,0.3)',
            border: `1px solid ${border}`,
            userSelect: 'none',
          }}
        >
          <div style={{ fontWeight: 700, color: '#fff7ea' }}>
            <span aria-hidden="true">{icon}</span> {animal.name}
            {!animal.alive && <span style={{ opacity: 0.7 }}> (gone)</span>}
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 6, fontSize: 10 }}>
            <span style={{ opacity: 0.85 }}>{animal.mood}</span>
            {chaotic && (
              <span style={{ color: ANIMAL_CHAOS_MAGENTA, fontWeight: 700 }}>chaos</span>
            )}
          </div>
          {/* energy bar */}
          <div
            style={{
              height: 4,
              borderRadius: 3,
              background: 'rgba(255,255,255,0.16)',
              margin: '3px 0 0',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${energy}%`,
                height: '100%',
                borderRadius: 3,
                background: energy > 50 ? '#7ed957' : energy > 20 ? '#ffcf5c' : '#ff6b5c',
                transition: 'width 300ms ease',
              }}
            />
          </div>
        </div>
      </Html>
    </Billboard>
  );
}

// ── Cat body: slim, upright pointed ears, long curling tail ───────────────────

function CatBody({ style, accent }: { style: AnimalStyle; accent: string }) {
  return (
    <group>
      {/* torso */}
      <RoundedBox args={[0.34, 0.3, 0.62]} radius={0.13} smoothness={3} position={[0, 0.34, 0]} castShadow receiveShadow>
        <meshStandardMaterial color={style.body} roughness={0.7} />
      </RoundedBox>
      {/* lighter belly */}
      <RoundedBox args={[0.26, 0.16, 0.5]} radius={0.08} smoothness={3} position={[0, 0.24, 0.02]} castShadow>
        <meshStandardMaterial color={style.belly} roughness={0.75} />
      </RoundedBox>
      {/* head */}
      <mesh position={[0, 0.5, 0.34]} castShadow>
        <sphereGeometry args={[0.2, 16, 16]} />
        <meshStandardMaterial color={style.body} roughness={0.6} />
      </mesh>
      {/* pointed upright ears */}
      {[-0.11, 0.11].map((ex) => (
        <mesh key={ex} position={[ex, 0.66, 0.32]} rotation={[0, 0, ex < 0 ? 0.2 : -0.2]} castShadow>
          <coneGeometry args={[0.07, 0.16, 4]} />
          <meshStandardMaterial color={accent} roughness={0.6} />
        </mesh>
      ))}
      {/* eyes */}
      {[-0.07, 0.07].map((ex) => (
        <mesh key={ex} position={[ex, 0.52, 0.5]}>
          <sphereGeometry args={[0.032, 8, 8]} />
          <meshStandardMaterial color="#241b14" />
        </mesh>
      ))}
      {/* long curling tail */}
      <mesh position={[0, 0.46, -0.4]} rotation={[0.9, 0, 0]} castShadow>
        <cylinderGeometry args={[0.04, 0.05, 0.5, 8]} />
        <meshStandardMaterial color={style.body} roughness={0.7} />
      </mesh>
      <mesh position={[0, 0.62, -0.5]} castShadow>
        <sphereGeometry args={[0.06, 10, 10]} />
        <meshStandardMaterial color={accent} roughness={0.7} />
      </mesh>
      <Legs color={style.body} />
    </group>
  );
}

// ── Dog body: chunkier, floppy droop ears, short stubby wagging tail ──────────

function DogBody({
  style,
  accent,
  tailRef,
}: {
  style: AnimalStyle;
  accent: string;
  tailRef: React.RefObject<THREE.Group>;
}) {
  return (
    <group>
      {/* chunkier torso */}
      <RoundedBox args={[0.42, 0.36, 0.66]} radius={0.16} smoothness={3} position={[0, 0.36, 0]} castShadow receiveShadow>
        <meshStandardMaterial color={style.body} roughness={0.75} />
      </RoundedBox>
      {/* belly */}
      <RoundedBox args={[0.32, 0.18, 0.54]} radius={0.09} smoothness={3} position={[0, 0.26, 0.02]} castShadow>
        <meshStandardMaterial color={style.belly} roughness={0.8} />
      </RoundedBox>
      {/* head — a touch bigger + a snout */}
      <mesh position={[0, 0.52, 0.36]} castShadow>
        <sphereGeometry args={[0.23, 16, 16]} />
        <meshStandardMaterial color={style.body} roughness={0.65} />
      </mesh>
      <mesh position={[0, 0.46, 0.56]} castShadow>
        <RoundedBoxImpostor />
        <meshStandardMaterial color={style.belly} roughness={0.7} />
      </mesh>
      {/* nose */}
      <mesh position={[0, 0.48, 0.64]}>
        <sphereGeometry args={[0.05, 10, 10]} />
        <meshStandardMaterial color="#2a201a" roughness={0.5} />
      </mesh>
      {/* floppy droop ears */}
      {[-0.2, 0.2].map((ex) => (
        <mesh key={ex} position={[ex, 0.56, 0.32]} rotation={[0.2, 0, ex < 0 ? 0.5 : -0.5]} castShadow>
          <RoundedBoxEar />
          <meshStandardMaterial color={accent} roughness={0.7} />
        </mesh>
      ))}
      {/* eyes */}
      {[-0.08, 0.08].map((ex) => (
        <mesh key={ex} position={[ex, 0.55, 0.54]}>
          <sphereGeometry args={[0.035, 8, 8]} />
          <meshStandardMaterial color="#241b14" />
        </mesh>
      ))}
      {/* short stubby wagging tail */}
      <group ref={tailRef} position={[0, 0.5, -0.34]}>
        <mesh position={[0, 0.08, -0.06]} rotation={[-0.7, 0, 0]} castShadow>
          <cylinderGeometry args={[0.05, 0.07, 0.26, 8]} />
          <meshStandardMaterial color={style.body} roughness={0.75} />
        </mesh>
      </group>
      <Legs color={style.body} />
    </group>
  );
}

/** Four little stubby legs shared by both species. */
function Legs({ color }: { color: string }) {
  const feet: Array<[number, number]> = [
    [-0.13, 0.2],
    [0.13, 0.2],
    [-0.13, -0.2],
    [0.13, -0.2],
  ];
  return (
    <>
      {feet.map(([fx, fz], i) => (
        <mesh key={i} position={[fx, 0.1, fz]} castShadow>
          <cylinderGeometry args={[0.055, 0.06, 0.2, 6]} />
          <meshStandardMaterial color={color} roughness={0.8} />
        </mesh>
      ))}
    </>
  );
}

/** A small rounded snout block (kept as its own component for readability). */
function RoundedBoxImpostor() {
  return <boxGeometry args={[0.16, 0.12, 0.16]} />;
}

/** A floppy ear flap (a thin rounded box). */
function RoundedBoxEar() {
  return <boxGeometry args={[0.1, 0.2, 0.04]} />;
}

// ── A magenta accent collar for chaotic critters ──────────────────────────────

function ChaosCollar() {
  return (
    <mesh position={[0, 0.4, 0.24]} rotation={[Math.PI / 2.2, 0, 0]}>
      <torusGeometry args={[0.18, 0.035, 10, 20]} />
      <meshStandardMaterial
        color={ANIMAL_CHAOS_MAGENTA}
        emissive={ANIMAL_CHAOS_MAGENTA}
        emissiveIntensity={0.7}
        roughness={0.4}
      />
    </mesh>
  );
}

export function Critter({ animal, center, animRef, chaotic }: CritterProps) {
  const groupRef = useRef<THREE.Group>(null);
  const tailRef = useRef<THREE.Group>(null);
  const bobPhase = useRef(hashUnit(animal.id) * Math.PI * 2);
  // A stable phase offset + speed for the wander loop, seeded from the id so
  // each critter roams its own path (deterministic, no per-frame allocation).
  const wanderSeed = useMemo(() => hashUnit(animal.id + ':wander'), [animal.id]);
  const wanderPhase = useRef(wanderSeed * Math.PI * 2);

  const style = useMemo(() => animalStyle(animal.species), [animal.species]);
  const accent = style.accent;

  useFrame((_, delta) => {
    const g = groupRef.current;
    if (!g) return;

    if (!animal.alive) {
      g.position.set(animRef.x, 0, animRef.z);
      g.rotation.x = -Math.PI / 2.4; // curled over, resting
      g.rotation.z = 0.3;
      return;
    }

    // Roam: a slow looping orbit around the place center, with a gentle radius
    // wobble so it reads as wandering rather than a perfect circle.
    wanderPhase.current += delta * (0.5 + wanderSeed * 0.4);
    const r = WANDER_RADIUS * (0.55 + 0.45 * Math.abs(Math.sin(wanderPhase.current * 0.7)));
    const targetX = center.x + Math.cos(wanderPhase.current) * r;
    const targetZ = center.z + Math.sin(wanderPhase.current) * r;

    // Lerp toward the roaming target (frame-rate aware) so re-centres are smooth.
    const lerp = 1 - Math.pow(0.06, delta);
    animRef.x += (targetX - animRef.x) * lerp;
    animRef.z += (targetZ - animRef.z) * lerp;

    const dx = targetX - animRef.x;
    const dz = targetZ - animRef.z;
    const moving = Math.hypot(dx, dz) > 0.02;

    g.position.x = animRef.x;
    g.position.z = animRef.z;

    // Trotting bob.
    bobPhase.current += delta * (moving ? 9 : 2.4);
    g.position.y = Math.abs(Math.sin(bobPhase.current)) * (moving ? 0.08 : 0.03);

    // Face direction of travel.
    if (moving) {
      const yaw = Math.atan2(dx, dz);
      let diff = yaw - g.rotation.y;
      while (diff > Math.PI) diff -= Math.PI * 2;
      while (diff < -Math.PI) diff += Math.PI * 2;
      g.rotation.y += diff * Math.min(1, delta * 6);
    }
    g.rotation.x = 0;
    g.rotation.z = 0;

    // Dog tail wag (only when a dog, tailRef present).
    if (tailRef.current) {
      tailRef.current.rotation.y = Math.sin(bobPhase.current * 1.6) * 0.5;
    }
  });

  return (
    <group ref={groupRef}>
      {animal.species === 'cat' ? (
        <CatBody style={style} accent={accent} />
      ) : (
        <DogBody style={style} accent={accent} tailRef={tailRef} />
      )}

      {chaotic && animal.alive && <ChaosCollar />}

      <CritterLabel animal={animal} chaotic={chaotic} />
    </group>
  );
}
