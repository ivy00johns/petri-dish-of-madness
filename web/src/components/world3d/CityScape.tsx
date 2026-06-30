/**
 * CityScape — the instanced render path for THE city (EM-154, re-aimed by
 * Wave D1.5 and EM-174): the compact EW-style grid the sim lives on — roads,
 * platted-lot paving pads, parks, street props and parked cars in Kenney
 * set dressing. EM-174: the generator emits ZERO decorative buildings —
 * every building in the world is a landmark anchor (Building.tsx) or a real
 * W7 Building entity (Structure.tsx). Pure renderer: ALL layout policy
 * lives in cityLayout.
 *
 * Pipeline: computeCityPlan (deterministic — seed = world.city_seed ?? 1337)
 * × CITY_MODEL_REGISTRY → one raw THREE.InstancedMesh per
 * (piece key × spatial chunk × material part).
 *
 *   • V2 PLAN (Wave D1.5 seam): CityPlan carries `landmarks` (place id →
 *     snapped block-center anchor) and blocks may be zoned 'landmark'. Both
 *     are LAYOUT metadata — landmark blocks emit no generated buildings (the
 *     place anchors themselves render through Building.tsx/PLACE_MODELS), so
 *     this renderer consumes them implicitly through `pieces`: nothing extra
 *     to draw, and the instanced path needs no policy of its own.
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
 *     around the grid center) by count, so frustum culling can drop the
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
import type { Place, Neighborhood } from '../../types';
import {
  CITY_PIECE_KEYS,
  computeCityPlan,
  DEFAULT_CITY_SEED,
  TILE,
  type CityInstance,
  type CityPieceKey,
  type CityPlan,
  type CityWorld,
} from './cityLayout';
import type { BuildZone, ZoneRule } from './cityFaces';
import { CITY_MODEL_REGISTRY } from './assets/cityModels';
import type { ModelSpec } from './assets/models';
import { useToonGLTF } from './assets/Model';
import { ModelBoundary } from './ModelBoundary';
import { RoadMesh } from './RoadMesh';
import { toonMaterial } from './toon';

// ── Chunking (pure, exported for tests) ──────────────────────────────────────

/** Piece keys with more instances than this split into 4 quadrant chunks. */
export const CHUNK_SPLIT_4 = 96;
/** …and beyond this, into 8 octant chunks (road_straight dominates). */
export const CHUNK_SPLIT_8 = 360;

/** The chunking origin: the D1.5 grid is centered on the world origin
 *  (cityLayout's frozen plan), so spatial buckets pivot there. */
export const GRID_CENTER: { x: number; z: number } = { x: 0, z: 0 };

/** How many spatial chunks a piece key with `n` instances gets (1 | 4 | 8). */
export function chunkCount(n: number): number {
  return n > CHUNK_SPLIT_8 ? 8 : n > CHUNK_SPLIT_4 ? 4 : 1;
}

/**
 * Which chunk an instance belongs to: quadrant (count 4) or angular octant
 * (count 8) around the grid center. Pure + deterministic, so the same plan
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
 *  (cityLayout zones generated blocks from the nearest landmark's district).
 *  EM-174/EM-155: the plan is keyed on (places, city_seed) ONLY — buildings
 *  and day no longer shape it (they only claim lots, assignBuildingLots), so
 *  snapshot polling never churns the memo while the town stands still. */
