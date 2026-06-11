/**
 * cityLayout — deterministic CityGenerator for Wave D1.5 (EM-153 v3),
 * re-aimed by EM-174: "if it's a building, it should have a purpose."
 *
 * The sim lives ON the grid (contracts/wave-d1.5.md), and every building in
 * the world is REAL: either a landmark (a sim place's anchor block) or an
 * actual W7 Building entity standing on a lot. The generator emits NO
 * decorative zone buildings — the Wave D1.6 founding-stock/growth-budget
 * fill is retired (EM-174). What it does emit:
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
 *     blocks carry zone 'landmark' — the place anchor lives there, plus
 *     `CityPlan.realLots`: up to REAL_LOTS_PER_LANDMARK street-front lots
 *     INSIDE the block (never on roads) reserved for the sim's actual W7
 *     Building entities. Farm-district landmark blocks are the city's parks
 *     and get a tree fill.
 *   • PLATTED LOTS (EM-174): every non-park, non-landmark block carries
 *     LOTS_PER_BLOCK platted lots from day 0 — grouped per block in
 *     `CityPlan.blockLots` (the city-wide overflow pool real W7 buildings
 *     claim once their place's landmark block fills, assignBuildingLots) and
 *     flattened in `CityPlan.emptyLots` (rendered by CityScape as subtle
 *     procedural pavement pads; no new GLB keys — the 23-key vocabulary
 *     stays frozen because landmark anchors and the W7 operationalVariant
 *     mapping still draw on the city GLBs).
 *   • PARK BLOCKS (trees + benches, no buildings): farm-district landmarks
 *     plus exactly one seeded park among the generated blocks. A generated
 *     block takes the zone of the nearest landmark's district (core→civic
 *     flavor, market→commercial, civic→civic, residential→residential,
 *     farm→park/greenbelt) — zones still tint the ground.
 *   • SIDEWALK PROPS (lamp/bench/hydrant/bin) sit at block corners along the
 *     road edges; `car_a..c` park sparsely on the curbs of the adjacent road
 *     tiles.
 *
 * Determinism is a contract invariant (EM-155): the plan is a pure function
 * of (places, city_seed) — same snapshot + same seed ⇒ byte-identical plan
 * across live/replay/fork. There is NO Math.random, NO Date, NO module
 * state — all variety derives from the repo's seeded-hash idiom
 * (worldSpace.hashUnit) keyed on (seed, gridX, gridZ, purpose), with
 * seed = world.city_seed ?? 1337. W7 buildings never shape the PLAN; they
 * only CLAIM lots through assignBuildingLots (itself a pure, input-order-
 * independent function).
 *
 * Rotation convention (shared with the registry models): rotY = 0 means the
 * piece's "front"/primary connection faces +Z; angles follow
 * Math.atan2(dx, dz), so +X ⇒ π/2, −Z ⇒ π, −X ⇒ −π/2.
 */

import type { Place } from '../../types';
import { placeToWorld, hashUnit, slotLayout } from './worldSpace';

// ── Frozen vocabulary (Wave D1 contract — the registry imports this) ────────

export type CityPieceKey =
  // roads (~2.6-unit tiles after scaling)
  | 'road_straight' | 'road_corner' | 'road_tee' | 'road_cross' | 'road_end'
  // zoned buildings — registry vocabulary ONLY since EM-174: PLACE_MODELS
  // anchors and the W7 operationalVariant mapping reuse these GLBs, but the
  // generator emits ZERO instances of them (no decorative fill, ever)
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

/** One generated block's platted lots (EM-174 overflow pool entry). */
export interface CityBlockLots { cx: number; cz: number; lots: CityInstance[] }

/** What computeCityPlan derives the city from (a WorldState slice). The
 *  plan is keyed on (places, city_seed) ONLY — EM-174 retired the Wave D1.6
 *  growth inputs (`buildings`/`day`); W7 buildings claim lots through
 *  assignBuildingLots instead of shaping the plan. */
export interface CityWorld {
  places: Place[];
  city_seed?: number | null;
}

