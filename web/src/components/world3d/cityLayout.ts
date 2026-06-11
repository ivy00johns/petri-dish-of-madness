/**
 * cityLayout — deterministic CityGenerator for Wave D1.5 (EM-153 v2).
 *
 * The sim lives ON the grid now (contracts/wave-d1.5.md) — Emergence-World
 * style: compact, dense, every block developed. The Wave D1 "ring around the
 * historic core" is gone, and with it the deriveCoreRadius/townCenter
 * machinery — the city IS the world.
 *
 *   • FROZEN GRID: 5×5 blocks, block pitch BLOCK_PITCH (13.0) world units —
 *     4 developable tiles + 1 road tile per pitch (TILE = 2.6) — centered on
 *     the world origin. Block centers sit at −26, −13, 0, 13, 26 on each
 *     axis; roads run between all blocks plus an outer ring road. City span
 *     ≈ 66u (= worldSpace.SIZE).
 *   • LANDMARK BLOCKS: every place claims the block nearest its
 *     placeToWorld position (the shipped town's yaml coords land within 5mm
 *     of block centers; snapping tolerance is asserted < 1.0u in tests).
 *     `CityPlan.landmarks` maps place id → snapped anchor center. Landmark
 *     blocks carry zone 'landmark' and receive NO generated buildings — the
 *     place anchor + its building-slot ring live there. Farm-district
 *     landmark blocks are the city's parks and get a tree fill.
 *   • GENERATED BLOCKS are fully developed by zone — every lot gets a
 *     building (an empty road-framed block is a contract violation) — except
 *     park blocks (trees + benches, no buildings). A generated block takes
 *     the zone of the nearest landmark's district (core→civic flavor,
 *     market→commercial, civic→civic, residential→residential,
 *     farm→park/greenbelt); exactly one seeded park is guaranteed among the
 *     generated blocks.
 *   • SIDEWALK PROPS (lamp/bench/hydrant/bin) sit at block corners along the
 *     road edges; `car_a..c` park sparsely on the curbs of the adjacent road
 *     tiles.
 *
 * Determinism is a contract invariant (EM-155): same snapshot + same seed ⇒
 * byte-identical plan across live/replay/fork. There is NO Math.random, NO
 * Date, NO module state — all variety derives from the repo's seeded-hash
 * idiom (worldSpace.hashUnit) keyed on (seed, gridX, gridZ, purpose), with
 * seed = world.city_seed ?? 1337.
 *
 * Rotation convention (shared with the registry models): rotY = 0 means the
 * piece's "front"/primary connection faces +Z; angles follow
 * Math.atan2(dx, dz), so +X ⇒ π/2, −Z ⇒ π, −X ⇒ −π/2.
 */

import type { Place } from '../../types';
import { placeToWorld, hashUnit } from './worldSpace';

// ── Frozen vocabulary (Wave D1 contract — the registry imports this) ────────

export type CityPieceKey =
  // roads (~2.6-unit tiles after scaling)
  | 'road_straight' | 'road_corner' | 'road_tee' | 'road_cross' | 'road_end'
  // zoned buildings (commercial / residential / industrial / civic)
  | 'com_a' | 'com_b' | 'com_c'
  | 'res_a' | 'res_b' | 'res_c'
  | 'ind_a' | 'ind_b'
  | 'civic_a'
  // street furniture + greenery
  | 'lamp' | 'bench' | 'hydrant' | 'bin' | 'fence' | 'tree_city'
  // vehicles (parked; ambient traffic is EM-169 / W17)
  | 'car_a' | 'car_b' | 'car_c';

/** Every CityPieceKey, in canonical emission order (plan key order is fixed). */
export const CITY_PIECE_KEYS: readonly CityPieceKey[] = [
  'road_straight', 'road_corner', 'road_tee', 'road_cross', 'road_end',
  'com_a', 'com_b', 'com_c',
  'res_a', 'res_b', 'res_c',
  'ind_a', 'ind_b',
  'civic_a',
  'lamp', 'bench', 'hydrant', 'bin', 'fence', 'tree_city',
  'car_a', 'car_b', 'car_c',
];

