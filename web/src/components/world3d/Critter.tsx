/**
 * Critter — the W8 Animal renderer: a roaming cat or dog in the cozy village.
 *
 * Animals are a DISTINCT entity type (world-model.md §W8), not human agents:
 * they share the world mechanically but act impulsively. They WANDER near
 * their place on a slow, looping path (not the ring-distributed villager
 * layout — animals roam).
 *
 * Body (EM-124): cats and dogs render the rigged Quaternius GLBs
 * (CHARACTER_MODELS.cat / .dog) through <CharacterModel> — 'Idle' at rest,
 * crossfade to 'Walk' while the wander lerp is in flight. The Wave B
 * procedural bodies stay as the <Suspense> fallback (contract rule 7), as the
 * dead-critter pose, and as the body for ANY OTHER species (EM-143's
 * god-spawned squirrels etc. have no GLB yet — characterAnim.critterModelFor
 * returns null and the procedural critter renders):
 *   cat → slim body, pointed upright ears, a long curling tail.
 *   dog → chunkier body, floppy droop ears, a short stubby wagging tail.
 *
 * A CHAOTIC animal (one that recently invoked a crime/structure-targeting or
 * other low-prior action — see the chaos heuristic in CozyWorld) gets a subtle
 * MAGENTA accent: a glowing collar + an emissive tint on its ears, the same
 * magenta as the Animal Chaos Feed + the replay timeline markers, so the chaos
 * register agrees across the 3D village and the 2D inspector.
 *
 * Colors are WebGL material colors (THREE.Color), explicitly OUTSIDE the CSS
 * design-token system (same convention as Building/Structure/Villager: the
 * GPU scene owns its warm palette; design-token-guard governs DOM/CSS only).
 */