export interface CityPlan {
  pieces: Record<CityPieceKey, CityInstance[]>;
  blocks: CityBlock[];
  /** Wave D1.5: place id → its landmark block's snapped anchor center. */
  landmarks: Record<string, { x: number; z: number }>;
  /**
   * Wave D1.6: place id → up to REAL_LOTS_PER_LANDMARK street-front lots
   * INSIDE the place's landmark block (never on roads), reserved for the
   * sim's actual W7 Building entities (assignBuildingLots). Only the place
   * that CLAIMED the block carries an entry.
   */
  realLots: Record<string, CityInstance[]>;
  /**
   * EM-174: every generated (non-park, non-landmark) block's platted lots,
   * grouped per block in deterministic block loop order — the city-wide
   * overflow pool assignBuildingLots draws on when a place's landmark block
   * is full.
   */
  blockLots: CityBlockLots[];
  /**
   * The same platted lots, flattened — rendered by CityScape as subtle
   * procedural pavement pads. A real W7 building that claims a platted lot
   * stands ON its pad (the pad reads as the building's foundation).
   */
  emptyLots: CityInstance[];
  /** Outer half-size of the city (Chebyshev from the world origin). */
  extent: number;
}

// ── Tunables ─────────────────────────────────────────────────────────────────

/** Seed when the snapshot predates W15 / omits city_seed (matches backend). */
export const DEFAULT_CITY_SEED = 1337;

/** Hard cap on total emitted instances (contract budget — holds trivially). */
export const MAX_CITY_INSTANCES = 3000;

/** Platted lots per generated block: 2 per side × 4 sides — ALL of them
 *  render as pavement pads (EM-174: no generated buildings, ever); real W7
 *  buildings may claim them as overflow lots. */
export const LOTS_PER_BLOCK = 8;

/** Street-front lots reserved for real W7 buildings inside a landmark block. */
export const REAL_LOTS_PER_LANDMARK = 6;

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

const CAR_KEYS: readonly CityPieceKey[] = ['car_a', 'car_b', 'car_c'];
/** EM-176: parked cars off until EM-169 (W17) makes vehicles playable. */
export const CARS_ENABLED = false;

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

/**
 * The LOTS_PER_BLOCK platted lots of a generated block: 2 per side × 4
 * sides, inset behind the sidewalk, facing the street. Position jitter is
 * keyed ONLY on (seed, block, lot index) — the EM-155 seeded-hash idiom —
 * so the plat never moves between snapshots. EM-174: these are PADS, never
 * generated buildings; real W7 buildings may claim them as overflow lots.
 */
function blockPads(seed: number, bx: number, bz: number): CityInstance[] {
  const wx = bx * BLOCK_PITCH;
  const wz = bz * BLOCK_PITCH;
  const perSide = LOTS_PER_BLOCK / 4; // 2
  const lots: CityInstance[] = [];
  for (let i = 0; i < LOTS_PER_BLOCK; i++) {
    const side = SIDES[i % 4];
    const slot = Math.floor(i / 4); // 0 | 1
    const tx = -side.dz; // street tangent
    const tz = side.dx;
    const inset = BLOCK_HALF - 1.5; // lot row, behind the sidewalk
    const lateral =
      ((slot + 0.5) / perSide - 0.5) * (BLOCK_TILES * TILE - TILE) +
      (h(seed, `lot-jitter-${i}`, bx, bz) - 0.5) * 0.5;
    lots.push({
      x: wx + side.dx * inset + tx * lateral,
      z: wz + side.dz * inset + tz * lateral,
      rotY: dirRot(side.dx, side.dz), // face the street
    });
  }
  return lots;
}

/**
 * The street-front lots a landmark block reserves for the sim's REAL W7
 * buildings: up to REAL_LOTS_PER_LANDMARK positions inside the block (inset
 * behind the sidewalk like generated lots — never on roads), cycling sides
 * N/E/S/W so consecutive buildings spread around the place anchor.
 */
