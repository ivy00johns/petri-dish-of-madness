/**
 * RoadMesh.tsx — EM-247 (S5a): the R3F render of the PURE buildRoadMesh data.
 * Each non-empty bucket (ribbons / intersections / roundabouts / plazas) is ONE
 * raw THREE.InstancedMesh sharing one toon material, so the whole road network
 * is a handful of draw calls — matching CityScape's raw-InstancedMesh-per-bucket
 * pattern. Geometry is procedural + flat (ground-flush in XZ); any-angle ribbons
 * come from the generator (rotY = atan2(dz, dx)), oriented here per instance.
 *
 * This is the OPT-IN path behind CityScape's ROAD_MESH_ENABLED flag (default
 * OFF). The visual quality (atlas UV packing, lane markings, crosswalks, LOD,
 * chunked culling, roundabout island fidelity) is the spec's explicitly-deferred
 * "budget real iteration" behind the human visual sign-off — this is a
 * functional first-cut render, not the final art.
 */
import { useLayoutEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import type { CityGraph } from '../../types';
import {
  buildRoadMesh,
  type PatchInstance,
  type RibbonInstance,
  type RingInstance,
} from './roadMeshData';
import { toonMaterial } from './toon';

// ── Ground-flush heights (small offsets so buckets don't z-fight) ────────────
const ROAD_Y = 0.04;        // ribbon surface, just above the ground
const JUNCTION_Y = 0.05;    // intersection patch, just above the ribbons
const ROUNDABOUT_Y = 0.05;  // roundabout ring
const PLAZA_Y = 0.05;       // plaza pad

// ── Surface tints (WebGL colors are OUTSIDE the CSS token system by the
//    established village convention — see toon.ts header). ─────────────────────
/** Asphalt-grey road surface (ribbons + intersections + roundabouts). */
export const ROAD_MESH_COLOR = '#5b5b62';
/** Warm paving for plazas — matches CityScape's PAD_COLOR family. */
export const PLAZA_COLOR = '#cfc4ad';

/** Shared flat unit plane in XZ (rotateX baked in) — one geometry reused for
 *  ribbons, intersections and plazas; the normal points +Y so it reads from
 *  above. Module-level + shared ⇒ never per-instance allocation. */
const UNIT_PLANE = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);

/** EM-157: road set dressing is invisible to the pointer (no raycast walk). */
function noopRaycast(): void {}

// ── Per-instance matrices (pure compose helpers) ─────────────────────────────
const _pos = new THREE.Vector3();
const _quat = new THREE.Quaternion();
const _scl = new THREE.Vector3();
const _Y = new THREE.Vector3(0, 1, 0);

/**
 * A ribbon matrix: translate to the edge midpoint, rotate so the unit plane's
 * local +X (length axis) aligns with the edge direction, scale (length, 1,
 * width). rotY = atan2(dz, dx) is the edge angle; THREE's makeRotationY(θ) maps
 * +X → (cosθ, 0, −sinθ), so we negate to land on (cos rotY, 0, sin rotY).
 */
function ribbonMatrix(r: RibbonInstance, target: THREE.Matrix4): THREE.Matrix4 {
  _pos.set(r.x, ROAD_Y, r.z);
  _quat.setFromAxisAngle(_Y, -r.rotY);
  _scl.set(r.length, 1, r.width);
  return target.compose(_pos, _quat, _scl);
}

/** A flat square patch (intersection / plaza) of side `size`, at height `y`. */
function patchMatrix(p: PatchInstance, y: number, target: THREE.Matrix4): THREE.Matrix4 {
  _pos.set(p.x, y, p.z);
  _quat.identity();
  _scl.set(p.size, 1, p.size);
  return target.compose(_pos, _quat, _scl);
}

/** Bucket of bucket-type to a per-instance matrix list + count helper. */
export interface RoadBucket { key: string; count: number }

/**
 * The non-empty buckets of `buildRoadMesh(graph, seed)` as (key, count) pairs —
 * exposed so the smoke test can assert the InstancedMesh count without the R3F
 * reconciler. Mirrors the render's one-mesh-per-non-empty-bucket rule.
 */
export function roadMeshBuckets(
  graph: CityGraph | null | undefined,
  seed: number,
): RoadBucket[] {
  const m = buildRoadMesh(graph, seed);
  return (
    [
      { key: 'ribbons', count: m.ribbons.length },
      { key: 'intersections', count: m.intersections.length },
      { key: 'roundabouts', count: m.roundabouts.length },
      { key: 'plazas', count: m.plazas.length },
    ] as RoadBucket[]
  ).filter((b) => b.count > 0);
}

