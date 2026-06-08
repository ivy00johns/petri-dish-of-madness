/**
 * CozyWorld — the cozy 3D village view (Stardew x Animal Crossing vibe).
 * Owns the R3F <Canvas>, warm late-afternoon lighting, a pleasant sky + fog,
 * the ground, scenery, buildings, and villagers. Spectator camera only.
 *
 * Data contract:
 *   world.places[] : { id, name, x, y (0..1000), kind, description }
 *   world.agents[] : { id, name, profile, profile_color, location, energy,
 *                      credits, mood, alive, ... }
 *   events[]       : NEWEST-FIRST, each with monotonic numeric `seq`.
 *                    'agent_speech' carries payload.said + payload.private.
 *                    Many kinds carry payload.routed_via (actual model).
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Sky } from '@react-three/drei';
import * as THREE from 'three';
import type { WorldState, WorldEvent } from '../../types';
import { Ground } from './Ground';
import { Scenery } from './Scenery';
import { Building } from './Building';
import { Villager, type AnimPos } from './Villager';
import type { BubbleData } from './ChatBubble';
import { placeToWorld, ringOffset, latestRoutedVia } from './worldSpace';

interface CozyWorldProps {
  world: WorldState | null;
  events: WorldEvent[];
}

const BUBBLE_LIFETIME_MS = 5200;
const MAX_BUBBLES_PER_AGENT = 3;
const SPEECH_TRUNCATE = 120;

/** Truncate spoken text for a tidy bubble. */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max - 1).trimEnd() + '…';
}

interface LiveBubble extends BubbleData {
  actorId: string;
  expires: number;
}

export function CozyWorld({ world, events }: CozyWorldProps) {
  // ── Chat bubble lifecycle ──────────────────────────────────────────────
  const lastSeqRef = useRef<number>(-1);
  const [bubbles, setBubbles] = useState<LiveBubble[]>([]);

  // Spawn bubbles for NEW agent_speech events (events are newest-first).
  useEffect(() => {
    if (events.length === 0) return;
    const maxSeq = events[0].seq;
    if (maxSeq <= lastSeqRef.current) return;

    // First time we see events, just adopt the baseline seq — don't flood the
    // scene with bubbles for the entire historical backlog.
    if (lastSeqRef.current < 0) {
      lastSeqRef.current = maxSeq;
      return;
    }

    const fresh: LiveBubble[] = [];
    const now = Date.now();
    for (const e of events) {
      if (e.seq <= lastSeqRef.current) break; // rest are older
      if (e.kind !== 'agent_speech') continue;
      const said = e.payload?.said;
      const actorId = e.actor_id;
      if (typeof said !== 'string' || !said || !actorId) continue;
      const isPrivate = e.payload?.private === true;
      fresh.push({
        id: e.seq,
        actorId,
        text: truncate(said, SPEECH_TRUNCATE),
        private: isPrivate,
        expires: now + BUBBLE_LIFETIME_MS,
      });
    }
    lastSeqRef.current = maxSeq;

    if (fresh.length > 0) {
      // newest first within this batch reads better when stacked
      setBubbles((prev) => [...prev, ...fresh.reverse()]);
    }
  }, [events]);

  // Expire old bubbles on a light interval.
  useEffect(() => {
    const t = window.setInterval(() => {
      const now = Date.now();
      setBubbles((prev) => {
        const next = prev.filter((b) => b.expires > now);
        return next.length === prev.length ? prev : next;
      });
    }, 500);
    return () => window.clearInterval(t);
  }, []);

  // Map: agentId -> latest routed_via model (scanned once per events change).
  const routedByAgent = useMemo(() => {
    const m = new Map<string, string>();
    if (world) {
      for (const a of world.agents) {
        const via = latestRoutedVia(events, a.id);
        if (via) m.set(a.id, via);
      }
    }
    return m;
  }, [events, world]);

  // Group active bubbles by agent (cap per agent).
  const bubblesByAgent = useMemo(() => {
    const m = new Map<string, BubbleData[]>();
    for (const b of bubbles) {
      const list = m.get(b.actorId) ?? [];
      list.push({ id: b.id, text: b.text, private: b.private });
      m.set(b.actorId, list);
    }
    for (const [k, v] of m) {
      if (v.length > MAX_BUBBLES_PER_AGENT) {
        m.set(k, v.slice(v.length - MAX_BUBBLES_PER_AGENT));
      }
    }
    return m;
  }, [bubbles]);

  if (!world) {
    return (
      <div className="flex h-full w-full items-center justify-center bg-lab-bg">
        <span className="font-mono text-xs text-lab-dim">AWAITING WORLD STATE…</span>
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <Canvas
        shadows
        dpr={[1, 2]}
        gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping }}
        camera={{ position: [24, 22, 24], fov: 42, near: 0.1, far: 400 }}
      >
        <color attach="background" args={['#f3e2c7']} />
        <Scene
          world={world}
          bubblesByAgent={bubblesByAgent}
          routedByAgent={routedByAgent}
        />
        <OrbitControls
          enablePan={false}
          autoRotate
          autoRotateSpeed={0.4}
          enableDamping
          dampingFactor={0.08}
          minDistance={14}
          maxDistance={60}
          minPolarAngle={0.25}
          maxPolarAngle={Math.PI / 2.3}
          target={[0, 1.5, 0]}
        />
      </Canvas>
    </div>
  );
}

