/**
 * Ground — soft grassy plane plus subtle dirt paths connecting the places.
 *
 * The plane receives shadows. Paths are thin, low-lying rounded strips drawn
 * from the plaza (social) hub out to each other place so the village reads as
 * "connected".
 *
 * EM-111: terrain/paths use the shared GOLDEN_HOUR palette via the cached
 * warm-toon material factory (toon.ts) — banded cel shading, warm shadows.
 */

import { useMemo } from 'react';
import type { Place } from '../../types';
import { SIZE, placeToWorld } from './worldSpace';
import { GOLDEN_HOUR, toonMaterial } from './toon';

interface GroundProps {
  places: Place[];
}

/** A single dirt path strip from A to B on the XZ plane. */
function Path({
  from,
  to,
}: {
  from: { x: number; z: number };
  to: { x: number; z: number };
}) {
  const { length, angle, midX, midZ } = useMemo(() => {
    const dx = to.x - from.x;
    const dz = to.z - from.z;
    return {
      length: Math.hypot(dx, dz),
      // rotate a +X-aligned plane to point along the path on the XZ plane
      angle: -Math.atan2(dz, dx),
      midX: (from.x + to.x) / 2,
      midZ: (from.z + to.z) / 2,
    };
  }, [from, to]);

  return (
    <mesh
      position={[midX, 0.02, midZ]}
      rotation={[-Math.PI / 2, 0, angle]}
      receiveShadow
      material={toonMaterial(GOLDEN_HOUR.path)}
    >
      <planeGeometry args={[length, 1.4]} />
    </mesh>
  );
}

export function Ground({ places }: GroundProps) {
  // Connect the social hub to every other place; if no social place exists,
  // fall back to the first place as the hub.
  const paths = useMemo(() => {
    if (places.length < 2) return [];
    const hub = places.find((p) => p.kind === 'social') ?? places[0];
    const hubW = placeToWorld(hub);
    return places
      .filter((p) => p.id !== hub.id)
      .map((p) => ({ id: p.id, from: hubW, to: placeToWorld(p) }));
  }, [places]);

  return (
    <group>
      {/* Grassy ground plane (camera never dips below the horizon — the
          orbit polar clamp keeps us topside, so front-face only is fine). */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, 0, 0]}
        receiveShadow
        material={toonMaterial(GOLDEN_HOUR.terrain)}
      >
        <planeGeometry args={[SIZE * 1.6, SIZE * 1.6, 1, 1]} />
      </mesh>

      {/* A slightly darker grass "field" border ring for depth */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, -0.01, 0]}
        material={toonMaterial(GOLDEN_HOUR.terrainEdge)}
      >
        <circleGeometry args={[SIZE * 1.1, 48]} />
      </mesh>

      {/* Dirt paths */}
      {paths.map((p) => (
        <Path key={p.id} from={p.from} to={p.to} />
      ))}
    </group>
  );
}