/** Wave D1.5: blocks[].zone gains 'landmark' (a place's reserved block). */
export const CITY_ZONES = [
  'commercial', 'residential', 'industrial', 'civic', 'park', 'landmark',
] as const;
export type CityZone = (typeof CITY_ZONES)[number];

// ── Contract API types ───────────────────────────────────────────────────────

/** Road tile pitch, world units (frozen by the Wave D1 contract). */
export const TILE = 2.6;

/** Block pitch: 4 developable tiles + 1 road tile (frozen, Wave D1.5). */
export const BLOCK_PITCH = 13.0;

/** Blocks per axis (the frozen 5×5 grid). */
export const GRID_BLOCKS = 5;

/** Developable tiles per block edge. */
export const BLOCK_TILES = 4;

/** Half-extent of a block's developable footprint (5.2 world units). */
export const BLOCK_HALF = (BLOCK_TILES * TILE) / 2;

export interface CityInstance { x: number; z: number; rotY: number; s?: number }

export interface CityBlock { cx: number; cz: number; zone: CityZone }

export interface CityPlan {
  pieces: Record<CityPieceKey, CityInstance[]>;
  blocks: CityBlock[];
  /** Wave D1.5: place id → its landmark block's snapped anchor center. */
  landmarks: Record<string, { x: number; z: number }>;
  /** Outer half-size of the city (Chebyshev from the world origin). */
  extent: number;
}

// ── Tunables ─────────────────────────────────────────────────────────────────

/** Seed when the snapshot predates W15 / omits city_seed (matches backend). */
export const DEFAULT_CITY_SEED = 1337;

/** Hard cap on total emitted instances (contract budget — holds trivially). */
export const MAX_CITY_INSTANCES = 3000;

/** Lots per developed block: 2 per side × 4 sides, ALL developed. */
export const LOTS_PER_BLOCK = 8;

/** Curb-life densities (per block side). */
const PROP_SIDE_CHANCE = 0.7;
const CAR_SIDE_CHANCE = 0.22;

/** Park fill (generated park blocks + farm-district landmark blocks). */
const PARK_TREES_MIN = 6;
const PARK_TREES_SPAN = 4; // 6 + [0..3]
const LANDMARK_PARK_TREES_MIN = 4;
const LANDMARK_PARK_TREES_SPAN = 3; // 4 + [0..2]
/** Trees keep this clear of a park landmark's anchor (the place marker). */
const PARK_ANCHOR_CLEAR = 2.8;
/** Tree-to-tree spacing inside a park block. */
const PARK_TREE_SPACING = 1.9;

// ── Geometry helpers ─────────────────────────────────────────────────────────

const HALF_PI = Math.PI / 2;

interface Dir { dx: number; dz: number; bit: number }

/** Block sides / road neighbors: N(−Z), E(+X), S(+Z), W(−X). */
const SIDES: readonly Dir[] = [
  { dx: 0, dz: -1, bit: 1 },
  { dx: 1, dz: 0, bit: 2 },
  { dx: 0, dz: 1, bit: 4 },
  { dx: -1, dz: 0, bit: 8 },
];

/** rotY that faces a piece's front along (dx, dz) — see the file header. */
function dirRot(dx: number, dz: number): number {
  return Math.atan2(dx, dz);
}

/** Road-piece rotation tables, keyed by the 4-bit neighbor mask (N|E|S|W). */
const END_ROT: Readonly<Record<number, number>> = { 4: 0, 2: HALF_PI, 1: Math.PI, 8: -HALF_PI };
const STRAIGHT_ROT: Readonly<Record<number, number>> = { 5: 0, 10: HALF_PI };
const CORNER_ROT: Readonly<Record<number, number>> = { 6: 0, 3: HALF_PI, 9: Math.PI, 12: -HALF_PI };
const TEE_ROT: Readonly<Record<number, number>> = { 14: 0, 7: HALF_PI, 11: Math.PI, 13: -HALF_PI };

// ── The frozen grid ──────────────────────────────────────────────────────────