function computeRealLots(seed: number, bx: number, bz: number): CityInstance[] {
  const wx = bx * BLOCK_PITCH;
  const wz = bz * BLOCK_PITCH;
  const out: CityInstance[] = [];
  for (let i = 0; i < REAL_LOTS_PER_LANDMARK; i++) {
    const side = SIDES[i % 4];
    const slot = Math.floor(i / 4); // 0 | 1
    const tx = -side.dz;
    const tz = side.dx;
    const inset = BLOCK_HALF - 1.6;
    // ±1.5 (tighter than generated lots) keeps corner-adjacent lots on
    // neighboring sides ≥ ~2.5u apart while clearing the anchor (≥ 3.8u).
    const lateral =
      (slot === 0 ? -1.5 : 1.5) + (h(seed, `real-lot-${i}`, bx, bz) - 0.5) * 0.3;
    out.push({
      x: wx + side.dx * inset + tx * lateral,
      z: wz + side.dz * inset + tz * lateral,
      rotY: dirRot(side.dx, side.dz), // face the street
    });
  }
  return out;
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
    // EM-176 — DISABLED until W17: static cars read as a distraction before
    // EM-169's ambient traffic gives vehicles a purpose. The keys, registry
    // entries, GLBs, and license rows all stay; flip CARS_ENABLED to bring
    // them back (EM-169 replaces this with moving traffic on the road graph).
    if (CARS_ENABLED && h(seed, `car-${s}`, bx, bz) < CAR_SIDE_CHANCE) {
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
 * origin-centered); the seed drives lot jitter, the guaranteed generated
 * park, curb life, and park fills. EM-174: the plan is a pure function of
 * (places, city_seed) — every generated-block lot is a platted pad; ONLY
 * landmark anchors and real W7 buildings put structures in the world.
 */
export function computeCityPlan(world: CityWorld): CityPlan {
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

  // Pass 2 — emit blocks + their contents in deterministic loop order, and
  // collect the generated blocks' platted lots (all pads, EM-174).
  const blocks: CityBlock[] = [];
  const realLots: Record<string, CityInstance[]> = {};
  const blockLots: CityBlockLots[] = [];
  for (const b of infos) {
    blocks.push({ cx: b.bx * BLOCK_PITCH, cz: b.bz * BLOCK_PITCH, zone: b.zone });

    if (b.zone === 'landmark') {
      // The place anchor + its real-building lots own the interior — no
      // generated buildings here. Farm-district landmarks are the parks.
      if (b.landmark) realLots[b.landmark.id] = computeRealLots(seed, b.bx, b.bz);
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
      blockLots.push({
        cx: b.bx * BLOCK_PITCH,
        cz: b.bz * BLOCK_PITCH,
        lots: blockPads(seed, b.bx, b.bz),
      });
    }

    // Curb life dresses every block's road edges (landmark blocks included —
    // sidewalk props on their road edges are explicitly fine).
    emitCurbLife(seed, b.bx, b.bz, pieces);
  }

  // EM-174: ALL platted lots render as pavement pads from day 0 — the
  // generator emits zero zone buildings; only landmark anchors and real W7
  // buildings ever stand in the world.
  const emptyLots: CityInstance[] = blockLots.flatMap((b) => b.lots);

  return {
    pieces,
    blocks,
    landmarks,
    realLots,
    blockLots,
    emptyLots,
    extent: Math.abs(tileCenter(TILE_MIN)) + TILE / 2, // 33.8: outer ring road edge
  };
}

// ── EM-174: real W7 buildings claim real lots, city-wide ─────────────────────

/**
 * Deterministic world position for every W7 Building:
 *
 *   1. LANDMARK BLOCK FIRST: a building's index among its place's buildings
 *      (stable sort by id) picks that place's realLots entry.
 *   2. NEIGHBORHOOD OVERFLOW (EM-181 spread sooner): past REAL_LOTS_PER_LANDMARK,
 *      overflow claims PLATTED lots city-wide, ROUND-ROBIN across blocks — lot
 *      index 0 of every block (nearest block to the place's landmark anchor —
 *      or the raw place center for ids with no landmark — first, ties → plan
 *      block order), then lot index 1, and so on. A place that outgrows its
 *      block fans out one lot per surrounding block instead of packing the
 *      single nearest block full before spilling. Each building takes the first
 *      unclaimed candidate; claims are GLOBAL across places, resolved in
 *      sorted-location order, so the result is independent of building input
 *      order.
 *   3. SLOT-RING LAST RESORT: the EM-131 slotLayout ring around the anchor /
 *      place center, only when every platted lot in the city is claimed.
 *
 * Pure function of (plan, buildings, centers) — same world ⇒ same spots
 * every frame, reload and input order. A building on a platted lot stands
 * ON its pavement pad (the pad reads as the building's foundation).
 */
export function assignBuildingLots(
  plan: Pick<CityPlan, 'realLots' | 'landmarks' | 'blockLots'>,
  buildings: ReadonlyArray<{ id: string; location: string }>,
  placeCenters: ReadonlyMap<string, { x: number; z: number }>,
): Map<string, { x: number; z: number }> {
  const out = new Map<string, { x: number; z: number }>();
  const byPlace = new Map<string, string[]>();
  for (const b of buildings) {
    const ids = byPlace.get(b.location) ?? [];
    ids.push(b.id);
    byPlace.set(b.location, ids);
  }
  // One global claim ledger over the platted-lot pool (overflow lots are
  // shared city-wide); sorted-location order makes contention deterministic.
  const claimed = plan.blockLots.map((b) => b.lots.map(() => false));
  for (const loc of [...byPlace.keys()].sort()) {
    const ids = [...(byPlace.get(loc) ?? [])].sort();
    // Locations are data-driven strings — own-property guard the lookups.
    const lotsForPlace = Object.prototype.hasOwnProperty.call(plan.realLots, loc)
      ? plan.realLots[loc]
      : [];
    const n = Math.min(ids.length, lotsForPlace.length);
    for (let i = 0; i < n; i++) {
      out.set(ids[i], { x: lotsForPlace[i].x, z: lotsForPlace[i].z });
    }
    const overflow = ids.slice(n);
    if (overflow.length === 0) continue;

    const anchor = Object.prototype.hasOwnProperty.call(plan.landmarks, loc)
      ? plan.landmarks[loc]
      : undefined;
    const center = anchor ?? placeCenters.get(loc) ?? { x: 0, z: 0 };

    // Nearest-block order: block-center distance to the place (ties → plan
    // block order). The candidate WALK then round-robins across these blocks
    // by lot index (EM-181 spread sooner): lot 0 of every block nearest-first,
    // then lot 1, and so on — a place that outgrows its landmark block fans out
    // one lot per surrounding block instead of packing the nearest block full
    // before spilling. Deterministic + input-order independent.
    const blockOrder = plan.blockLots
      .map((b, bi) => ({ bi, d: Math.hypot(b.cx - center.x, b.cz - center.z) }))
      .sort((a, b) => a.d - b.d || a.bi - b.bi);
    const maxLots = plan.blockLots.reduce((m, b) => Math.max(m, b.lots.length), 0);
    const candidates: Array<{ bi: number; li: number }> = [];
    for (let li = 0; li < maxLots; li++) {
      for (const { bi } of blockOrder) {
        if (li < plan.blockLots[bi].lots.length) candidates.push({ bi, li });
      }
    }

    const cityFull: string[] = [];
    let cursor = 0;
    for (const id of overflow) {
      while (cursor < candidates.length && claimed[candidates[cursor].bi][candidates[cursor].li]) {
        cursor++;
      }
      if (cursor < candidates.length) {
        const { bi, li } = candidates[cursor];
        claimed[bi][li] = true;
        const lot = plan.blockLots[bi].lots[li];
        out.set(id, { x: lot.x, z: lot.z });
      } else {
        cityFull.push(id); // every platted lot in the city is claimed
      }
    }
    if (cityFull.length > 0) {
      for (const [id, pt] of slotLayout(center, cityFull)) out.set(id, pt);
    }
  }
  return out;
}
