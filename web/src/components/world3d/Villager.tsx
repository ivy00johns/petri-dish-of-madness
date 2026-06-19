/**
 * Villager — a rigged, animated character for one agent (EM-124).
 *
 * Movement: a parent useRef map (in CozyWorld) holds the current animated
 * {x,z} for every agent. This component lerps from its current animated
 * position toward its target place position over ~1s; a hysteresis on the
 * distance-to-target (characterAnim.nextMoving) derives the moving/idle state
 * that drives the animation clips. Dead agents lie down as a faded ghost with
 * a small tombstone and stop moving.
 *
 * Body: the KayKit villager GLB (CHARACTER_MODELS.villager) rendered through
 * <CharacterModel> — a <Clone> of the shared toon-converted scene, tinted with
 * the agent's identity color on the CLONED tree only, playing 'Idle' at rest
 * and crossfading to 'Walking_A' while in motion. The Wave B procedural
 * capsule remains as the <Suspense> fallback (contract rule 7: the scene
 * never shows a hole) and as the ghost body for dead agents.
 *
 * Floating label above each: name, energy bar, credits w/ coin, mood, and the
 * ACTUAL model (latest routed_via, fallback profile).
 */

import React, { Suspense, useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import { Billboard, Html, RoundedBox, useAnimations, useCursor, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { SkeletonUtils } from 'three-stdlib';
import type { Agent } from '../../types';
import { ChatBubble, type BubbleData } from './ChatBubble';
import { useProximity, ENTITY_LABEL_DIST } from './useProximity';
import { toonMaterial } from './toon';
import { CHARACTER_MODELS, type ModelSpec } from './assets/models';
import { useToonGLTF } from './assets/Model';
import { applyTintToScene } from './assets/toonify';
import {
  clipFor,
  nextMoving,
  stepYaw,
  yawTowards,
  villagerModelFor,
  VILLAGER_MOVE,
} from './characterAnim';

export interface AnimPos {
  x: number;
  z: number;
}

/** Shared mutable movement state, written by the parent lerp's useFrame and
 *  read by the body components' own frame loops (clip choice / bob). */
export interface MotionState {
  moving: boolean;
}

interface VillagerProps {
  agent: Agent;
  /** Target world position (already ring-distributed for co-located agents). */
  target: AnimPos;
  /** Shared mutable animated position for this agent (mutated in useFrame). */
  animRef: AnimPos;
  /** The model that actually answered most recently (fallback handled here). */
  routedVia?: string;
  /** Active speech bubbles for this agent. */
  bubbles: BubbleData[];
  /** EM-095: true while the camera is following this villager. */
  focused?: boolean;
  /** EM-095: clicked → follow this villager. */
  onPick?: () => void;
}

const BODY_HEIGHT = 0.9;
const HEAD_Y = 1.45;
const LABEL_Y = 2.5;
/** Idle ↔ walk crossfade duration (seconds). */
const CROSSFADE = 0.25;

// Warm the GLTF cache for the villager model so the capsule fallback only
// flashes on a cold cache (useGLTF.preload de-dupes by url, so this composes
// with any scene-level preload).
if (CHARACTER_MODELS.villager) useGLTF.preload(CHARACTER_MODELS.villager.url);

/** Slightly darken a hex color for the body shade vs the head. */
function shade(hex: string, amount: number): string {
  const c = new THREE.Color(hex);
  c.multiplyScalar(amount);
  return `#${c.getHexString()}`;
}

/**
 * Fallback invariant, part 2 (contract rule 7): <Suspense> only covers a GLB
 * while it LOADS — if the fetch fails (404, aborted, offline), drei useGLTF
 * THROWS and the error would climb past Suspense and take the whole Canvas
 * down. This boundary catches it and pins the procedural body instead, so a
 * missing model can never blank the scene. Shared by Villager and Critter.
 */
export class CharacterModelBoundary extends React.Component<
  { fallback: React.ReactNode; children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error) {
    console.warn('[EM-124] character GLB failed to load — procedural body stays:', error.message);
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/**
 * A rigged GLB character body: a SkeletonUtils.clone of the shared
 * toon-converted scene (NOT drei <Clone> — its JSX re-spread of the node
 * hierarchy mis-rebinds Quaternius rigs whose armature AND mesh nodes carry
 * nested 100× scales, throwing the skinned result hundreds of units off;
 * SkeletonUtils.clone preserves the hierarchy + bindings exactly), identity-
 * tinted on the CLONED tree only (applyTintToScene clones materials before
 * touching them), driving drei useAnimations — idle clip at rest, crossfade
 * to the walk clip while `motion.moving` (no procedural bob: the clips own
 * the body motion). Skinned meshes get frustumCulled=false: their culling
 * sphere is the bind pose, which these rigs park far away from the animated
 * body. Shared by Villager and Critter; must be mounted inside <Suspense>
 * with the procedural body as fallback.
 */
export function CharacterModel({
  spec,
  motion,
  tint,
}: {
  spec: ModelSpec;
  motion: React.MutableRefObject<MotionState>;
  /** Per-instance identity tint (villagers); omit to keep the GLB's palette. */
  tint?: string;
}) {
  const { scene, animations } = useToonGLTF(spec.url);
  const root = useRef<THREE.Group>(null);
  // One faithful clone per character instance; materials stay shared with the
  // toonified source until applyTintToScene clones them for tinting.
  const cloned = useMemo(() => {
    const c = SkeletonUtils.clone(scene);
    c.traverse((o) => {
      if ((o as THREE.SkinnedMesh).isSkinnedMesh) o.frustumCulled = false;
    });
    return c;
  }, [scene]);
  const { actions } = useAnimations(animations, root);
  const currentClip = useRef<string | null>(null);

  // Identity tint — on the cloned subtree only, never the shared scene.
  useLayoutEffect(() => {
    if (root.current && tint) applyTintToScene(root.current, tint);
  }, [tint, cloned]);

  // Drive the mixer from the shared movement state: pick the clip for the
  // current moving flag and crossfade whenever it changes (first frame fades
  // the idle clip in from nothing).
  useFrame(() => {
    const want = clipFor(motion.current.moving, spec.clips);
    if (!want || want === currentClip.current) return;
    const next = actions[want];
    if (!next) return;
    const prev = currentClip.current ? actions[currentClip.current] : null;
    next.reset().fadeIn(CROSSFADE).play();
    prev?.fadeOut(CROSSFADE);
    currentClip.current = want;
  });

  return (
    <group
      ref={root}
      scale={spec.scale}
      position-y={spec.yOffset}
      rotation-y={spec.rotation ?? 0}
    >
      <primitive object={cloned} />
    </group>
  );
}

/**
 * The Wave B procedural capsule body — now the Suspense fallback while the
 * GLB streams, and the ghost body for dead agents. Keeps its own walking-hop /
 * idle-sway bob (driven by the shared motion state) on a local group so the
 * label and bubbles above don't inherit it.
 */
function CapsuleBody({
  color,
  bodyColor,
  alive,
  motion,
}: {
  color: string;
  bodyColor: string;
  alive: boolean;
  motion: React.MutableRefObject<MotionState>;
}) {
  const bodyRef = useRef<THREE.Group>(null);
  const bobPhase = useRef(Math.random() * Math.PI * 2);

  useFrame((_, delta) => {
    const b = bodyRef.current;
    if (!b) return;
    if (!alive) {
      b.position.y = 0;
      return;
    }
    // Bob: brisk hop while walking, gentle idle sway otherwise.
    const moving = motion.current.moving;
    bobPhase.current += delta * (moving ? 11 : 2.2);
    const amp = moving ? 0.18 : 0.05;
    b.position.y = Math.abs(Math.sin(bobPhase.current)) * amp;
  });

  return (
    <group ref={bodyRef}>
      {/* body — cached warm-toon material; ghosts get the transparent
          variant (a distinct cache entry, EM-111) */}
      <RoundedBox
        args={[0.6, BODY_HEIGHT, 0.5]}
        radius={0.22}
        smoothness={3}
        position={[0, BODY_HEIGHT / 2 + 0.05, 0]}
        castShadow
        receiveShadow
        material={toonMaterial(
          bodyColor,
          alive ? {} : { transparent: true, opacity: 0.4 },
        )}
      />
      {/* head */}
      <mesh
        position={[0, HEAD_Y, 0]}
        castShadow
        material={toonMaterial(
          color,
          alive ? {} : { transparent: true, opacity: 0.4 },
        )}
      >
        <sphereGeometry args={[0.34, 18, 18]} />
      </mesh>
      {/* little eyes (only when alive) */}
      {alive && (
        <>
          <mesh position={[0.12, HEAD_Y + 0.04, 0.3]} material={toonMaterial('#241b14')}>
            <sphereGeometry args={[0.05, 8, 8]} />
          </mesh>
          <mesh position={[-0.12, HEAD_Y + 0.04, 0.3]} material={toonMaterial('#241b14')}>
            <sphereGeometry args={[0.05, 8, 8]} />
          </mesh>
        </>
      )}
    </group>
  );
}

/** The floating info card above a villager. */
function VillagerLabel({
  agent,
  routedVia,
}: {
  agent: Agent;
  routedVia?: string;
}) {
  const energy = Math.max(0, Math.min(100, agent.energy));
  const model = routedVia ?? agent.profile;
  const color = agent.profile_color ?? '#cccccc';

  return (
    <Billboard position={[0, LABEL_Y, 0]}>
      <Html center distanceFactor={13} zIndexRange={[30, 0]} style={{ pointerEvents: 'none' }}>
        <div
          style={{
            opacity: agent.alive ? 1 : 0.45,
            minWidth: 96,
            padding: '4px 7px 5px',
            borderRadius: 10,
            background: 'rgba(40,32,26,0.86)',
            color: '#f4ecdf',
            fontFamily: '"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif',
            fontSize: 11,
            lineHeight: 1.25,
            textAlign: 'center',
            boxShadow: '0 3px 9px rgba(0,0,0,0.3)',
            border: `1px solid ${color}66`,
            userSelect: 'none',
          }}
        >
          <div style={{ fontWeight: 700, color: '#fff7ea' }}>
            {agent.name}
            {!agent.alive && <span style={{ opacity: 0.7 }}> (gone)</span>}
          </div>
          {/* energy bar */}
          <div
            style={{
              height: 5,
              borderRadius: 3,
              background: 'rgba(255,255,255,0.16)',
              margin: '3px 0',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${energy}%`,
                height: '100%',
                borderRadius: 3,
                background:
                  energy > 50 ? '#7ed957' : energy > 20 ? '#ffcf5c' : '#ff6b5c',
                transition: 'width 300ms ease',
              }}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 6, fontSize: 10 }}>
            <span title="credits">
              <span style={{ color: '#ffd95c' }}>●</span> {agent.credits}
            </span>
            <span style={{ opacity: 0.85 }}>{agent.mood}</span>
          </div>
          <div
            style={{
              marginTop: 2,
              fontSize: 9.5,
              color,
              fontWeight: 600,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              maxWidth: 130,
            }}
            title={model}
          >
            {model}
          </div>
        </div>
      </Html>
    </Billboard>
  );
}

export function Villager({ agent, target, animRef, routedVia, bubbles, focused, onPick }: VillagerProps) {
  const groupRef = useRef<THREE.Group>(null);
  const motion = useRef<MotionState>({ moving: false });
  const [hovered, setHovered] = useState(false);
  useCursor(hovered && Boolean(onPick));

  // EM-102: the info card collapses when the camera is far away (it would be
  // unreadably small and just stack on the building labels) — unless this
  // villager is hovered or being followed (EM-095), which always reveals it.
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

  const color = agent.profile_color ?? '#b0b0b0';
  const bodyColor = shade(color, 0.85);
  // EM-216b: per-agent villager mesh from the variety pool (deterministic by id).
  const spec = villagerModelFor(agent.id);

  useFrame((_, delta) => {
    const g = groupRef.current;
    if (!g) return;

    if (!agent.alive) {
      // Dead: stop moving, settle in place, lie down.
      motion.current.moving = false;
      g.position.x = animRef.x;
      g.position.z = animRef.z;
      g.position.y = 0;
      g.rotation.x = -Math.PI / 2.2; // tipped over
      g.rotation.z = 0.2;
      return;
    }

    // Lerp animated position toward the target over ~1s (frame-rate aware).
    const lerp = 1 - Math.pow(0.02, delta); // ~98%/sec
    animRef.x += (target.x - animRef.x) * lerp;
    animRef.z += (target.z - animRef.z) * lerp;

    const dx = target.x - animRef.x;
    const dz = target.z - animRef.z;
    const dist = Math.hypot(dx, dz);
    // Hysteresis (start 0.05 / stop 0.02) so the walk↔idle clip choice can't
    // flicker as the exponential lerp's tail hovers around one epsilon.
    motion.current.moving = nextMoving(motion.current.moving, dist, VILLAGER_MOVE);

    g.position.x = animRef.x;
    g.position.z = animRef.z;
    g.position.y = 0; // bob lives on the body components, not the group

    // Face direction of travel (smoothed, wrap-aware); idle keeps last facing.
    if (motion.current.moving) {
      g.rotation.y = stepYaw(g.rotation.y, yawTowards(dx, dz), delta, 8);
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
      {/* body: rigged GLB when alive (capsule as the streaming fallback —
          contract rule 7, never a hole); dead agents keep the Wave B faded
          ghost capsule exactly as before. */}
      {agent.alive && spec ? (
        <CharacterModelBoundary
          fallback={
            <CapsuleBody color={color} bodyColor={bodyColor} alive motion={motion} />
          }
        >
          <Suspense
            fallback={
              <CapsuleBody color={color} bodyColor={bodyColor} alive motion={motion} />
            }
          >
            <CharacterModel spec={spec} motion={motion} tint={color} />
          </Suspense>
        </CharacterModelBoundary>
      ) : (
        <CapsuleBody
          color={color}
          bodyColor={bodyColor}
          alive={agent.alive}
          motion={motion}
        />
      )}

      {/* EM-095: follow indicator — a flat acid ring under the tracked
          villager (WebGL material color mirroring --lab-acid, the same
          in-canvas convention as the rest of the GPU palette). */}
      {focused && (
        <mesh position={[0, 0.05, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.55, 0.72, 28]} />
          <meshBasicMaterial color="#c8ff00" transparent opacity={0.75} />
        </mesh>
      )}

      {/* tombstone for the departed */}
      {!agent.alive && (
        <group position={[0.55, 0, 0]}>
          <mesh position={[0, 0.45, 0]} castShadow material={toonMaterial('#9aa0a6')}>
            <boxGeometry args={[0.5, 0.9, 0.14]} />
          </mesh>
          <mesh position={[0, 0.95, 0]} castShadow material={toonMaterial('#9aa0a6')}>
            <cylinderGeometry args={[0.25, 0.25, 0.14, 16, 1, false, 0, Math.PI]} />
          </mesh>
        </group>
      )}

      {showLabel && <VillagerLabel agent={agent} routedVia={routedVia} />}

      {/* active speech bubbles, stacked above the label */}
      {bubbles.map((b, i) => (
        <ChatBubble
          key={b.id}
          text={b.text}
          isPrivate={b.private}
          stackIndex={i}
          baseY={LABEL_Y + 0.9}
        />
      ))}
    </group>
  );
}
