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
 *   • STREET NAMES (EM-188): `CityPlan.streets` names every road centerline
 *     of the frozen grid (12 streets) from a seeded two-part name bank —
 *     pure data, seeded ONLY by city_seed via the hashUnit idiom, part of
 *     the EM-155 byte-identical output. Interior avenues carry mid-block
 *     label anchors; the outer ring road stays unlabeled (sparse-label law).
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

import type { Place, Neighborhood, CityGraph, CityGraphEdge } from '../../types';
import { placeToWorld, hashUnit, slotLayout } from './worldSpace';
// EM-264 (SA): graph-derived buildable zones. Runtime imports are the planar-
// face algorithm; BuildZone is a TYPE-only import (the additive CityPlan.zones
// field). cityFaces never runtime-imports cityLayout (contract §1 import-cycle
// rule), so this one-way runtime edge cityLayout → cityFaces → worldSpace is acyclic.
import { planarFaces, buildZonesFromFaces } from './cityFaces';
import type { BuildZone } from './cityFaces';

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

/** EM-188: a ground-plane anchor where a street's name label may render. */
export interface StreetLabelAnchor { x: number; z: number }

/**
 * EM-188: one named street of the frozen grid. The 5×5 plan has exactly 12
 * full-span streets — 6 north–south (constant x) + 6 east–west (constant z)
 * road centerlines. PURE DETERMINISTIC DATA: names derive ONLY from the
 * city seed via the hashUnit idiom (no Math.random, no clock), so they are
 * part of the EM-155 byte-identical plan output.
 */
export interface CityStreet {
  /** Stable id: `${axis}:${roadTileIndex}` (the frozen grid never moves). */
  id: string;
  /** Two-part seeded name from the bank (e.g. "Rowan Lane"). */
  name: string;
  /** 'ns' runs along Z at constant x = `at`; 'ew' runs along X at z = `at`. */
  axis: 'ns' | 'ew';
  /** World coordinate of the road centerline on the cross axis. */
  at: number;
  /** Interior avenue (labeled) vs the outer ring road (kept unlabeled —
   *  the EM-188 "sparse: main lanes, not every alley stub" law). */
  main: boolean;
  /** Mid-block label anchors ON the road (never intersections); [] for the
   *  unlabeled ring. */
  labels: StreetLabelAnchor[];
}

/** One generated block's platted lots (EM-174 overflow pool entry). */
export interface CityBlockLots { cx: number; cz: number; lots: CityInstance[] }

/** What computeCityPlan derives the city from (a WorldState slice). The
 *  plan is keyed on (places, city_seed) ONLY — EM-174 retired the Wave D1.6
 *  growth inputs (`buildings`/`day`); W7 buildings claim lots through
 *  assignBuildingLots instead of shaping the plan. */
