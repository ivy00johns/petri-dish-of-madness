/**
 * CityScape — the instanced render path for the EW-grade generated city ring
 * (EM-154, Wave D1d), wrapping the Wave C historic core in zoned districts of
 * Kenney/KayKit set dressing.
 *
 * Pipeline: computeCityPlan (D1b, deterministic — seed = world.city_seed ??
 * 1337) × CITY_MODEL_REGISTRY (D1a) → one raw THREE.InstancedMesh per
 * (piece key × spatial chunk × material part).
 *
 *   • PLAN MEMO: the plan is cached on a content signature of (places,
 *     city_seed) — snapshot polling replaces the world object every tick, so
 *     identity-only memoization would rebuild the instance buffers each poll.
 *     Same signature ⇒ the SAME plan/chunk objects ⇒ zero re-uploads.
 *   • GEOMETRY/MATERIAL once per GLB: useToonGLTF loads + toon-converts the
 *     cached scene; extractInstanceParts() flattens it into (geometry,
 *     material) parts — same-material sub-meshes (Kenney cars are 5–6 nodes
 *     sharing one atlas material) are BAKED + MERGED into a single geometry,
 *     so a car key still costs one draw call per chunk. Parts are cached per
 *     scene; materials are the shared toon conversions (never cloned).
 *   • CHUNKING: instances split into 1/4/8 spatial chunks (quadrants/octants
 *     around the town centroid) by count, so frustum culling can drop the
 *     city behind the camera without exploding draw calls. Per-chunk bounding
 *     spheres are computed from the real instance matrices.
 *   • NON-INTERACTIVE (EM-157): set dressing carries NO pointer handlers and
 *     a no-op `raycast`, so click-to-focus raycasts against real buildings
 *     never walk thousands of city triangles.
 *   • FALLBACK (rule 10): a `null` registry entry, an empty piece list, or a
 *     GLB that fails to fetch simply skips that piece — each piece key is
 *     wrapped in a ModelBoundary (the Wave C pattern), so a 404 never
 *     unmounts the canvas. No hole, no crash.
 *
 * Matrices are written in useLayoutEffect with ONE instanceMatrix.needsUpdate
 * per chunk; buffers are marked StaticDrawUsage (the city never animates —
 * ambient traffic is EM-169 / W17).
 */

import { useLayoutEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import type { Place, WorldState } from '../../types';
import {
  CITY_PIECE_KEYS,
  computeCityPlan,
  townCenter,
  type CityInstance,
  type CityPieceKey,
  type CityPlan,
} from './cityLayout';
import { CITY_MODEL_REGISTRY } from './assets/cityModels';
import type { ModelSpec } from './assets/models';
import { useToonGLTF } from './assets/Model';
import { ModelBoundary } from './ModelBoundary';

// ── Chunking (pure, exported for tests) ──────────────────────────────────────

/** Piece keys with more instances than this split into 4 quadrant chunks. */
export const CHUNK_SPLIT_4 = 96;
/** …and beyond this, into 8 octant chunks (road_straight is ~700 alone). */
export const CHUNK_SPLIT_8 = 360;

/** How many spatial chunks a piece key with `n` instances gets (1 | 4 | 8). */
export function chunkCount(n: number): number {
  return n > CHUNK_SPLIT_8 ? 8 : n > CHUNK_SPLIT_4 ? 4 : 1;
}

/**
 * Which chunk an instance belongs to: quadrant (count 4) or angular octant
 * (count 8) around the town centroid. Pure + deterministic, so the same plan
 * always buckets identically.
 */
export function chunkIndexOf(
  inst: CityInstance,
  center: { x: number; z: number },
  count: number,
): number {
  if (count <= 1) return 0;
  if (count === 4) {
    return (inst.x >= center.x ? 1 : 0) + (inst.z >= center.z ? 2 : 0);
  }
  const angle = Math.atan2(inst.z - center.z, inst.x - center.x); // (-π, π]
  return Math.min(count - 1, Math.floor(((angle + Math.PI) / (2 * Math.PI)) * count));
}

/**
 * Partition a piece key's instances into spatial chunks (empty chunks
 * dropped). Within a chunk, plan emission order is preserved.
 */
export function chunkInstances(
  instances: readonly CityInstance[],
  center: { x: number; z: number },
): CityInstance[][] {
  const count = chunkCount(instances.length);
  if (count === 1) return instances.length > 0 ? [instances.slice()] : [];
  const buckets: CityInstance[][] = Array.from({ length: count }, () => []);
  for (const inst of instances) buckets[chunkIndexOf(inst, center, count)].push(inst);
  return buckets.filter((b) => b.length > 0);
}

// ── Plan → renderable entries (rule 10: null/empty ⇒ skip) ──────────────────

export interface CityEntry {
  key: CityPieceKey;
  spec: ModelSpec;
  instances: CityInstance[];
}

/**
 * The renderable (key, spec, instances) triples: registry `null` and empty
 * piece lists are skipped — never a hole, never a crash. Canonical
 * CITY_PIECE_KEYS order, so output is deterministic.
 */
export function renderableEntries(
  plan: CityPlan,
  registry: Record<CityPieceKey, ModelSpec | null>,
): CityEntry[] {
  const out: CityEntry[] = [];
  for (const key of CITY_PIECE_KEYS) {
    const spec = registry[key];
    const instances = plan.pieces[key];
    if (!spec || instances.length === 0) continue;
    out.push({ key, spec, instances });
  }
  return out;
}

// ── Instance matrices ────────────────────────────────────────────────────────

const _pos = new THREE.Vector3();
const _quat = new THREE.Quaternion();
const _scl = new THREE.Vector3();
const _Y = new THREE.Vector3(0, 1, 0);

/**
 * The world matrix for one city instance under a ModelSpec — the instanced
 * equivalent of Model.tsx's inner group: translate (x, yOffset, z) ∘ rotate
 * (spec.rotation + inst.rotY) ∘ uniform scale (spec.scale × inst.s).
 */
export function composeInstanceMatrix(
  inst: CityInstance,
  spec: ModelSpec,
  target: THREE.Matrix4 = new THREE.Matrix4(),
): THREE.Matrix4 {
  _pos.set(inst.x, spec.yOffset, inst.z);
  _quat.setFromAxisAngle(_Y, (spec.rotation ?? 0) + inst.rotY);
  const s = spec.scale * (inst.s ?? 1);
  _scl.set(s, s, s);
  return target.compose(_pos, _quat, _scl);
}

/** EM-157: set dressing is invisible to the pointer — raycast does nothing. */
export function noopRaycast(): void {}

/**
 * Write a chunk's instance matrices into its InstancedMesh: one matrix per
 * instance, ONE needsUpdate, StaticDrawUsage (the city never animates), a
 * correct per-chunk bounding sphere (so frustumCulled works on real bounds),
 * and the EM-157 no-op raycast.
 */
export function setupCityMesh(
  mesh: THREE.InstancedMesh,
  instances: readonly CityInstance[],
  spec: ModelSpec,
): void {
  mesh.raycast = noopRaycast;
  mesh.instanceMatrix.setUsage(THREE.StaticDrawUsage);
  const m = new THREE.Matrix4();
  for (let i = 0; i < instances.length; i++) {
    mesh.setMatrixAt(i, composeInstanceMatrix(instances[i], spec, m));
  }
  mesh.instanceMatrix.needsUpdate = true;
  mesh.computeBoundingSphere();
}

// ── GLB scene → instanceable (geometry, material) parts ─────────────────────

export interface CityPart {
  geometry: THREE.BufferGeometry;
  material: THREE.Material | THREE.Material[];
}

/** Parts are derived once per cached GLB scene and shared by every chunk. */
const PARTS_CACHE = new WeakMap<THREE.Object3D, CityPart[]>();

/**
 * Normalize + merge same-material geometries (transforms already baked).
 * Attribute sets are intersected and indexing made consistent first; any
 * mismatch mergeGeometries can't handle falls back to null (caller keeps
 * per-part meshes — correctness over draw-call count).
 */
function tryMergeGeometries(geoms: THREE.BufferGeometry[]): THREE.BufferGeometry | null {
  const nameSets = geoms.map((g) => new Set<string>(Object.keys(g.attributes)));
  const first: string[] = nameSets.length > 0 ? Array.from(nameSets[0]) : [];
  const common = new Set<string>(first.filter((n) => nameSets.every((s) => s.has(n))));
  for (const g of geoms) {
    for (const name of Object.keys(g.attributes)) {
      if (!common.has(name)) g.deleteAttribute(name);
    }
    g.morphAttributes = {};
  }
  const anyNonIndexed = geoms.some((g) => !g.index);
  const normalized = anyNonIndexed ? geoms.map((g) => (g.index ? g.toNonIndexed() : g)) : geoms;
  try {
    return (mergeGeometries(normalized, false) as THREE.BufferGeometry | null) ?? null;
  } catch {
    return null;
  }
}

/**
 * Flatten a toon-converted GLB scene into instanceable parts. Sub-mesh node
 * transforms are baked into (cloned) geometries; sub-meshes SHARING a material
 * merge into one geometry (one draw call per chunk for the 5–6-node Kenney
 * cars). The single-mesh/identity case reuses the cached geometry untouched.
 * Materials are always the shared toon instances — never cloned.
 */
export function extractInstanceParts(scene: THREE.Object3D): CityPart[] {
  const cached = PARTS_CACHE.get(scene);
  if (cached) return cached;

  scene.updateMatrixWorld(true);
  const rootInv = new THREE.Matrix4().copy(scene.matrixWorld).invert();

  interface Sub {
    geometry: THREE.BufferGeometry;
    local: THREE.Matrix4;
  }
  const byMaterial = new Map<THREE.Material | THREE.Material[], Sub[]>();
  scene.traverse((obj) => {
    const mesh = obj as THREE.Mesh;
    if (!mesh.isMesh || !mesh.geometry || !mesh.material) return;
    const local = new THREE.Matrix4().multiplyMatrices(rootInv, mesh.matrixWorld);
    const subs = byMaterial.get(mesh.material) ?? [];
    subs.push({ geometry: mesh.geometry, local });
    byMaterial.set(mesh.material, subs);
  });

  const identity = new THREE.Matrix4();
  const parts: CityPart[] = [];
  for (const [material, subs] of byMaterial) {
    if (subs.length === 1 && subs[0].local.equals(identity)) {
      parts.push({ geometry: subs[0].geometry, material });
      continue;
    }
    const baked = subs.map((s) => s.geometry.clone().applyMatrix4(s.local));
    if (baked.length === 1) {
      parts.push({ geometry: baked[0], material });
      continue;
    }
    const merged = tryMergeGeometries(baked);
    if (merged) parts.push({ geometry: merged, material });
    else for (const g of baked) parts.push({ geometry: g, material });
  }

  PARTS_CACHE.set(scene, parts);
  return parts;
}

// ── Plan memo (content-keyed — see file header) ──────────────────────────────

/** Everything the plan depends on: seed + each place's position/kind/district
 *  (deriveCoreRadius reads computeTownLayout, which reads kind + district). */
export function citySignature(
  places: readonly Place[],
  citySeed: number | null | undefined,
): string {
  const head = citySeed ?? 'default';
  const body = places
    .map((p) => `${p.id}:${p.x}:${p.y}:${p.kind}:${p.district ?? ''}`)
    .join(',');
  return `${head}|${body}`;
}

/**
 * The deterministic city plan + town centroid, cached on citySignature so
 * per-tick world-object churn never rebuilds instance buffers.
 */
export function useCityPlan(
  places: Place[],
  citySeed: number | null | undefined,
): { plan: CityPlan; center: { x: number; z: number } } {
  const sig = useMemo(() => citySignature(places, citySeed), [places, citySeed]);
  const ref = useRef<{
    sig: string;
    plan: CityPlan;
    center: { x: number; z: number };
  } | null>(null);
  if (!ref.current || ref.current.sig !== sig) {
    ref.current = {
      sig,
      plan: computeCityPlan({ places, city_seed: citySeed }),
      center: townCenter(places),
    };
  }
  return ref.current;
}

// ── Components ───────────────────────────────────────────────────────────────

/** One InstancedMesh: a (piece key × chunk × material part). */
function CityChunkMesh({
  name,
  part,
  spec,
  instances,
  castShadow,
}: {
  name: string;
  part: CityPart;
  spec: ModelSpec;
  instances: CityInstance[];
  castShadow: boolean;
}) {
  const ref = useRef<THREE.InstancedMesh>(null);

  useLayoutEffect(() => {
    const mesh = ref.current;
    // jsdom smoke tests mount this tree without the R3F reconciler, so the
    // ref can be an HTMLUnknownElement — matrices only apply to the real mesh.
    if (!mesh || typeof mesh.setMatrixAt !== 'function') return;
    setupCityMesh(mesh, instances, spec);
    // No cleanup, by design: R3F itself calls InstancedMesh.dispose() when
    // this mesh unmounts (plan change ⇒ args reconstruct), and three's
    // dispose frees ONLY the per-mesh instance buffers — R3F never disposes
    // args-passed geometry/material, so the shared GLB caches stay intact.
    // Do NOT pass dispose={null}: R3F applies it as a plain prop, overwriting
    // the dispose METHOD with null. And do not dispose manually here: a
    // throwing cleanup in StrictMode's mount→cleanup→remount cycle trips
    // every ModelBoundary on a fresh page load (Gate 2 finding 1).
  }, [instances, spec]);

  return (
    <instancedMesh
      name={name}
      ref={ref}
      args={[part.geometry, part.material as THREE.Material, instances.length]}
      frustumCulled
      castShadow={castShadow}
      receiveShadow
    />
  );
}

/** All chunks for one piece key (suspends while its GLB streams). */
function CityPiece({
  pieceKey,
  spec,
  instances,
  center,
}: {
  pieceKey: CityPieceKey;
  spec: ModelSpec;
  instances: CityInstance[];
  center: { x: number; z: number };
}) {
  // Throws to the ModelBoundary on load failure (rule 10: skip, never crash).
  const { scene } = useToonGLTF(spec.url);
  const parts = useMemo(() => extractInstanceParts(scene), [scene]);
  const chunks = useMemo(() => chunkInstances(instances, center), [instances, center]);
  // Road tiles are ground-flush slabs — casting is pure shadow-map waste.
  const castShadow = !pieceKey.startsWith('road_');
  return (
    <>
      {chunks.map((chunk, ci) =>
        parts.map((part, pi) => (
          <CityChunkMesh
            key={`${pieceKey}:${ci}:${pi}`}
            name={`city-${pieceKey}-${ci}-${pi}`}
            part={part}
            spec={spec}
            instances={chunk}
            castShadow={castShadow}
          />
        )),
      )}
    </>
  );
}

/**
 * The generated city ring. Mounted by CozyWorld inside the canvas, OUTSIDE
 * the historic-core groups — the Wave C town renders exactly as before
 * (EM-156); this is pure set dressing around it (EM-157).
 */
export function CityScape({ world }: { world: Pick<WorldState, 'places' | 'city_seed'> }) {
  const { plan, center } = useCityPlan(world.places, world.city_seed);
  const entries = useMemo(() => renderableEntries(plan, CITY_MODEL_REGISTRY), [plan]);
  return (
    <group name="cityscape">
      {entries.map(({ key, spec, instances }) => (
        // One boundary per piece key: a failed GLB silently skips THAT piece
        // (fallback null — absence, not a hole) and never unmounts the canvas.
        <ModelBoundary key={key} fallback={null}>
          <CityPiece pieceKey={key} spec={spec} instances={instances} center={center} />
        </ModelBoundary>
      ))}
    </group>
  );
}