/** Max |block index| (blocks run bx, bz ∈ −2..2). */
const B_MAX = (GRID_BLOCKS - 1) / 2;

/**
 * Tile-index space: tile i has its center at (i + 0.5) · TILE, i ∈ −13..12.
 * Road tiles sit on the lines between blocks plus the outer ring — indices
 * where ((i − 2) mod 5) === 0, i.e. {−13, −8, −3, 2, 7, 12} (world −32.5,
 * −19.5, −6.5, 6.5, 19.5, 32.5).
 */
const TILE_MIN = -13;
const TILE_MAX = 12;

function tileCenter(i: number): number {
  return (i + 0.5) * TILE;
}

function isRoadIndex(i: number): boolean {
  return ((((i - 2) % 5) + 5) % 5) === 0;
}

function inGrid(i: number, j: number): boolean {
  return i >= TILE_MIN && i <= TILE_MAX && j >= TILE_MIN && j <= TILE_MAX;
}

function isRoadTile(i: number, j: number): boolean {
  return inGrid(i, j) && (isRoadIndex(i) || isRoadIndex(j));
}

/**
 * Snap a world position to the nearest block center of the frozen 5×5 grid
 * (clamped to the grid). Pure; used for landmark anchors here and for the
 * park scatter in foliageLayout.
 */
export function snapToBlockCenter(x: number, z: number): { x: number; z: number } {
  const bx = Math.max(-B_MAX, Math.min(B_MAX, Math.round(x / BLOCK_PITCH)));
  const bz = Math.max(-B_MAX, Math.min(B_MAX, Math.round(z / BLOCK_PITCH)));
  return { x: bx * BLOCK_PITCH, z: bz * BLOCK_PITCH };
}

// ── Landmarks ────────────────────────────────────────────────────────────────

/**
 * Place id → snapped landmark anchor (the block center the place claims).
 * Deterministic in place CONTENT, not input order.
 */
export function computeLandmarks(places: Place[]): Record<string, { x: number; z: number }> {
  const out: Record<string, { x: number; z: number }> = {};
  for (const p of [...places].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))) {
    const w = placeToWorld(p);
    out[p.id] = snapToBlockCenter(w.x, w.z);
  }
  return out;
}

// ── Zoning ───────────────────────────────────────────────────────────────────

/** District → generated-block zone (the frozen plan's table). */
const DISTRICT_ZONE: Readonly<Record<string, CityZone>> = {
  core: 'civic',
  market: 'commercial',
  civic: 'civic',
  residential: 'residential',
  farm: 'park',
};

/** Kind fallback for district-less snapshots (legacy towns / procgen). */
const KIND_ZONE: Readonly<Record<string, CityZone>> = {
  social: 'civic',
  work: 'commercial',
  governance: 'civic',
  home: 'residential',
  wild: 'park',
};

function zoneForPlace(p: Place): CityZone {
  if (p.district && DISTRICT_ZONE[p.district] !== undefined) return DISTRICT_ZONE[p.district];
  return KIND_ZONE[p.kind] ?? 'residential';
}

/** Zone-matched building variants. */
const ZONE_BUILDINGS: Readonly<
  Record<Exclude<CityZone, 'park' | 'landmark'>, readonly CityPieceKey[]>
> = {
  commercial: ['com_a', 'com_b', 'com_c'],
  residential: ['res_a', 'res_b', 'res_c'],
  industrial: ['ind_a', 'ind_b'],
  civic: ['civic_a'],
};

const CAR_KEYS: readonly CityPieceKey[] = ['car_a', 'car_b', 'car_c'];

// ── Seeded hash (the repo idiom, keyed on seed/gridX/gridZ/purpose) ──────────

function h(seed: number, purpose: string, gridX = 0, gridZ = 0): number {
  return hashUnit(`city:${seed}:${gridX}:${gridZ}:${purpose}`);
}

// ── Emission ─────────────────────────────────────────────────────────────────

function emptyPieces(): Record<CityPieceKey, CityInstance[]> {
  const out = {} as Record<CityPieceKey, CityInstance[]>;
  for (const k of CITY_PIECE_KEYS) out[k] = [];
  return out;
}

