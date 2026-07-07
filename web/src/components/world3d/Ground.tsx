/**
 * Ground — soft grassy plane + per-district ground-zone tints for the compact
 * city grid (Wave D1.5).
 *
 * The Wave C LANE NETWORK is dead: the city's streets are the Kenney road
 * tiles emitted by cityLayout and rendered by CityScape, so this component no
 * longer draws lane strips or junction patches (computeTownLayout still runs
 * for its district ZONES, and returns empty lanes/junctions by contract).
 *
 * EM-111: terrain uses the shared GOLDEN_HOUR palette via the cached
 * warm-toon material factory (toon.ts) — banded cel shading, warm shadows.
 * Zone tints are deliberately subtle: two stacked translucent toon discs per
 * district (soft, banded edge — no textures, no new packages). They sit
 * BELOW the road tiles (y ≤ 0.007 vs the tiles' ~0.02+), so the grid stays
 * crisp while each neighborhood keeps its own grass tone.
 *
 * Extent: sized by WORLD_REACH, which Wave D1.5 shrank back to a compact
 * world (the 66u city span + a small grass apron — no more ring sprawl).
 */

import { useMemo } from 'react';
import type { Place } from '../../types';
import { WORLD_REACH } from './worldSpace';
import { GOLDEN_HOUR, toonMaterial } from './toon';
import { computeTownLayout } from './townLayout';

interface GroundProps {
  places: Place[];
}

export function Ground({ places }: GroundProps) {
  // District zones (pure, deterministic — same world, same plan). Lanes and
  // junctions are empty arrays since Wave D1.5; only the zones are consumed.
  const town = useMemo(() => computeTownLayout(places), [places]);

  return (
    <group>
      {/* Grassy ground plane (camera never dips below the horizon — the
          orbit polar clamp keeps us topside, so front-face only is fine).
          Wave D1.5: WORLD_REACH is compact again — the city grid (±33)
          stands on grass with a small apron, nothing more. */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, 0, 0]}
        receiveShadow
        material={toonMaterial(GOLDEN_HOUR.terrain)}
      >
        <planeGeometry args={[WORLD_REACH * 2, WORLD_REACH * 2, 1, 1]} />
      </mesh>

      {/* A slightly darker grass "field" border ring for depth. It underlies
          the main plane almost entirely (radius 1.35·REACH vs the ±REACH
          square), so it MUST sit far enough BELOW to clear depth-buffer
          precision. At the camera's near=0.1 / far=420, a 24-bit depth buffer
          only resolves ~0.01u at the map centre and ~0.02–0.025u out toward the
          fog line — so the old −0.01 gap fell AT/BELOW precision across the
          mid/far terrain and the two coplanar planes z-fought, shimmering as
          the "grass flicker at zoom-out" (EM-179 masked it with fog; it never
          fixed the depth conflict). −0.4u is ~20× that worst-case precision at
          every visible distance ⇒ the opaque main plane always wins the
          overlap (no z-fight), while the darker ring still reads beyond the
          square edge. Do NOT shrink this back toward 0. */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, -0.4, 0]}
        material={toonMaterial(GOLDEN_HOUR.terrainEdge)}
      >
        <circleGeometry args={[WORLD_REACH * 1.35, 48]} />
      </mesh>

      {/* Per-district ground-zone tints: two stacked translucent discs per
          zone — a wide faint wash plus a smaller, slightly stronger core —
          so each neighborhood gets a soft, toon-banded grass variation. */}
      {town.zones.map((z) => (
        <group key={z.key}>
          <mesh
            rotation={[-Math.PI / 2, 0, 0]}
            position={[z.x, 0.004, z.z]}
            material={toonMaterial(z.tint, {
              transparent: true,
              opacity: 0.26,
              depthWrite: false,
              polygonOffset: true,
            })}
          >
            <circleGeometry args={[z.radius, 40]} />
          </mesh>
          <mesh
            rotation={[-Math.PI / 2, 0, 0]}
            position={[z.x, 0.007, z.z]}
            material={toonMaterial(z.tint, {
              transparent: true,
              opacity: 0.3,
              depthWrite: false,
              polygonOffset: true,
            })}
          >
            <circleGeometry args={[z.radius * 0.62, 36]} />
          </mesh>
        </group>
      ))}
    </group>
  );
}
