/**
 * Villager — a cute, rounded character for one agent.
 *
 * Movement: a parent useRef map (in CozyWorld) holds the current animated
 * {x,z} for every agent. This component lerps from its current animated
 * position toward its target place position over ~1s with a gentle walking
 * bob; idle villagers do a subtle idle bob. Dead agents lie down as a faded
 * ghost with a small tombstone and stop moving.
 *
 * Floating label above each: name, energy bar, credits w/ coin, mood, and the
 * ACTUAL model (latest routed_via, fallback profile).
 */

import { useCallback, useRef, useState } from 'react';
import { useFrame } from '@react-three/fiber';
import type { ThreeEvent } from '@react-three/fiber';
import { Billboard, Html, RoundedBox, useCursor } from '@react-three/drei';
import * as THREE from 'three';
import type { Agent } from '../../types';
import { ChatBubble, type BubbleData } from './ChatBubble';
import { useProximity, ENTITY_LABEL_DIST } from './useProximity';

export interface AnimPos {
  x: number;
  z: number;
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

/** Slightly darken a hex color for the body shade vs the head. */
function shade(hex: string, amount: number): string {
  const c = new THREE.Color(hex);
  c.multiplyScalar(amount);
  return `#${c.getHexString()}`;
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
  const bobPhase = useRef(Math.random() * Math.PI * 2);
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

  useFrame((_, delta) => {
    const g = groupRef.current;
    if (!g) return;

    if (!agent.alive) {
      // Dead: stop moving, settle in place, lie down.
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
    const moving = dist > 0.05;

    g.position.x = animRef.x;
    g.position.z = animRef.z;

    // Bob: brisk hop while walking, gentle idle sway otherwise.
    bobPhase.current += delta * (moving ? 11 : 2.2);
    const amp = moving ? 0.18 : 0.05;
    g.position.y = Math.abs(Math.sin(bobPhase.current)) * amp;

    // Face direction of travel.
    if (moving) {
      const targetYaw = Math.atan2(dx, dz);
      let cur = g.rotation.y;
      let diff = targetYaw - cur;
      while (diff > Math.PI) diff -= Math.PI * 2;
      while (diff < -Math.PI) diff += Math.PI * 2;
      g.rotation.y = cur + diff * Math.min(1, delta * 8);
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
      {/* shadow-casting body group */}
      <group>
        {/* body */}
        <RoundedBox
          args={[0.6, BODY_HEIGHT, 0.5]}
          radius={0.22}
          smoothness={3}
          position={[0, BODY_HEIGHT / 2 + 0.05, 0]}
          castShadow
          receiveShadow
        >
          <meshStandardMaterial
            color={bodyColor}
            roughness={0.7}
            transparent={!agent.alive}
            opacity={agent.alive ? 1 : 0.4}
          />
        </RoundedBox>
        {/* head */}
        <mesh position={[0, HEAD_Y, 0]} castShadow>
          <sphereGeometry args={[0.34, 18, 18]} />
          <meshStandardMaterial
            color={color}
            roughness={0.55}
            transparent={!agent.alive}
            opacity={agent.alive ? 1 : 0.4}
          />
        </mesh>
        {/* little eyes (only when alive) */}
        {agent.alive && (
          <>
            <mesh position={[0.12, HEAD_Y + 0.04, 0.3]}>
              <sphereGeometry args={[0.05, 8, 8]} />
              <meshStandardMaterial color="#241b14" />
            </mesh>
            <mesh position={[-0.12, HEAD_Y + 0.04, 0.3]}>
              <sphereGeometry args={[0.05, 8, 8]} />
              <meshStandardMaterial color="#241b14" />
            </mesh>
          </>
        )}
      </group>

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
          <mesh position={[0, 0.45, 0]} castShadow>
            <boxGeometry args={[0.5, 0.9, 0.14]} />
            <meshStandardMaterial color="#9aa0a6" roughness={1} />
          </mesh>
          <mesh position={[0, 0.95, 0]} castShadow>
            <cylinderGeometry args={[0.25, 0.25, 0.14, 16, 1, false, 0, Math.PI]} />
            <meshStandardMaterial color="#9aa0a6" roughness={1} />
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