import { Suspense, useCallback, useMemo, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import { Billboard, Html, RoundedBox, useCursor, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import type { Animal } from '../../types';
import type { AnimalModelId } from '../../lib/animalIdentity';
import {
  animalStyle,
  hashUnit,
  type AnimalStyle,
  ANIMAL_CHAOS_MAGENTA,
} from './worldSpace';
import { useProximity, ENTITY_LABEL_DIST } from './useProximity';
import { toonMaterial } from './toon';
import { CharacterModel, CharacterModelBoundary, type MotionState } from './Villager';
import { CHARACTER_MODELS } from './assets/models';
import {
  critterModelFor,
  nextMoving,
  stepYaw,
  yawTowards,
  CRITTER_MOVE,
} from './characterAnim';

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
  /**
   * EM-089: the model profile this critter consults on LLM-decision ticks
   * (from the latest animal llm_call — world_state animals don't carry it).
   * null/absent ⇒ the label omits the model chip (reflex-only so far).
   */
  model?: AnimalModelId | null;
  /** EM-095/099: true while the camera is following this critter. */
  focused?: boolean;
  /** EM-095/099: clicked → follow this critter (same mechanism as agents). */
  onPick?: () => void;
}

const LABEL_Y = 1.5;
// Radius the critter roams around its place center.
const WANDER_RADIUS = 3.2;

// Warm the GLTF cache for the critter models (preload de-dupes by url).
if (CHARACTER_MODELS.cat) useGLTF.preload(CHARACTER_MODELS.cat.url);
if (CHARACTER_MODELS.dog) useGLTF.preload(CHARACTER_MODELS.dog.url);

/** The floating info card above a critter: name, species, mood, energy —
 *  and (EM-089) the model profile it consults, in the profile's color (the
 *  same treatment villagers get), when known. */
function CritterLabel({
  animal,
  chaotic,
  model,
}: {
  animal: Animal;
  chaotic: boolean;
  model?: AnimalModelId | null;
}) {
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
          {/* EM-089: the model behind the critter (villager-style chip; the
              color is the profile's data-driven color). Omitted when unknown —
              an animal that has only ever acted on reflex has no model yet. */}
          {model && (
            <div
              style={{
                marginTop: 2,
                fontSize: 9.5,
                color: model.color ?? '#f4ecdf',
                fontWeight: 600,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                maxWidth: 130,
              }}
              title={`LLM decisions route to ${model.profile}`}
            >
              🧠 {model.profile}
            </div>
          )}
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
      <RoundedBox args={[0.34, 0.3, 0.62]} radius={0.13} smoothness={3} position={[0, 0.34, 0]} castShadow receiveShadow material={toonMaterial(style.body)} />
      {/* lighter belly */}
      <RoundedBox args={[0.26, 0.16, 0.5]} radius={0.08} smoothness={3} position={[0, 0.24, 0.02]} castShadow material={toonMaterial(style.belly)} />
      {/* head */}
      <mesh position={[0, 0.5, 0.34]} castShadow material={toonMaterial(style.body)}>
        <sphereGeometry args={[0.2, 16, 16]} />
      </mesh>
      {/* pointed upright ears */}
      {[-0.11, 0.11].map((ex) => (
        <mesh key={ex} position={[ex, 0.66, 0.32]} rotation={[0, 0, ex < 0 ? 0.2 : -0.2]} castShadow material={toonMaterial(accent)}>
          <coneGeometry args={[0.07, 0.16, 4]} />
        </mesh>
      ))}
      {/* eyes */}
      {[-0.07, 0.07].map((ex) => (
        <mesh key={ex} position={[ex, 0.52, 0.5]} material={toonMaterial('#241b14')}>
          <sphereGeometry args={[0.032, 8, 8]} />
        </mesh>
      ))}
      {/* long curling tail */}
      <mesh position={[0, 0.46, -0.4]} rotation={[0.9, 0, 0]} castShadow material={toonMaterial(style.body)}>
        <cylinderGeometry args={[0.04, 0.05, 0.5, 8]} />
      </mesh>
      <mesh position={[0, 0.62, -0.5]} castShadow material={toonMaterial(accent)}>
        <sphereGeometry args={[0.06, 10, 10]} />
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
      <RoundedBox args={[0.42, 0.36, 0.66]} radius={0.16} smoothness={3} position={[0, 0.36, 0]} castShadow receiveShadow material={toonMaterial(style.body)} />
      {/* belly */}
      <RoundedBox args={[0.32, 0.18, 0.54]} radius={0.09} smoothness={3} position={[0, 0.26, 0.02]} castShadow material={toonMaterial(style.belly)} />
      {/* head — a touch bigger + a snout */}
      <mesh position={[0, 0.52, 0.36]} castShadow material={toonMaterial(style.body)}>
        <sphereGeometry args={[0.23, 16, 16]} />
      </mesh>
      <mesh position={[0, 0.46, 0.56]} castShadow material={toonMaterial(style.belly)}>
        <RoundedBoxImpostor />
      </mesh>
      {/* nose */}
      <mesh position={[0, 0.48, 0.64]} material={toonMaterial('#2a201a')}>
        <sphereGeometry args={[0.05, 10, 10]} />
      </mesh>
      {/* floppy droop ears */}
      {[-0.2, 0.2].map((ex) => (
        <mesh key={ex} position={[ex, 0.56, 0.32]} rotation={[0.2, 0, ex < 0 ? 0.5 : -0.5]} castShadow material={toonMaterial(accent)}>
          <RoundedBoxEar />
        </mesh>
      ))}
      {/* eyes */}
      {[-0.08, 0.08].map((ex) => (
        <mesh key={ex} position={[ex, 0.55, 0.54]} material={toonMaterial('#241b14')}>
          <sphereGeometry args={[0.035, 8, 8]} />
        </mesh>
      ))}
      {/* short stubby wagging tail */}
      <group ref={tailRef} position={[0, 0.5, -0.34]}>
        <mesh position={[0, 0.08, -0.06]} rotation={[-0.7, 0, 0]} castShadow material={toonMaterial(style.body)}>
          <cylinderGeometry args={[0.05, 0.07, 0.26, 8]} />
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
        <mesh key={i} position={[fx, 0.1, fz]} castShadow material={toonMaterial(color)}>
          <cylinderGeometry args={[0.055, 0.06, 0.2, 6]} />
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

/**
 * The Wave B procedural critter — now the Suspense fallback, the dead-critter
 * pose, and the body for species without a GLB. Owns its own trotting bob and
 * the dog's tail wag on a local group (the GLB clips animate themselves, so
 * neither effect belongs on the shared parent group).
 */
function ProceduralCritterBody({
  animal,
  style,
  accent,
  motion,
}: {
  animal: Animal;
  style: AnimalStyle;
  accent: string;
  motion: React.MutableRefObject<MotionState>;
}) {
  const bodyRef = useRef<THREE.Group>(null);
  const tailRef = useRef<THREE.Group>(null);
  const bobPhase = useRef(hashUnit(animal.id) * Math.PI * 2);

  useFrame((_, delta) => {
    const b = bodyRef.current;
    if (!b) return;
    if (!animal.alive) {
      b.position.y = 0;
      return;
    }
    // Trotting bob.
    const moving = motion.current.moving;
    bobPhase.current += delta * (moving ? 9 : 2.4);
    b.position.y = Math.abs(Math.sin(bobPhase.current)) * (moving ? 0.08 : 0.03);
    // Dog tail wag (only when a dog, tailRef present).
    if (tailRef.current) {
      tailRef.current.rotation.y = Math.sin(bobPhase.current * 1.6) * 0.5;
    }
  });

  return (
    <group ref={bodyRef}>
      {animal.species === 'cat' ? (
        <CatBody style={style} accent={accent} />
      ) : (
        <DogBody style={style} accent={accent} tailRef={tailRef} />
      )}
    </group>
  );
}

// ── A magenta accent collar for chaotic critters ──────────────────────────────

function ChaosCollar() {
  return (
    <mesh
      position={[0, 0.4, 0.24]}
      rotation={[Math.PI / 2.2, 0, 0]}
      material={toonMaterial(ANIMAL_CHAOS_MAGENTA, {
        emissive: ANIMAL_CHAOS_MAGENTA,
        emissiveIntensity: 0.7,
      })}
    >
      <torusGeometry args={[0.18, 0.035, 10, 20]} />
    </mesh>
  );
}

export function Critter({ animal, center, animRef, chaotic, model, focused, onPick }: CritterProps) {
  const groupRef = useRef<THREE.Group>(null);
  const motion = useRef<MotionState>({ moving: false });
  const [hovered, setHovered] = useState(false);
  useCursor(hovered && Boolean(onPick));

  // EM-102: the info card collapses when the camera is far away, unless the
  // critter is hovered or being followed (EM-095/099) — those always reveal it.
  const near = useProximity(
    useCallback(() => ({ x: animRef.x, z: animRef.z }), [animRef]),
    ENTITY_LABEL_DIST,
  );
  const showLabel = near || hovered || Boolean(focused);

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (!onPick) return;
    e.stopPropagation();
    onPick();
  };
  // A stable phase offset + speed for the wander loop, seeded from the id so
  // each critter roams its own path (deterministic, no per-frame allocation).
  const wanderSeed = useMemo(() => hashUnit(animal.id + ':wander'), [animal.id]);
  const wanderPhase = useRef(wanderSeed * Math.PI * 2);

  const style = useMemo(() => animalStyle(animal.species), [animal.species]);
  const accent = style.accent;
  // Species → rigged GLB; unknown species (god-spawned etc.) stay procedural.
  const spec = critterModelFor(animal.species);

  useFrame((_, delta) => {
    const g = groupRef.current;
    if (!g) return;

    if (!animal.alive) {
      motion.current.moving = false;
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
    const dist = Math.hypot(dx, dz);
    // Hysteresis (start 0.02 / stop 0.008) — same anti-flicker treatment as
    // villagers, scaled to the critter wander epsilon.
    motion.current.moving = nextMoving(motion.current.moving, dist, CRITTER_MOVE);

    g.position.x = animRef.x;
    g.position.z = animRef.z;
    g.position.y = 0; // bob lives on the procedural body, clips animate the GLB

    // Face direction of travel (smoothed, wrap-aware); idle keeps last facing.
    if (motion.current.moving) {
      g.rotation.y = stepYaw(g.rotation.y, yawTowards(dx, dz), delta, 6);
    }
    g.rotation.x = 0;
    g.rotation.z = 0;
  });

  return (
    <group
      ref={groupRef}
      onClick={handleClick}
      onPointerOver={(e) => { e.stopPropagation(); setHovered(true); }}
      onPointerOut={() => setHovered(false)}
    >
      {/* body: rigged GLB for cat/dog when alive (procedural critter as the
          streaming fallback — contract rule 7); dead critters and unmodeled
          species keep the Wave B procedural body. */}
      {animal.alive && spec ? (
        <CharacterModelBoundary
          fallback={
            <ProceduralCritterBody animal={animal} style={style} accent={accent} motion={motion} />
          }
        >
          <Suspense
            fallback={
              <ProceduralCritterBody animal={animal} style={style} accent={accent} motion={motion} />
            }
          >
            <CharacterModel spec={spec} motion={motion} />
          </Suspense>
        </CharacterModelBoundary>
      ) : (
        <ProceduralCritterBody animal={animal} style={style} accent={accent} motion={motion} />
      )}

      {chaotic && animal.alive && <ChaosCollar />}

      {/* EM-095/099: follow indicator — flat acid ring (in-canvas GPU palette,
          mirroring --lab-acid). */}
      {focused && (
        <mesh position={[0, 0.04, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.45, 0.6, 24]} />
          <meshBasicMaterial color="#c8ff00" transparent opacity={0.75} />
        </mesh>
      )}

      {showLabel && <CritterLabel animal={animal} chaotic={chaotic} model={model} />}
    </group>
  );
}