/** Roads: classify every road tile from its actual road neighbors. */
function emitRoads(pieces: Record<CityPieceKey, CityInstance[]>): void {
  for (let j = TILE_MIN; j <= TILE_MAX; j++) {
    for (let i = TILE_MIN; i <= TILE_MAX; i++) {
      if (!isRoadTile(i, j)) continue;
      let mask = 0;
      for (const d of SIDES) {
        if (isRoadTile(i + d.dx, j + d.dz)) mask |= d.bit;
      }
      if (mask === 0) continue;
      const x = tileCenter(i);
      const z = tileCenter(j);
      if (mask === 15) pieces.road_cross.push({ x, z, rotY: 0 });
      else if (mask in TEE_ROT) pieces.road_tee.push({ x, z, rotY: TEE_ROT[mask] });
      else if (mask in STRAIGHT_ROT) pieces.road_straight.push({ x, z, rotY: STRAIGHT_ROT[mask] });
      else if (mask in CORNER_ROT) pieces.road_corner.push({ x, z, rotY: CORNER_ROT[mask] });
      else pieces.road_end.push({ x, z, rotY: END_ROT[mask] });
    }
  }
}

/** Tree fill for a park block (seeded scatter, anchor-clear, self-spaced). */
function emitParkTrees(
  seed: number,
  bx: number,
  bz: number,
  count: number,
  clearAnchor: boolean,
  pieces: Record<CityPieceKey, CityInstance[]>,
): void {
  const wx = bx * BLOCK_PITCH;
  const wz = bz * BLOCK_PITCH;
  const spread = BLOCK_HALF - 1.0;
  const placed: Array<{ x: number; z: number }> = [];
  let attempts = 0;
  let i = 0;
  while (placed.length < count && attempts < count * 10) {
    attempts++;
    const tag = `park-tree-${i++}`;
    const ox = (h(seed, `${tag}-x`, bx, bz) - 0.5) * 2 * spread;
    const oz = (h(seed, `${tag}-z`, bx, bz) - 0.5) * 2 * spread;
    if (clearAnchor && Math.hypot(ox, oz) < PARK_ANCHOR_CLEAR) continue;
    if (placed.some((t) => Math.hypot(t.x - ox, t.z - oz) < PARK_TREE_SPACING)) continue;
    placed.push({ x: ox, z: oz });
    pieces.tree_city.push({
      x: wx + ox,
      z: wz + oz,
      rotY: h(seed, `${tag}-r`, bx, bz) * Math.PI * 2,
      s: 0.85 + h(seed, `${tag}-s`, bx, bz) * 0.4,
    });
  }
}

/** Benches facing inward on a generated park block. */
function emitParkBenches(
  seed: number,
  bx: number,
  bz: number,
  pieces: Record<CityPieceKey, CityInstance[]>,
): void {
  const wx = bx * BLOCK_PITCH;
  const wz = bz * BLOCK_PITCH;
  const count = 2 + (h(seed, 'park-benches', bx, bz) < 0.5 ? 0 : 1);
  for (let i = 0; i < count; i++) {
    const side = SIDES[(i + Math.floor(h(seed, 'park-bench-side', bx, bz) * 4)) % 4];
    const tx = -side.dz;
    const tz = side.dx;
    const inset = BLOCK_HALF - 1.4;
    const lateral = (h(seed, `park-bench-at-${i}`, bx, bz) - 0.5) * (BLOCK_HALF * 1.1);
    pieces.bench.push({
      x: wx + side.dx * inset + tx * lateral,
      z: wz + side.dz * inset + tz * lateral,
      // face the park's interior (back to the street)
      rotY: dirRot(-side.dx, -side.dz),
    });
  }
}

