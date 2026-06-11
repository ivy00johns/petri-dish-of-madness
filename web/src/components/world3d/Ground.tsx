/**
 * Ground — soft grassy plane, per-district ground-zone tints, and the Wave C
 * LANE NETWORK (EM-149). The old hub→place spoke "pinwheel" is gone: lanes
 * come from townLayout's graph — a main-lane spine ringing the district
 * anchors plus connector lanes wiring every place in — with round junction
 * patches where lanes meet so corners read finished.
 *
 * Look-dev call (contract §12): widened warm-toon lane STRIPS won over Kenney
 * road tiles — flat toon strips sit inside the golden-hour banding (one
 * material family with the terrain), while tiled roads read as a different
 * art style and would cost a per-tile draw/UV pass for no warmth gained.
 *
 * EM-111: terrain/lanes use the shared GOLDEN_HOUR palette via the cached
 * warm-toon material factory (toon.ts) — banded cel shading, warm shadows.
 * Zone tints are deliberately subtle: two stacked translucent toon discs per
 * district (soft, banded edge — no textures, no new packages).
 */

import { useMemo } from 'react';
import type { Place } from '../../types';
import { WORLD_REACH } from './worldSpace';
import { GOLDEN_HOUR, toonMaterial } from './toon';
import {
  computeTownLayout,
  LANE_COLORS,
  LANE_WIDTHS,
  type LaneSegment,
} from './townLayout';

interface GroundProps {
  places: Place[];
}

/** One lane strip on the XZ plane (width + color by lane kind). */
function Lane({ lane }: { lane: LaneSegment }) {
  const { length, angle, midX, midZ } = useMemo(() => {
    const dx = lane.bx - lane.ax;
    const dz = lane.bz - lane.az;
    return {
      length: Math.hypot(dx, dz),
      // rotate a +X-aligned plane to point along the lane on the XZ plane
      angle: -Math.atan2(dz, dx),
      midX: (lane.ax + lane.bx) / 2,
      midZ: (lane.az + lane.bz) / 2,
    };
  }, [lane]);

  return (
    <mesh
      position={[midX, 0.02, midZ]}
      rotation={[-Math.PI / 2, 0, angle]}
      receiveShadow
      material={toonMaterial(LANE_COLORS[lane.kind])}
    >
      <planeGeometry args={[length, LANE_WIDTHS[lane.kind]]} />
    </mesh>
  );
}

export function Ground({ places }: GroundProps) {
  // The full town plan: lane graph + junctions + district zones (pure,
  // deterministic — same world, same plan).
  const town = useMemo(() => computeTownLayout(places), [places]);

  return (
    <group>
      {/* Grassy ground plane (camera never dips below the horizon — the
          orbit polar clamp keeps us topside, so front-face only is fine).
          Wave D1 (EM-154): sized by WORLD_REACH so the generated city ring
          (instances out to ~±85) stands on grass, not on the void. */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, 0, 0]}
        receiveShadow
        material={toonMaterial(GOLDEN_HOUR.terrain)}
      >
        <planeGeometry args={[WORLD_REACH * 2, WORLD_REACH * 2, 1, 1]} />
      </mesh>

      {/* A slightly darker grass "field" border ring for depth */}
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, -0.01, 0]}
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
            material={toonMaterial(z.tint, { transparent: true, opacity: 0.26 })}
          >
            <circleGeometry args={[z.radius, 40]} />
          </mesh>
          <mesh
            rotation={[-Math.PI / 2, 0, 0]}
            position={[z.x, 0.007, z.z]}
            material={toonMaterial(z.tint, { transparent: true, opacity: 0.3 })}
          >
            <circleGeometry args={[z.radius * 0.62, 36]} />
          </mesh>
        </group>
      ))}

      {/* Lane network: warm-toon strips (spine wider + a shade deeper). */}
      {town.lanes.map((lane, i) => (
        <Lane key={`lane-${i}`} lane={lane} />
      ))}

      {/* Junction patches where lanes meet/bend, so corners read finished.
          Slightly above the strips, in the connector tone, no z-fighting. */}
      {town.junctions.map((j, i) => (
        <mesh
          key={`junction-${i}`}
          rotation={[-Math.PI / 2, 0, 0]}
          position={[j.x, 0.022, j.z]}
          receiveShadow
          material={toonMaterial(LANE_COLORS.connector)}
        >
          <circleGeometry args={[j.r, 20]} />
        </mesh>
      ))}
    </group>
  );
}