// ── Components ───────────────────────────────────────────────────────────────

/** One raw InstancedMesh for a bucket: writes matrices once, static, raycast-
 *  dead (EM-157). jsdom smoke mounts have no reconciler, so the ref may be an
 *  HTMLUnknownElement — matrices only apply to the real mesh. */
function RoadBucketMesh({
  name,
  geometry,
  material,
  matrices,
}: {
  name: string;
  geometry: THREE.BufferGeometry;
  material: THREE.Material;
  matrices: THREE.Matrix4[];
}) {
  const ref = useRef<THREE.InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh || typeof mesh.setMatrixAt !== 'function') return;
    mesh.raycast = noopRaycast;
    mesh.instanceMatrix.setUsage(THREE.StaticDrawUsage);
    for (let i = 0; i < matrices.length; i++) mesh.setMatrixAt(i, matrices[i]);
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
  }, [matrices]);
  return (
    <instancedMesh
      name={name}
      ref={ref}
      args={[geometry, material, matrices.length]}
      frustumCulled
      castShadow={false}
      receiveShadow
    />
  );
}

/**
 * Build the roundabout bucket: one shared RingGeometry (the inner/outer RATIO
 * from the first instance — all roundabouts share the S5a constants today) laid
 * flat, scaled per-instance by outerR. Returns null when the bucket is empty.
 */
function useRoundaboutBucket(rings: RingInstance[]): {
  geometry: THREE.BufferGeometry;
  matrices: THREE.Matrix4[];
} | null {
  return useMemo(() => {
    if (rings.length === 0) return null;
    const r0 = rings[0];
    const ratio = r0.outerR > 0 ? Math.min(0.99, r0.innerR / r0.outerR) : 0.5;
    const geometry = new THREE.RingGeometry(ratio, 1, 24).rotateX(-Math.PI / 2);
    const matrices = rings.map((r) => {
      const m = new THREE.Matrix4();
      _pos.set(r.x, ROUNDABOUT_Y, r.z);
      _quat.identity();
      _scl.set(r.outerR, 1, r.outerR);
      return m.compose(_pos, _quat, _scl);
    });
    return { geometry, matrices };
  }, [rings]);
}

/**
 * <RoadMesh> — renders the procedural road network for `graph` behind
 * CityScape's ROAD_MESH_ENABLED flag. One InstancedMesh per non-empty bucket;
 * empty buckets render nothing.
 */
export function RoadMesh({
  graph,
  seed,
}: {
  graph?: CityGraph | null;
  seed: number;
}) {
  const data = useMemo(() => buildRoadMesh(graph, seed), [graph, seed]);

  const ribbonMats = useMemo(
    () => data.ribbons.map((r) => ribbonMatrix(r, new THREE.Matrix4())),
    [data.ribbons],
  );
  const intersectionMats = useMemo(
    () => data.intersections.map((p) => patchMatrix(p, JUNCTION_Y, new THREE.Matrix4())),
    [data.intersections],
  );
  const plazaMats = useMemo(
    () => data.plazas.map((p) => patchMatrix(p, PLAZA_Y, new THREE.Matrix4())),
    [data.plazas],
  );
  const roundabout = useRoundaboutBucket(data.roundabouts);

  const surface = toonMaterial(ROAD_MESH_COLOR);
  const plazaMat = toonMaterial(PLAZA_COLOR);

  return (
    <group name="roadmesh">
      {ribbonMats.length > 0 && (
        <RoadBucketMesh
          name="road-ribbons"
          geometry={UNIT_PLANE}
          material={surface}
          matrices={ribbonMats}
        />
      )}
      {intersectionMats.length > 0 && (
        <RoadBucketMesh
          name="road-intersections"
          geometry={UNIT_PLANE}
          material={surface}
          matrices={intersectionMats}
        />
      )}
      {roundabout && (
        <RoadBucketMesh
          name="road-roundabouts"
          geometry={roundabout.geometry}
          material={surface}
          matrices={roundabout.matrices}
        />
      )}
      {plazaMats.length > 0 && (
        <RoadBucketMesh
          name="road-plazas"
          geometry={UNIT_PLANE}
          material={plazaMat}
          matrices={plazaMats}
        />
      )}
    </group>
  );
}