/** Every lot of a developed block gets a building — zero empty lots. */
function emitLots(
  seed: number,
  bx: number,
  bz: number,
  zone: Exclude<CityZone, 'park' | 'landmark'>,
  pieces: Record<CityPieceKey, CityInstance[]>,
): void {
  const wx = bx * BLOCK_PITCH;
  const wz = bz * BLOCK_PITCH;
  const variants = ZONE_BUILDINGS[zone];
  const perSide = LOTS_PER_BLOCK / 4; // 2
  for (let i = 0; i < LOTS_PER_BLOCK; i++) {
    const side = SIDES[i % 4];
    const slot = Math.floor(i / 4); // 0 | 1
    const tx = -side.dz; // street tangent
    const tz = side.dx;
    const inset = BLOCK_HALF - 1.5; // building row, behind the sidewalk
    const lateral =
      ((slot + 0.5) / perSide - 0.5) * (BLOCK_TILES * TILE - TILE) +
      (h(seed, `lot-jitter-${i}`, bx, bz) - 0.5) * 0.5;
    const key =
      variants[Math.floor(h(seed, `lot-key-${i}`, bx, bz) * variants.length) % variants.length];
    pieces[key].push({
      x: wx + side.dx * inset + tx * lateral,
      z: wz + side.dz * inset + tz * lateral,
      rotY: dirRot(side.dx, side.dz), // face the street
      s: 0.92 + h(seed, `lot-scale-${i}`, bx, bz) * 0.16,
    });
  }
}

/** Sidewalk props at block corners + sparse parked cars on the curbs. */
function emitCurbLife(
  seed: number,
  bx: number,
  bz: number,
  pieces: Record<CityPieceKey, CityInstance[]>,
): void {
  const wx = bx * BLOCK_PITCH;
  const wz = bz * BLOCK_PITCH;
  for (let s = 0; s < 4; s++) {
    const side = SIDES[s];
    const tx = -side.dz;
    const tz = side.dx;

    // Sidewalk props at block corners along the road edge.
    if (h(seed, `prop-${s}`, bx, bz) < PROP_SIDE_CHANCE) {
      const r = h(seed, `prop-kind-${s}`, bx, bz);
      const key: CityPieceKey = r < 0.4 ? 'lamp' : r < 0.6 ? 'bin' : r < 0.8 ? 'hydrant' : 'bench';
      const cornerSign = h(seed, `prop-corner-${s}`, bx, bz) < 0.5 ? -1 : 1;
      const inset = BLOCK_HALF - 0.35;
      const lateral = cornerSign * (BLOCK_HALF - 0.55);
      pieces[key].push({
        x: wx + side.dx * inset + tx * lateral,
        z: wz + side.dz * inset + tz * lateral,
        rotY: dirRot(side.dx, side.dz),
      });
    }

    // Sparse parked cars: on the adjacent road tile, pulled to this curb.
    if (h(seed, `car-${s}`, bx, bz) < CAR_SIDE_CHANCE) {
      const roadDist = BLOCK_PITCH / 2; // road centerline off the block center
      const curbPull = TILE * 0.32;
      const lateral = (h(seed, `car-at-${s}`, bx, bz) - 0.5) * (BLOCK_TILES * TILE - TILE);
      const key =
        CAR_KEYS[Math.floor(h(seed, `car-key-${s}`, bx, bz) * CAR_KEYS.length) % CAR_KEYS.length];
      const flip = h(seed, `car-flip-${s}`, bx, bz) < 0.5 ? 0 : Math.PI;
      pieces[key].push({
        x: wx + side.dx * (roadDist - curbPull) + tx * lateral,
        z: wz + side.dz * (roadDist - curbPull) + tz * lateral,
        rotY: dirRot(side.dx, side.dz) + HALF_PI + flip, // along the road
      });
    }
  }
}

// ── The generator ────────────────────────────────────────────────────────────

/**
 * Compute the deterministic city plan for a world snapshot.
 *
 * seed = world.city_seed ?? 1337. The grid itself is frozen (5×5, pitch 13,
 * origin-centered); the seed drives lot variety, the guaranteed generated
 * park, curb life, and park fills.
 */