export interface CityWorld {
  places: Place[];
  city_seed?: number | null;
  // EM-123 (additive): zoned-district maturity. When present, a block whose
  // nearest place belongs to a tier>1 neighborhood gets deterministic EXTRA
  // street life (park trees + curb props) — a strict superset of the tier-1
  // plan, never filler buildings (EM-174). Absent ⇒ every district is tier 1
  // and the plan is byte-identical to pre-EM-123.
  neighborhoods?: Neighborhood[] | null;
  // EM-239 (S1) — the authoritative road graph. When present, roads + street
  // lines derive from it; when absent, the hardcoded frozen grid is used
  // (fallback discipline). Same byte-identical output for the classic_grid.
  city_graph?: CityGraph | null;
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
  /**
   * EM-188: the named streets of the frozen grid (12 — see CityStreet).
   * Names are seeded ONLY from city_seed (hashUnit idiom) and are part of
   * the EM-155 byte-identical deterministic output.
   */
  streets: CityStreet[];
  /**
   * EM-244 (S3a): road tiles whose covering edge resolves to a 'pedestrian'
   * car policy — rendered by CityScape as a tinted sidewalk surface variant
   * (PEDESTRIAN_ROAD_COLOR). EMPTY for the default (city 'cars') / no-graph
   * plan, so the byte-identical baseline is preserved; a pedestrianization
   * vote (set_car_policy) fills it. Same envelope loop order as emitRoads.
   */
  pedestrianTiles: CityInstance[];
  /** Outer half-size of the city (Chebyshev from the world origin). */
  extent: number;
  /**
   * EM-264 (SA): graph-derived buildable zones — one per bounded planar face
   * of the road graph, each wrapping its face + seeded lot pads + zone hint.
   * ADDITIVE + OPTIONAL: present ONLY on the graph-lots path
   * (`computeCityPlan(world, { graphLots: true })` with a real CityGraph). On
   * the default/grid path the key is absent (undefined), so the EM-155
   * byte-identical baseline is preserved. The source of blockLots/emptyLots/
   * blocks on that path.
   */
  zones?: BuildZone[];
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

/**
 * EM-243 (S2): agents grow roads past the frozen 5×5 into the 9×9 growth
 * envelope — tile-index [−23, 22], mirroring backend `citygraph.MIN_IDX/MAX_IDX`
 * (`MAX_CITY_BLOCKS = 9`). The hardcoded fallback grid stays 5×5; only a real
 * `CityGraph` reaches this far, so grown segments still render (no gap) while the
 * no-graph baseline is byte-identical to before.
 */
const ENV_MIN = -23;
const ENV_MAX = 22;

function tileCenter(i: number): number {
  return (i + 0.5) * TILE;
}

function isRoadIndex(i: number): boolean {
  return ((((i - 2) % 5) + 5) % 5) === 0;
}

function inGrid(i: number, j: number): boolean {
  return i >= TILE_MIN && i <= TILE_MAX && j >= TILE_MIN && j <= TILE_MAX;
}

/** Inside the 9×9 growth envelope (the renderable bound for grown graphs). */
function inEnvelope(i: number, j: number): boolean {
  return i >= ENV_MIN && i <= ENV_MAX && j >= ENV_MIN && j <= ENV_MAX;
}

function isRoadTile(i: number, j: number): boolean {
  return inGrid(i, j) && (isRoadIndex(i) || isRoadIndex(j));
}

/** Recover a tile index from a world coordinate (inverse of tileCenter). */
function tileIndexOf(world: number): number {
  return Math.round(world / TILE - 0.5);
}

/** Build the set of road-tile "i,j" keys from the graph's edges (each edge is
 *  axis-aligned; mark every tile index between its endpoints). For the
 *  classic_grid this reproduces the hardcoded isRoadTile set exactly, so the
 *  plan is byte-identical. S2-ready: partial graphs mark only their segments. */
function roadTileSetFrom(graph: CityGraph | null | undefined): Set<string> {
  const set = new Set<string>();
  // Fall back unless the graph carries REAL node + edge arrays. ModelBoundary
  // (EM-239): a type-corrupt / partially-written graph must degrade to the
  // hardcoded grid, never throw — computeCityPlan runs in CityScape's
  // useCityPlan upstream of the per-piece <ModelBoundary>, so a throw here would
  // crash the whole 3D world instead of falling back.
  if (
    !graph ||
    !Array.isArray(graph.nodes) ||
    !Array.isArray(graph.edges) ||
    !graph.edges.length
  ) {
    // Fallback: today's hardcoded full grid.
    for (let j = TILE_MIN; j <= TILE_MAX; j++)
      for (let i = TILE_MIN; i <= TILE_MAX; i++)
        if (isRoadTile(i, j)) set.add(`${i},${j}`);
    return set;
  }
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  for (const e of graph.edges) {
    const a = nodeById.get(e.a);
    const b = nodeById.get(e.b);
    if (!a || !b) continue;
    const ai = tileIndexOf(a.x), aj = tileIndexOf(a.z), bi = tileIndexOf(b.x), bj = tileIndexOf(b.z);
    if (ai === bi) {
      const lo = Math.min(aj, bj), hi = Math.max(aj, bj);
      for (let j = lo; j <= hi; j++) if (inEnvelope(ai, j)) set.add(`${ai},${j}`);
    } else if (aj === bj) {
      const lo = Math.min(ai, bi), hi = Math.max(ai, bi);
      for (let i = lo; i <= hi; i++) if (inEnvelope(i, aj)) set.add(`${i},${aj}`);
    }
  }
  return set;
}

/**
 * EM-264 (SA): true iff the graph carries a REAL node + edge payload. Mirrors
 * `roadTileSetFrom`'s ModelBoundary guard EXACTLY (not a graph, or nodes/edges
 * aren't arrays, or there are no edges ⇒ false). Gates the graph-lots branch:
 * a stub / corrupt / empty graph falls back to the fixed grid, never the
 * face-derived path — so the byte-identical baseline is safe.
 */
export function hasRealGraph(graph: CityGraph | null | undefined): boolean {
  return (
    !!graph &&
    Array.isArray(graph.nodes) &&
    Array.isArray(graph.edges) &&
    graph.edges.length > 0
  );
}

/** Road-line tile indices on one axis, derived from the graph (for street
 *  naming). Fallback = the hardcoded isRoadIndex lines. ns lines run along Z at
 *  constant x; ew lines run along X at constant z. */
function roadLineIndicesFrom(
  graph: CityGraph | null | undefined,
  axis: 'ns' | 'ew',
): number[] {
  // Same ModelBoundary guard as roadTileSetFrom: a type-corrupt graph (nodes
  // not a real array) degrades to the hardcoded road lines, never throws.
  if (!graph || !Array.isArray(graph.nodes) || !graph.nodes.length) {
    const out: number[] = [];
    for (let i = TILE_MIN; i <= TILE_MAX; i++) if (isRoadIndex(i)) out.push(i);
    return out;
  }
  const s = new Set<number>();
  for (const n of graph.nodes) s.add(tileIndexOf(axis === 'ns' ? n.x : n.z));
  return [...s].sort((p, q) => p - q);
}

// ── EM-244 (S3a): car policy — pedestrian roads lose cars + render tinted ─────

/**
 * The EFFECTIVE car policy of one edge: an 'inherit' edge defers to the graph
 * (city) policy; an explicit edge policy overrides it. Pure. When the graph is
 * absent (no-graph fallback) an 'inherit' edge reads as the default 'cars', so
 * the byte-identical baseline never gains a pedestrian zone.
 */
export function pedestrianPolicyFor(
  graph: Pick<CityGraph, 'car_policy'> | null | undefined,
  edge: CityGraphEdge,
): 'cars' | 'pedestrian' | 'mixed' {
  if (edge.car_policy === 'inherit') return graph?.car_policy ?? 'cars';
  return edge.car_policy;
}

/**
 * The road-tile "i,j" keys covered by an edge whose effective policy resolves
 * to 'pedestrian'. EMPTY for the default (city 'cars' + all-'inherit' edges)
 * graph and for the no-graph fallback — so the EM-239/EM-243 byte-identical
 * plan is preserved; only a real pedestrianization populates it. Mirrors
 * `roadTileSetFrom`'s axis-aligned tile walk + ModelBoundary guard.
 */
function pedestrianTileSetFrom(graph: CityGraph | null | undefined): Set<string> {
  const set = new Set<string>();
  if (
    !graph ||
    !Array.isArray(graph.nodes) ||
    !Array.isArray(graph.edges) ||
    !graph.edges.length
  ) {
    return set; // no graph ⇒ no pedestrian tiles (default path untouched)
  }
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  for (const e of graph.edges) {
    if (pedestrianPolicyFor(graph, e) !== 'pedestrian') continue;
    const a = nodeById.get(e.a);
    const b = nodeById.get(e.b);
    if (!a || !b) continue;
    const ai = tileIndexOf(a.x), aj = tileIndexOf(a.z), bi = tileIndexOf(b.x), bj = tileIndexOf(b.z);
    if (ai === bi) {
      const lo = Math.min(aj, bj), hi = Math.max(aj, bj);
      for (let j = lo; j <= hi; j++) if (inEnvelope(ai, j)) set.add(`${ai},${j}`);
    } else if (aj === bj) {
      const lo = Math.min(ai, bi), hi = Math.max(ai, bi);
      for (let i = lo; i <= hi; i++) if (inEnvelope(i, aj)) set.add(`${i},${aj}`);
    }
  }
  return set;
}

/**
 * The set of CityStreet ids (`${axis}:${tileIndex}`, mirroring computeStreets)
 * whose road line carries at least one edge resolving to 'pedestrian'. Those
 * streets get NO ambient traffic (Traffic.tsx). EMPTY for the default/cars
 * graph and the no-graph fallback ⇒ the fleet is byte-identical; city-scope
 * 'pedestrian' makes every 'inherit' edge pedestrian ⇒ every street ⇒ no cars.
 */
export function pedestrianStreetIds(graph: CityGraph | null | undefined): Set<string> {
  const out = new Set<string>();
  if (
    !graph ||
    !Array.isArray(graph.nodes) ||
    !Array.isArray(graph.edges) ||
    !graph.edges.length
  ) {
    return out;
  }
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  for (const e of graph.edges) {
    if (pedestrianPolicyFor(graph, e) !== 'pedestrian') continue;
    const a = nodeById.get(e.a);
    const b = nodeById.get(e.b);
    if (!a || !b) continue;
    const ai = tileIndexOf(a.x), aj = tileIndexOf(a.z);
    const bi = tileIndexOf(b.x), bj = tileIndexOf(b.z);
    if (ai === bi) out.add(`ns:${ai}`);      // constant x ⇒ a north-south street line
    else if (aj === bj) out.add(`ew:${aj}`); // constant z ⇒ an east-west street line
  }
  return out;
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

/** EM-123: a place's explicit canonical zone_kind → the frontend block zone.
 *  Lets an author re-zone one place inside a mixed district; absent ⇒ the
 *  district mapping below stands (byte-identical to pre-EM-123). */
const ZONE_KIND_CITYZONE: Readonly<Record<string, CityZone>> = {
  residential: 'residential',
  market: 'commercial',
  civic: 'civic',
  industrial: 'commercial',
  farm: 'park',
};

function zoneForPlace(p: Place): CityZone {
  if (p.zone_kind && ZONE_KIND_CITYZONE[p.zone_kind] !== undefined) return ZONE_KIND_CITYZONE[p.zone_kind];
  if (p.district && DISTRICT_ZONE[p.district] !== undefined) return DISTRICT_ZONE[p.district];
  return KIND_ZONE[p.kind] ?? 'residential';
}

// ── EM-123: district maturity → deterministic extra street life ──────────────

/** Extra park trees per tier above 1 (a matured district reads denser/greener;
 *  strictly additive — the first N trees keep their tier-1 positions). */
const TIER_EXTRA_PARK_TREES = 1;
/** Curb-prop chance bump per tier above 1 (more lamps/bins/benches as a
 *  district fills in). Added to PROP_SIDE_CHANCE, clamped below 1 so the
 *  seeded threshold stays a strict superset of the tier-1 props. */
const TIER_PROP_CHANCE_STEP = 0.08;
const TIER_PROP_CHANCE_MAX = 0.95;

/** A place's neighborhood id (`neighborhood_id ?? district`), or '' when the
 *  place is un-districted (procgen). Mirrors the backend grouping key. */
function neighborhoodIdOf(p: Place): string {
  return String(p.neighborhood_id ?? p.district ?? '');
}

/** The maturity tier of a place's neighborhood (1 when un-districted, the
 *  feature is off, or the tier hasn't diverged from the baseline). */
function tierForPlace(p: Place | null, tierById: Map<string, number>): number {
  if (!p) return 1;
  const nid = neighborhoodIdOf(p);
  return (nid && tierById.get(nid)) || 1;
}

const CAR_KEYS: readonly CityPieceKey[] = ['car_a', 'car_b', 'car_c'];
/** EM-176/EM-169: parked cars ON — ambient moving traffic (Traffic.tsx) now
 *  gives vehicles a purpose, so curb-parked cars read as part of the scene
 *  rather than static distraction. Flip to false for the pre-W17 look. */
export const CARS_ENABLED = true;

// ── Seeded hash (the repo idiom, keyed on seed/gridX/gridZ/purpose) ──────────

function h(seed: number, purpose: string, gridX = 0, gridZ = 0): number {
  return hashUnit(`city:${seed}:${gridX}:${gridZ}:${purpose}`);
}

// ── EM-188: street names (pure deterministic plan data) ──────────────────────

/**
 * Two-part street-name bank: stem × suffix. Stems mix trees, trades and
 * founder names (the contract's tree/trade/founder vocabulary). 24 stems ×
 * 4 suffixes = 96 distinct names, comfortably ≥ the grid's 12 streets, so
 * the deterministic walk-forward dedupe below ALWAYS terminates and a full
 * city never repeats a name (proven in cityLayout.test).
 */
export const STREET_NAME_STEMS = [
  // trees
  'Alder', 'Aspen', 'Birch', 'Cedar', 'Elm', 'Hazel',
  'Juniper', 'Linden', 'Maple', 'Oak', 'Rowan', 'Willow',
  // trades
  'Chandler', 'Cooper', 'Mason', 'Miller', 'Potter', 'Tanner', 'Weaver', 'Tinker',
  // founders
  'Ada', 'Bram', 'Vesper', 'Quill',
] as const;

export const STREET_NAME_SUFFIXES = ['Lane', 'Row', 'Way', 'Street'] as const;

/** Size of the full name bank (stem × suffix combinations). */
export const STREET_NAME_BANK_SIZE =
  STREET_NAME_STEMS.length * STREET_NAME_SUFFIXES.length;

/** The k-th bank name — stem-major so adjacent indices change stems first. */
export function streetNameAt(k: number): string {
  const n = STREET_NAME_STEMS.length;
  const i = ((k % STREET_NAME_BANK_SIZE) + STREET_NAME_BANK_SIZE) % STREET_NAME_BANK_SIZE;
  return `${STREET_NAME_STEMS[i % n]} ${STREET_NAME_SUFFIXES[Math.floor(i / n)]}`;
}

/** Cross-axis label anchors: the three odd block-center rows — mid-block road
 *  stretches, never intersections (roads cross at ±6.5/±19.5/±32.5). */
const STREET_LABEL_CROSS = [-2 * BLOCK_PITCH, 0, 2 * BLOCK_PITCH];

/**
 * The 12 named streets of the frozen grid, in canonical order (ns ascending
 * by `at`, then ew ascending). Pure function of the city seed ONLY: each
 * street draws a seeded start index into the name bank (hashUnit idiom,
 * keyed on seed/axis/road tile index) and walks FORWARD to the first unused
 * name — deterministic dedupe, no randomness, no clock. Interior avenues
 * are `main` and carry mid-block label anchors; the outer ring road stays
 * unlabeled (sparse-label law).
 */
export function computeStreets(seed: number, graph?: CityGraph | null): CityStreet[] {
  const used = new Set<number>();
  const out: CityStreet[] = [];
  for (const axis of ['ns', 'ew'] as const) {
    for (const i of roadLineIndicesFrom(graph, axis)) {
      const at = tileCenter(i);
      const main = i !== TILE_MIN && i !== TILE_MAX; // ring road ⇒ not main
      const start = Math.floor(h(seed, `street-name-${axis}`, i) * STREET_NAME_BANK_SIZE);
      let k = start % STREET_NAME_BANK_SIZE;
      while (used.has(k)) k = (k + 1) % STREET_NAME_BANK_SIZE;
      used.add(k);
      out.push({
        id: `${axis}:${i}`,
        name: streetNameAt(k),
        axis,
        at,
        main,
        labels: main
          ? STREET_LABEL_CROSS.map((c) =>
              axis === 'ns' ? { x: at, z: c } : { x: c, z: at },
            )
          : [],
      });
    }
  }
  return out;
}

// ── Emission ─────────────────────────────────────────────────────────────────

function emptyPieces(): Record<CityPieceKey, CityInstance[]> {
  const out = {} as Record<CityPieceKey, CityInstance[]>;
  for (const k of CITY_PIECE_KEYS) out[k] = [];
  return out;
}

/** Roads: classify every road tile from its actual road neighbors. The
 *  road-tile set comes from the CityGraph (EM-239) — for the classic_grid it
 *  reproduces isRoadTile exactly, so the emitted pieces are byte-identical. */
function emitRoads(
  pieces: Record<CityPieceKey, CityInstance[]>,
  roadTiles: Set<string>,
): void {
  const isRoad = (i: number, j: number) => roadTiles.has(`${i},${j}`);
  // EM-243 (S2): iterate the full 9×9 growth envelope so grown segments render.
  // Tiles absent from `roadTiles` are skipped, so the frozen 5×5 fallback and
  // the classic_grid graph stay byte-identical (j-outer/i-inner order unchanged).
  for (let j = ENV_MIN; j <= ENV_MAX; j++) {
    for (let i = ENV_MIN; i <= ENV_MAX; i++) {
      if (!isRoad(i, j)) continue;
      let mask = 0;
      for (const d of SIDES) {
        if (isRoad(i + d.dx, j + d.dz)) mask |= d.bit;
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
  tier = 1,
  pedestrianTiles: Set<string> = new Set(),
): void {
  const wx = bx * BLOCK_PITCH;
  const wz = bz * BLOCK_PITCH;
  // EM-123: a matured district fills its sidewalks in. The bump is ADDED to the
  // tier-1 chance, so the seeded `h(...) < chance` set stays a strict superset
  // (tier 1 ⇒ chance == PROP_SIDE_CHANCE ⇒ byte-identical to pre-EM-123).
  const propChance = Math.min(
    TIER_PROP_CHANCE_MAX,
    PROP_SIDE_CHANCE + Math.max(0, tier - 1) * TIER_PROP_CHANCE_STEP,
  );
  for (let s = 0; s < 4; s++) {
    const side = SIDES[s];
    const tx = -side.dz;
    const tz = side.dx;

    // Sidewalk props at block corners along the road edge.
    if (h(seed, `prop-${s}`, bx, bz) < propChance) {
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
    // EM-244 (S3a): no parked cars curbside a 'pedestrian' road tile (the
    // adjacent road tile is block center ± BLOCK_PITCH/2 on this side). The
    // set is empty on the default/no-graph path, so the gate is a no-op there
    // (h(...) still evaluated ⇒ the seeded fleet stays byte-identical).
    const curbPedestrian = pedestrianTiles.has(
      `${tileIndexOf(wx + side.dx * (BLOCK_PITCH / 2))},${tileIndexOf(wz + side.dz * (BLOCK_PITCH / 2))}`,
    );
    if (CARS_ENABLED && !curbPedestrian && h(seed, `car-${s}`, bx, bz) < CAR_SIDE_CHANCE) {
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
export function computeCityPlan(
  world: CityWorld,
  opts?: { graphLots?: boolean },
): CityPlan {
  const places = world.places ?? [];
  const seed = world.city_seed ?? DEFAULT_CITY_SEED;
  const pieces = emptyPieces();

  // EM-123: neighborhood id → maturity tier (absent/baseline ⇒ tier 1 ⇒ the
  // plan is byte-identical to pre-EM-123). Sorted insert is irrelevant (a Map
  // lookup), but ids are unique so order never affects the result.
  const tierById = new Map<string, number>();
  for (const n of world.neighborhoods ?? []) {
    if (n && n.id) tierById.set(String(n.id), Math.max(1, Math.floor(n.tier ?? 1)));
  }

  // EM-239 (S1) — roads derive from the authoritative CityGraph when present
  // (fallback discipline: absent ⇒ the hardcoded frozen grid). For the
  // classic_grid the derived road-tile set is byte-identical to the old grid.
  const roadTiles = roadTileSetFrom(world.city_graph);
  emitRoads(pieces, roadTiles);

  // EM-244 (S3a): road tiles whose covering edge resolves to 'pedestrian'.
  // Empty unless a vote set a pedestrian policy ⇒ the default plan is unchanged.
  const pedestrianTileKeys = pedestrianTileSetFrom(world.city_graph);

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

  // Buildable blocks + their platted lots. DEFAULT = the frozen 5×5 plat (the
  // grid Pass 1 / Pass 2 below). EM-264 (SA), flag-gated OFF by default: derive
  // them from the road graph's bounded planar FACES instead. roads, landmarks,
  // realLots, streets, pedestrianTiles + extent are SHARED by both paths.
  let blocks: CityBlock[];
  let realLots: Record<string, CityInstance[]>;
  let blockLots: CityBlockLots[];
  let emptyLots: CityInstance[];
  let zones: BuildZone[] | undefined;

  if ((opts?.graphLots ?? false) && hasRealGraph(world.city_graph)) {
    // EM-264 (SA) — the ONLY behavioral change. Buildable blocks/lots come from
    // the bounded planar FACES of the road graph (ANY topology: pentagon /
    // radial), so buildings land inside the road-enclosed blocks instead of the
    // fixed grid. zoneFor reuses the grid path's nearestPlace + zoneForPlace,
    // INJECTED so cityFaces never imports cityLayout (contract §1 cycle rule).
    const zoneFor = (x: number, z: number): CityZone => {
      const p = nearestPlace(x, z);
      return p ? zoneForPlace(p) : 'residential';
    };
    // EM-265 (SB): attach the graph's ratified zone_rules to their matching
    // face by id (absent ⇒ [] ⇒ byte-identical to SA — the no-rules path).
    zones = buildZonesFromFaces(
      planarFaces(world.city_graph),
      seed,
      zoneFor,
      world.city_graph?.zone_rules ?? [],
    );
    blockLots = zones.map((zn) => ({
      cx: zn.face.centroid.x,
      cz: zn.face.centroid.z,
      lots: zn.suggestedLots,
    }));
    emptyLots = blockLots.flatMap((b) => b.lots);
    blocks = zones.map((zn) => ({
      cx: zn.face.centroid.x,
      cz: zn.face.centroid.z,
      zone: zn.zoneHint,
    }));
    // realLots is UNCHANGED + shared: every landmark block still reserves its
    // REAL_LOTS_PER_LANDMARK street-front lots for the sim's W7 buildings (same
    // computeRealLots, same (bz,bx) block-loop order as Pass 2 below), so
    // assignBuildingLots — reused AS-IS — still claims the landmark block first.
    realLots = {};
    for (let bz = -B_MAX; bz <= B_MAX; bz++) {
      for (let bx = -B_MAX; bx <= B_MAX; bx++) {
        const claimed = landmarkAt.get(`${bx},${bz}`);
        if (claimed) realLots[claimed.id] = computeRealLots(seed, bx, bz);
      }
    }
  } else {
  // ── today's fixed-grid Pass 1 / Pass 2 — byte-identical, UNTOUCHED ──────────
  // Pass 1 — classify all 25 blocks.
  interface BlockInfo {
    bx: number;
    bz: number;
    zone: CityZone;
    landmark: Place | null;
    tier: number;   // EM-123: maturity of the block's governing neighborhood
  }
  const infos: BlockInfo[] = [];
  for (let bz = -B_MAX; bz <= B_MAX; bz++) {
    for (let bx = -B_MAX; bx <= B_MAX; bx++) {
      const claimed = landmarkAt.get(`${bx},${bz}`) ?? null;
      if (claimed) {
        infos.push({ bx, bz, zone: 'landmark', landmark: claimed, tier: tierForPlace(claimed, tierById) });
      } else {
        const near = nearestPlace(bx * BLOCK_PITCH, bz * BLOCK_PITCH);
        infos.push({
          bx, bz,
          zone: near ? zoneForPlace(near) : 'residential',
          landmark: null,
          tier: tierForPlace(near, tierById),
        });
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
  blocks = [];
  realLots = {};
  blockLots = [];
  for (const b of infos) {
    blocks.push({ cx: b.bx * BLOCK_PITCH, cz: b.bz * BLOCK_PITCH, zone: b.zone });

    if (b.zone === 'landmark') {
      // The place anchor + its real-building lots own the interior — no
      // generated buildings here. Farm-district landmarks are the parks.
      if (b.landmark) realLots[b.landmark.id] = computeRealLots(seed, b.bx, b.bz);
      if (b.landmark && (b.landmark.district === 'farm' || (!b.landmark.district && b.landmark.kind === 'wild'))) {
        const trees =
          LANDMARK_PARK_TREES_MIN +
          Math.floor(h(seed, 'landmark-park-trees', b.bx, b.bz) * LANDMARK_PARK_TREES_SPAN) +
          Math.max(0, b.tier - 1) * TIER_EXTRA_PARK_TREES;  // EM-123: matured ⇒ greener
        emitParkTrees(seed, b.bx, b.bz, trees, true, pieces);
      }
    } else if (b.zone === 'park') {
      const trees =
        PARK_TREES_MIN + Math.floor(h(seed, 'park-trees', b.bx, b.bz) * PARK_TREES_SPAN) +
        Math.max(0, b.tier - 1) * TIER_EXTRA_PARK_TREES;  // EM-123: matured ⇒ greener
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
    // sidewalk props on their road edges are explicitly fine). EM-123: a
    // matured district fills its sidewalks in (strict superset of tier-1).
    // EM-244 (S3a): parked cars skip pedestrian-road curbs (empty set ⇒ no-op).
    emitCurbLife(seed, b.bx, b.bz, pieces, b.tier, pedestrianTileKeys);
  }

  // EM-174: ALL platted lots render as pavement pads from day 0 — the
  // generator emits zero zone buildings; only landmark anchors and real W7
  // buildings ever stand in the world.
  emptyLots = blockLots.flatMap((b) => b.lots);
  } // ── end grid path (else) ──────────────────────────────────────────────────

  // EM-244 (S3a): flatten the pedestrian road tiles into render instances
  // (same envelope loop order as emitRoads ⇒ deterministic). Empty for the
  // default/cars/no-graph plan, so the byte-identical baseline is preserved.
  // SHARED by BOTH paths — it reads pedestrianTileKeys, not the blocks.
  const pedestrianTiles: CityInstance[] = [];
  for (let j = ENV_MIN; j <= ENV_MAX; j++) {
    for (let i = ENV_MIN; i <= ENV_MAX; i++) {
      if (pedestrianTileKeys.has(`${i},${j}`)) {
        pedestrianTiles.push({ x: tileCenter(i), z: tileCenter(j), rotY: 0 });
      }
    }
  }

  return {
    pieces,
    blocks,
    landmarks,
    realLots,
    blockLots,
    emptyLots,
    streets: computeStreets(seed, world.city_graph), // EM-188: seeded names, part of the plan
    pedestrianTiles, // EM-244 (S3a): tinted-surface road tiles (empty by default)
    extent: Math.abs(tileCenter(TILE_MIN)) + TILE / 2, // 33.8: outer ring road edge
    // EM-264 (SA): additive — the key is present ONLY on the graph-lots path
    // (grid path leaves `zones` undefined ⇒ omitted ⇒ byte-identical baseline).
    ...(zones ? { zones } : {}),
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
 * EM-266 (SC): a building may carry a `zone_id` — the agent-TARGETED build zone
 * (a `plan.zones[].id`). When the plan carries zones (the graph-lots path) and
 * the id resolves, the build is placed into THAT zone's suggestedLots (claiming
 * lots in sorted-id order), OVERFLOWING past them via the slotLayout ring around
 * the zone centroid when the zone is over-cap — a violated cap you can SEE, never
 * a refused or dropped build (law §0.1). A build with NO zone_id, an unresolvable
 * id, or a plan with NO zones (flag off / no graph) falls through to the location
 * path below UNCHANGED ⇒ byte-identical to pre-SC (law §0.3).
 *
 * Pure function of (plan, buildings, centers) — same world ⇒ same spots
 * every frame, reload and input order. A building on a platted lot stands
 * ON its pavement pad (the pad reads as the building's foundation).
 */
export function assignBuildingLots(
  plan: Pick<CityPlan, 'realLots' | 'landmarks' | 'blockLots' | 'zones'>,
  buildings: ReadonlyArray<{ id: string; location: string; zone_id?: string | null }>,
  placeCenters: ReadonlyMap<string, { x: number; z: number }>,
): Map<string, { x: number; z: number }> {
  const out = new Map<string, { x: number; z: number }>();

  // EM-266 (SC): zone-targeted placement. ONLY when plan.zones exists (the
  // graph-lots path). A build whose zone_id matches a zone.id lands in THAT
  // zone; every other build (no zone_id, unresolvable id, or no zones at all)
  // routes to the EXISTING location path below UNCHANGED — so the no-zone_id /
  // no-zones case is byte-identical to pre-SC (law §0.3).
  const zonesById =
    plan.zones && plan.zones.length > 0
      ? new Map(plan.zones.map((z) => [z.id, z]))
      : null;

  const placeBuildings: { id: string; location: string }[] = [];
  const byZone = new Map<string, string[]>();
  for (const b of buildings) {
    const zid = b.zone_id;
    if (zonesById && zid != null && zonesById.has(zid)) {
      const ids = byZone.get(zid) ?? [];
      ids.push(b.id);
      byZone.set(zid, ids);
    } else {
      placeBuildings.push({ id: b.id, location: b.location });
    }
  }

  // One global claim ledger over the platted-lot pool (overflow lots are shared
  // city-wide); sorted-location order makes contention deterministic. Declared
  // HERE — BEFORE the zone loop — and SHARED with it: EM-266 (SC) F2. On the
  // graph-lots path a zone's `suggestedLots` ARE a blockLots entry (same array
  // reference — computeCityPlan sets `blockLots = zones.map(z => ({..., lots:
  // z.suggestedLots}))`), so the location-overflow pool below IS the zones' pads.
  // A pad a zone-targeted build claims must therefore be flagged in THIS ledger,
  // or a later location-overflow build could reuse the identical (x,z) and stack
  // a second mesh on the same pad. `blockIndexByLots` maps each blockLots entry's
  // lots array back to its index so a zone claim can flag the shared pad.
  const claimed = plan.blockLots.map((b) => b.lots.map(() => false));
  const blockIndexByLots = new Map<CityInstance[], number>();
  plan.blockLots.forEach((b, bi) => blockIndexByLots.set(b.lots, bi));

  // Per targeted zone (sorted zone-id order): claim suggestedLots in sorted
  // building-id order; builds PAST the lots ring the zone centroid (slotLayout —
  // the SA-sanctioned overflow). Each zone owns its OWN pads, so there is no
  // cross-zone contention. Sorted iteration both levels ⇒ input-order independent.
  if (zonesById) {
    for (const zid of [...byZone.keys()].sort()) {
      const zone = zonesById.get(zid)!;
      const ids = [...(byZone.get(zid) ?? [])].sort();
      const lots = zone.suggestedLots;
      const bi = blockIndexByLots.get(lots); // the shared blockLots entry (graph-lots path)
      const n = Math.min(ids.length, lots.length);
      for (let i = 0; i < n; i++) {
        out.set(ids[i], { x: lots[i].x, z: lots[i].z });
        // F2: flag the pad in the SHARED ledger so a location-overflow build
        // never reuses it. `bi === undefined` ⇒ the zone's lots aren't a
        // blockLots pool entry ⇒ nothing shared (defensive; on the graph-lots
        // path they always are — determinism + the overflow ring are untouched).
        if (bi !== undefined) claimed[bi][i] = true;
      }
      const overflow = ids.slice(n);
      if (overflow.length > 0) {
        // slotLayout sorts internally; the ring hugs the face centroid so an
        // over-cap zone reads as a choked, dense pile — never a vanished build.
        for (const [id, pt] of slotLayout(zone.face.centroid, overflow)) {
          out.set(id, pt);
        }
      }
    }
  }

  // ── EXISTING location path — byte-identical when no build targets a zone ─────
  const byPlace = new Map<string, string[]>();
  for (const b of placeBuildings) {
    const ids = byPlace.get(b.location) ?? [];
    ids.push(b.id);
    byPlace.set(b.location, ids);
  }
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