export function citySignature(
  places: readonly Place[] | null | undefined,
  citySeed: number | null | undefined,
  neighborhoods?: readonly Neighborhood[] | null,
  cityGraph?: {
    nodes: readonly unknown[];
    edges: readonly { id?: string; car_policy?: string }[];
    car_policy?: string;
    zone_rules?: readonly { zone_id?: string; hint?: string; density_cap?: number | null }[];
  } | null,
): string {
  const head = citySeed ?? 'default';
  const body = (places ?? [])
    .map((p) => `${p.id}:${p.x}:${p.y}:${p.kind}:${p.district ?? ''}:${p.neighborhood_id ?? ''}:${p.zone_kind ?? ''}`)
    .join(',');
  // EM-123: district maturity shapes extra street life — fold each grown
  // district's id:tier in (sorted, so polling order never churns the memo) so
  // the plan rebuilds when a district levels up. ONLY tier>1 contributes (tier 1
  // adds nothing to the plan), so an all-tier-1 or absent set ⇒ '' ⇒ the plan is
  // byte-identical to pre-EM-123 and the memo never churns on a fresh world.
  const tiers = (neighborhoods ?? [])
    .filter((n) => (n.tier ?? 1) > 1)
    .map((n) => `${n.id}:${n.tier}`)
    .sort()
    .join(',');
  // EM-243 (S2): fold the graph's node/edge COUNTS (not the object) so a built
  // road re-renders live while idle polls (identical counts) never churn the memo.
  const graph = cityGraph ? `${cityGraph.nodes.length}:${cityGraph.edges.length}` : '';
  // EM-244 (S3a): car_policy mutates at CONSTANT node/edge counts (city default or a
  // single edge), so the counts above miss it — fold the city policy + every
  // non-'inherit' edge policy (sorted, so poll order never churns). All-default
  // (city 'cars', edges 'inherit') ⇒ 'cars:' ⇒ stable; only a ratified ban-cars /
  // street vote changes it, re-rendering the tint + parked-car removal live.
  const policy = cityGraph
    ? `${cityGraph.car_policy ?? 'cars'}:` +
      cityGraph.edges
        .filter((e) => e.car_policy && e.car_policy !== 'inherit')
        .map((e) => `${e.id}=${e.car_policy}`)
        .sort()
        .join(',')
    : '';
  // EM-265 (SB): fold a RULES HASH so a ratified set_zone_rule re-renders LIVE
  // (the thrice-shipped content-key bug — law §0.5). Read off the SAME 4th param
  // (zone_rules ride ON the CityGraph), so the arity stays 4. Map each rule to
  // `zone_id:hint:density_cap`, SORT (poll order never churns), join. No rules ⇒
  // '' ⇒ a stable suffix ⇒ byte-identical no-churn (law §0.1).
  const rules =
    cityGraph && Array.isArray(cityGraph.zone_rules)
      ? cityGraph.zone_rules
          .map((r) => `${r.zone_id ?? ''}:${r.hint ?? ''}:${r.density_cap ?? ''}`)
          .sort()
          .join(',')
      : '';
  return `${head}|${body}|${tiers}|${graph}|${policy}|${rules}`;
}

/**
 * The deterministic city plan + chunking center (GRID_CENTER — the D1.5 grid
 * is origin-centered by the frozen plan), cached on citySignature so
 * per-tick world-object churn never rebuilds instance buffers.
 */