export function computeCityPlan(world: {
  places: Place[];
  city_seed?: number | null;
}): CityPlan {
  const places = world.places ?? [];
  const seed = world.city_seed ?? DEFAULT_CITY_SEED;
  const pieces = emptyPieces();

  emitRoads(pieces);

  const landmarks = computeLandmarks(places);

  // Landmark occupancy + the zone each landmark projects (sorted-id order so
  // ties resolve deterministically regardless of input order).
  const sortedPlaces = [...places].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const landmarkAt = new Map<string, Place>(); // "bx,bz" → claiming place (first by id)
  for (const p of sortedPlaces) {
    const a = landmarks[p.id];
    const key = `${Math.round(a.x / BLOCK_PITCH)},${Math.round(a.z / BLOCK_PITCH)}`;
    if (!landmarkAt.has(key)) landmarkAt.set(key, p);
  }

  /** Nearest landmark place by exact world distance (ties → smallest id). */
  function nearestPlace(wx: number, wz: number): Place | null {
    let best: Place | null = null;
    let bestD = Infinity;
    for (const p of sortedPlaces) {
      const w = placeToWorld(p);
      const d = Math.hypot(w.x - wx, w.z - wz);
      if (d < bestD - 1e-9) {
        bestD = d;
        best = p;
      }
    }
    return best;
  }

  // Pass 1 — classify all 25 blocks.
  interface BlockInfo {
    bx: number;
    bz: number;
    zone: CityZone;
    landmark: Place | null;
  }
  const infos: BlockInfo[] = [];
  for (let bz = -B_MAX; bz <= B_MAX; bz++) {
    for (let bx = -B_MAX; bx <= B_MAX; bx++) {
      const claimed = landmarkAt.get(`${bx},${bz}`) ?? null;
      if (claimed) {
        infos.push({ bx, bz, zone: 'landmark', landmark: claimed });
      } else {
        const near = nearestPlace(bx * BLOCK_PITCH, bz * BLOCK_PITCH);
        infos.push({ bx, bz, zone: near ? zoneForPlace(near) : 'residential', landmark: null });
      }
    }
  }

  // Park guarantee: exactly one seeded park among the generated blocks when
  // district adjacency produced none — the block with the lowest seeded roll
  // converts (loop order breaks exact ties).
  const generated = infos.filter((b) => b.zone !== 'landmark');
  if (generated.length > 0 && !generated.some((b) => b.zone === 'park')) {
    let best = generated[0];
    let bestRoll = h(seed, 'zone-park', best.bx, best.bz);
    for (const b of generated) {
      const roll = h(seed, 'zone-park', b.bx, b.bz);
      if (roll < bestRoll) {
        bestRoll = roll;
        best = b;
      }
    }
    best.zone = 'park';
  }

  // Pass 2 — emit blocks + their contents in deterministic loop order.
  const blocks: CityBlock[] = [];
  for (const b of infos) {
    blocks.push({ cx: b.bx * BLOCK_PITCH, cz: b.bz * BLOCK_PITCH, zone: b.zone });

    if (b.zone === 'landmark') {
      // The place anchor + its slot ring own the interior — no generated
      // buildings here. Farm-district landmarks are the city's parks.
      if (b.landmark && (b.landmark.district === 'farm' || (!b.landmark.district && b.landmark.kind === 'wild'))) {
        const trees =
          LANDMARK_PARK_TREES_MIN +
          Math.floor(h(seed, 'landmark-park-trees', b.bx, b.bz) * LANDMARK_PARK_TREES_SPAN);
        emitParkTrees(seed, b.bx, b.bz, trees, true, pieces);
      }
    } else if (b.zone === 'park') {
      const trees =
        PARK_TREES_MIN + Math.floor(h(seed, 'park-trees', b.bx, b.bz) * PARK_TREES_SPAN);
      emitParkTrees(seed, b.bx, b.bz, trees, false, pieces);
      emitParkBenches(seed, b.bx, b.bz, pieces);
    } else {
      emitLots(seed, b.bx, b.bz, b.zone, pieces);
    }

    // Curb life dresses every block's road edges (landmark blocks included —
    // sidewalk props on their road edges are explicitly fine).
    emitCurbLife(seed, b.bx, b.bz, pieces);
  }

  return {
    pieces,
    blocks,
    landmarks,
    extent: Math.abs(tileCenter(TILE_MIN)) + TILE / 2, // 33.8: outer ring road edge
  };
}