/**
 * Scene — all in-Canvas contents: warm sky/light/fog, ground, scenery,
 * buildings, and villagers. Owns the per-agent animated-position map (a ref,
 * so re-renders from new world state never reset in-flight animations).
 * The routed_via model map is precomputed by CozyWorld (O(agents) per events
 * change) and injected here, keeping that scan out of the per-frame path.
 */
function Scene({
  world,
  bubblesByAgent,
  routedByAgent,
}: {
  world: WorldState;
  bubblesByAgent: Map<string, BubbleData[]>;
  routedByAgent: Map<string, string>;
}) {
  const animMap = useRef<Map<string, AnimPos>>(new Map());
  const { places, agents } = world;

  const placeCenters = useMemo(() => {
    const m = new Map<string, { x: number; z: number }>();
    places.forEach((p) => m.set(p.id, placeToWorld(p)));
    return m;
  }, [places]);

  const targets = useMemo(() => {
    const byPlace = new Map<string, string[]>();
    agents.forEach((a) => {
      const list = byPlace.get(a.location) ?? [];
      list.push(a.id);
      byPlace.set(a.location, list);
    });
    const result = new Map<string, AnimPos>();
    agents.forEach((a) => {
      const center = placeCenters.get(a.location);
      if (!center) {
        result.set(a.id, { x: 0, z: 0 });
        return;
      }
      const colocated = byPlace.get(a.location) ?? [a.id];
      const idx = colocated.indexOf(a.id);
      const pos = ringOffset(center, idx, colocated.length);
      result.set(a.id, { x: pos.x, z: pos.z });
      if (!animMap.current.has(a.id)) {
        animMap.current.set(a.id, { x: pos.x, z: pos.z });
      }
    });
    return result;
  }, [agents, placeCenters]);

  return (
    <>
      <Sky
        distance={450000}
        sunPosition={[8, 6, 4]}
        inclination={0.48}
        azimuth={0.25}
        turbidity={6}
        rayleigh={1.2}
        mieCoefficient={0.01}
        mieDirectionalG={0.85}
      />
      <hemisphereLight args={['#fff3df', '#7aa05f', 0.7]} />
      <ambientLight intensity={0.25} color="#ffe9cc" />
      <directionalLight
        position={[14, 18, 8]}
        intensity={1.5}
        color="#ffd9a0"
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={1}
        shadow-camera-far={70}
        shadow-camera-left={-32}
        shadow-camera-right={32}
        shadow-camera-top={32}
        shadow-camera-bottom={-32}
        shadow-bias={-0.0004}
      />
      <fog attach="fog" args={['#f3e2c7', 45, 95]} />

      <Ground places={places} />
      <Scenery places={places} />

      {places.map((p) => (
        <Building key={p.id} place={p} />
      ))}

      {agents.map((a) => {
        const target = targets.get(a.id) ?? { x: 0, z: 0 };
        let anim = animMap.current.get(a.id);
        if (!anim) {
          anim = { x: target.x, z: target.z };
          animMap.current.set(a.id, anim);
        }
        return (
          <Villager
            key={a.id}
            agent={a}
            target={target}
            animRef={anim}
            routedVia={routedByAgent.get(a.id)}
            bubbles={bubblesByAgent.get(a.id) ?? []}
          />
        );
      })}
    </>
  );
}