export function useCityPlan(
  world: CityWorld,
): { plan: CityPlan; center: { x: number; z: number } } {
  const { places = [], city_seed: citySeed, neighborhoods, city_graph } = world;
  // EM-243 (S2) / EM-244 (S3a): the graph MUTATES — agents build_road (changes
  // node/edge counts) AND ratify set_car_policy (changes car_policy at CONSTANT
  // counts). A count-only memo dep caught build_road but missed car_policy (the
  // S3a HIGH). citySignature now folds BOTH counts and car_policy; we compute it
  // every render (a cheap string concat over ~tens of nodes, run per snapshot-poll
  // — NOT per frame) and let the ref-cache below gate the expensive computeCityPlan
  // rebuild on the sig string. So a built road OR a ratified car-policy renders
  // live, while idle polls (identical sig) never rebuild instance buffers.
  const sig = citySignature(places, citySeed, neighborhoods, city_graph);
  const ref = useRef<{
    sig: string;
    plan: CityPlan;
    center: { x: number; z: number };
  } | null>(null);
  if (!ref.current || ref.current.sig !== sig) {
    ref.current = {
      sig,
      // EM-264 (SA): the graph-lots branch is gated by GRAPH_LOTS_ENABLED
      // (default OFF ⇒ { graphLots: false } ⇒ the untouched grid path, byte-
      // identical). citySignature already folds node/edge counts + car_policy,
      // so zone lots (a pure function of the graph's edges) re-derive live on a
      // graph mutation — no new memo dep needed.
      plan: computeCityPlan(
        { places, city_seed: citySeed, neighborhoods, city_graph },
        { graphLots: GRAPH_LOTS_ENABLED },
      ),
      center: GRID_CENTER,
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

// ── EM-174: platted lots (procedural pads — no GLB key) ──────────────────────

/** Pad tint — the existing warm paving stone (Structure's step/portico). */
export const PAD_COLOR = '#cfc4ad';

/** Thin paving pad: 2.3×2.3, ground-flush (top face baked to y = 0.05). */
const PAD_GEOMETRY = new THREE.BoxGeometry(2.3, 0.05, 2.3).translate(0, 0.025, 0);

/** Identity spec for the pad instances (procedural — no GLB, no url). */
const PAD_SPEC: ModelSpec = { url: '', scale: 1, yOffset: 0 };

/**
 * The platted lots, instanced like every other piece (chunked, raycast-dead,
 * StaticDrawUsage). Subtle by construction: thin flat geometry in an
 * existing palette tint — reads "platted city", never competes with the
 * landmarks. A real W7 building that claims a lot renders ON TOP of its pad
 * (the pad reads as the building's foundation — pads are never removed by
 * claims, keeping the plan independent of the building list). Purely
 * procedural ⇒ no ModelBoundary needed.
 */
function EmptyLotPads({
  instances,
  center,
}: {
  instances: CityInstance[];
  center: { x: number; z: number };
}) {
  const chunks = useMemo(() => chunkInstances(instances, center), [instances, center]);
  const part = useMemo<CityPart>(
    () => ({ geometry: PAD_GEOMETRY, material: toonMaterial(PAD_COLOR) }),
    [],
  );
  return (
    <>
      {chunks.map((chunk, ci) => (
        <CityChunkMesh
          key={`pad:${ci}`}
          name={`city-pad-${ci}`}
          part={part}
          spec={PAD_SPEC}
          instances={chunk}
          castShadow={false}
        />
      ))}
    </>
  );
}

// ── EM-244 (S3a): pedestrian road surface tint (procedural overlay) ──────────

/** Pedestrian-road tint — a cool flagstone wash distinct from the warm paving
 *  pads (PAD_COLOR), so a pedestrianized street reads as "sidewalk, no cars". */
export const PEDESTRIAN_ROAD_COLOR = '#9fb0a6';

/** Full-tile flagstone overlay (TILE×TILE), sitting just above the road slab
 *  so it tints the surface without z-fighting the road tile beneath it. */
const PEDESTRIAN_GEOMETRY = new THREE.BoxGeometry(TILE, 0.06, TILE).translate(0, 0.06, 0);

/**
 * The pedestrian road tiles, instanced like EmptyLotPads (chunked, raycast-
 * dead, StaticDrawUsage) in a single tinted toon material — the EM-244 (S3a)
 * surface variant that marks where a `set_car_policy` vote banned cars. Empty
 * for the default/cars/no-graph plan, so it adds nothing to the baseline city.
 * Purely procedural ⇒ no ModelBoundary needed.
 */
function PedestrianRoadPads({
  instances,
  center,
}: {
  instances: CityInstance[];
  center: { x: number; z: number };
}) {
  const chunks = useMemo(() => chunkInstances(instances, center), [instances, center]);
  const part = useMemo<CityPart>(
    () => ({ geometry: PEDESTRIAN_GEOMETRY, material: toonMaterial(PEDESTRIAN_ROAD_COLOR) }),
    [],
  );
  return (
    <>
      {chunks.map((chunk, ci) => (
        <CityChunkMesh
          key={`ped:${ci}`}
          name={`city-pedestrian-${ci}`}
          part={part}
          spec={PAD_SPEC}
          instances={chunk}
          castShadow={false}
        />
      ))}
    </>
  );
}

// ── EM-265 (SB): agent-authored zone-rule tint overlay (advisory) ────────────

/**
 * Hint → ground-zone tint. Maps the frozen SB hint vocabulary
 * (`residential | market | civic | open`) onto the EXISTING district-tint
 * vocabulary (townLayout.DISTRICT_TINTS: residential/market/civic grass tones;
 * `open` reuses the farm/greenbelt tone). WebGL colors live OUTSIDE the CSS
 * token system (the RoadMesh / EmptyLotPads precedent), so these hex literals
 * are the established renderer pattern. A ratified rule tints its block by hint.
 */
export const ZONE_HINT_TINTS: Record<ZoneRule['hint'], string> = {
  residential: '#95bf67', // DISTRICT_TINTS.residential
  market: '#a6bd55', // DISTRICT_TINTS.market
  civic: '#85b164', // DISTRICT_TINTS.civic
  open: '#a9c352', // DISTRICT_TINTS.farm — open / greenbelt
};

/** A renderable tint for one ruled zone — derived from the zone's face. */
export interface ZoneTintEntry {
  id: string;
  x: number;
  z: number;
  radius: number;
  color: string;
  hint: ZoneRule['hint'];
}

/**
 * The tint overlays for the zones that carry a ratified rule. Pure +
 * deterministic (canonical zone order, last-rule-wins per zone). A zone with
 * NO rule contributes nothing — so the no-rules path yields [] ⇒ ZERO tint
 * meshes ⇒ byte-identical to pre-SB (law §0.1). Absent/empty zones ⇒ [] (the
 * graph-lots flag is OFF ⇒ plan.zones undefined on the default path).
 */
export function zoneRuleTints(zones: readonly BuildZone[] | undefined): ZoneTintEntry[] {
  if (!Array.isArray(zones)) return [];
  const out: ZoneTintEntry[] = [];
  for (const zn of zones) {
    // `rules` is always ZoneRule[] by the type; the length guard is defensive.
    const rules: ZoneRule[] = zn?.rules ?? [];
    if (rules.length === 0) continue;
    const rule = rules[rules.length - 1]; // one rule per zone (last wins)
    const color = Object.prototype.hasOwnProperty.call(ZONE_HINT_TINTS, rule.hint)
      ? ZONE_HINT_TINTS[rule.hint]
      : null;
    if (!color) continue; // unknown hint ⇒ no tint (defensive, never a hole)
    // Disc radius from the face footprint (√(area/π)); clamped so a sliver face
    // still reads. Advisory tint — approximate is fine (mirrors Ground discs).
    const radius = Math.max(1.0, Math.sqrt(Math.abs(zn.face.area) / Math.PI));
    out.push({ id: zn.id, x: zn.face.centroid.x, z: zn.face.centroid.z, radius, color, hint: rule.hint });
  }
  return out;
}

/** Tint opacity for the zone-rule wash (subtle, like the Ground district discs). */
const ZONE_TINT_OPACITY = 0.3;

/**
 * EM-265 (SB): the advisory zone-rule tints — one translucent toon disc per
 * ruled block, hinted by color, sitting just above the grass (below the road
 * tiles / lot pads). Reuses the Ground.tsx district-disc vocabulary so a
 * ratified rule reads as a soft zone wash, never a paint-bucket. EMPTY when no
 * rule is ratified ⇒ adds nothing to the baseline city (law §0.1). An OPTIONAL
 * sparse label is deferred (EM-188 discipline) — the tint is the SB signal.
 * Purely procedural ⇒ no ModelBoundary needed.
 */
export function ZoneRuleTints({ zones }: { zones: readonly BuildZone[] }) {
  const tints = useMemo(() => zoneRuleTints(zones), [zones]);
  return (
    <>
      {tints.map((t, i) => (
        <mesh
          key={`zone-tint:${t.id}`}
          name={`city-zone-tint-${i}`}
          rotation={[-Math.PI / 2, 0, 0]}
          position={[t.x, 0.009, t.z]}
          material={toonMaterial(t.color, {
            transparent: true,
            opacity: ZONE_TINT_OPACITY,
            depthWrite: false,
            polygonOffset: true,
          })}
        >
          <circleGeometry args={[t.radius, 36]} />
        </mesh>
      ))}
    </>
  );
}

// ── EM-247 (S5a): procedural road-mesh flag (default OFF) ────────────────────

/**
 * EM-247 (S5a): when true, the road network renders as procedural geometry
 * (<RoadMesh>, any-angle ribbons from the CityGraph) instead of the EM-239/243
 * road TILES. Default **false** — the tile path is the byte-identical default +
 * fallback, and flipping this on is a deliberate, reviewed change pending the
 * human visual sign-off (atlas / lane markings / crosswalks / LOD are the
 * spec's deferred "budget real iteration"). With the flag off the road render
 * is the existing tile path UNCHANGED, so every EM-239/243/244/246 golden +
 * byte-identical assertion still holds. Do NOT retire the tile path here.
 */
export const ROAD_MESH_ENABLED = true; // EM-247 visual sign-off (TEMP — revert if not signed off)

// ── EM-264 (SA): graph-derived buildable-zone lots (default OFF) ─────────────

/**
 * EM-264 (SA): when true, computeCityPlan derives buildable blocks / platted
 * lots from the road graph's bounded planar FACES (any topology: pentagon /
 * radial) instead of the fixed 5×5 grid plat. Default **false** — the grid plat
 * is the EM-155 byte-identical default + fallback, and flipping this on is a
 * deliberate, reviewed change pending the human visual sign-off (confirm
 * buildings land inside the road-enclosed blocks, no grid-on-pentagon). With
 * the flag off, computeCityPlan runs the untouched grid path UNCHANGED, so every
 * EM-155/174/239/243/244/246 golden + byte-identical assertion still holds —
 * exactly the ROAD_MESH_ENABLED (EM-247) deferred-sign-off pattern. No new
 * render component: zone lots flow through the existing blockLots/emptyLots/
 * blocks render path.
 */
export const GRAPH_LOTS_ENABLED = false;

/** A road-tile piece key (the EM-239/243 instanced road slabs). */
function isRoadPieceKey(key: CityPieceKey): boolean {
  return key.startsWith('road_');
}

/**
 * THE city (Wave D1.5 + EM-174). Mounted by CozyWorld inside the canvas —
 * every road tile, platted-lot pad, park tree, prop and parked car of the
 * compact grid, as pure non-interactive set dressing (EM-157). ZERO
 * generated buildings: place anchors, agent-built structures, villagers and
 * critters render through their own components on top of this.
 */
export function CityScape({ world }: { world: CityWorld }) {
  const { plan, center } = useCityPlan(world);
  const entries = useMemo(() => renderableEntries(plan, CITY_MODEL_REGISTRY), [plan]);
  // EM-247 (S5a): branch ONLY the road rendering. With the flag OFF (default)
  // drawEntries === entries, so the road TILES render through the same
  // CityPiece path as every other piece — byte-identical to pre-EM-247. With it
  // ON, the road-tile pieces drop out and <RoadMesh> renders the procedural
  // roads instead; every non-road piece (buildings/props/lots/landmarks) is
  // untouched in both modes.
  const drawEntries = ROAD_MESH_ENABLED
    ? entries.filter((e) => !isRoadPieceKey(e.key))
    : entries;
  return (
    <group name="cityscape">
      {drawEntries.map(({ key, spec, instances }) => (
        // One boundary per piece key: a failed GLB silently skips THAT piece
        // (fallback null — absence, not a hole) and never unmounts the canvas.
        <ModelBoundary key={key} fallback={null}>
          <CityPiece pieceKey={key} spec={spec} instances={instances} center={center} />
        </ModelBoundary>
      ))}
      {ROAD_MESH_ENABLED && (
        <RoadMesh graph={world.city_graph} seed={world.city_seed ?? DEFAULT_CITY_SEED} />
      )}
      {plan.emptyLots.length > 0 && (
        <EmptyLotPads instances={plan.emptyLots} center={center} />
      )}
      {plan.pedestrianTiles.length > 0 && (
        <PedestrianRoadPads instances={plan.pedestrianTiles} center={center} />
      )}
      {/* EM-265 (SB): advisory zone-rule tints. Gated on GRAPH_LOTS_ENABLED +
          real zones (zones only exist on the graph-lots path) AND on a zone
          actually carrying a rule (zoneRuleTints filters) — so the default
          flag-OFF path renders NOTHING here ⇒ byte-identical (law §0.1). */}
      {GRAPH_LOTS_ENABLED && plan.zones && plan.zones.length > 0 && (
        <ZoneRuleTints zones={plan.zones} />
      )}
    </group>
  );
}
