/**
 * cityLayout — deterministic CityGenerator for EM-153 (Wave D1 / W15).
 *
 * Pure, deterministic city-planning math: the EW-grade city ring that
 * surrounds (never intrudes into) the Wave C historic core.
 *
 *   • MANHATTAN GRID in TILE-unit (2.6) tiles, centered on the town centroid.
 *     Avenues run on a seeded block period (4×4–6×6-tile blocks + 1 road
 *     tile), classified per tile into straight/corner/tee/cross/end pieces
 *     from their actual road neighbors — so roads terminate naturally
 *     (`road_end` caps) wherever the grid meets the historic core or the
 *     outer extent.
 *   • BLOCKS between avenues are zoned: commercial near the core ring,
 *     residential mid-ring, industrial along ONE seeded compass edge, civic
 *     sprinkled, and ~1 in 9 blocks a park. Blocks subdivide into 4–8 lots;
 *     each lot places a zone-matched building key rotated to face its street.
 *   • SIDEWALK PROPS (lamp/bench/hydrant/bin) sit at block corners along the
 *     road edges; `tree_city` fills parks and dots residential blocks; fences
 *     edge residential/park blocks; `car_a..c` park sparsely on the curbs.
 *   • HISTORIC CORE CLEARANCE (EM-156): `deriveCoreRadius` measures the Wave C
 *     town's occupied extent — places' bounding circle + the building-slot
 *     band (foliageLayout.BAND_MAX), every computeTownLayout lane endpoint,
 *     and every district zone disc — plus a margin. Tile eligibility then
 *     requires tile centers > coreRadius + TILE, which (worst-case offsets
 *     being < TILE) guarantees NO instance ever lands inside coreRadius.
 *
 * Determinism is a contract invariant (EM-155): same snapshot + same seed ⇒
 * byte-identical plan across live/replay/fork. There is NO Math.random, NO
 * Date, NO module state — all variety derives from the repo's seeded-hash
 * idiom (worldSpace.hashUnit) keyed on (seed, gridX, gridZ, purpose), with
 * seed = world.city_seed ?? 1337.
 *
 * Rotation convention (shared with D1a's registry models): rotY = 0 means the
 * piece's "front"/primary connection faces +Z; angles follow
 * Math.atan2(dx, dz), so +X ⇒ π/2, −Z ⇒ π, −X ⇒ −π/2.
 */

import type { Place } from '../../types';
import { placeToWorld, hashUnit } from './worldSpace';
import { computeTownLayout } from './townLayout';
import { BAND_MAX } from './foliageLayout';

// ── Frozen vocabulary (Wave D1 contract — D1a's registry imports this) ──────

export type CityPieceKey =
  // roads (Kenney City Kit Roads; ~2.6-unit tiles after scaling, see §D1a)
  | 'road_straight' | 'road_corner' | 'road_tee' | 'road_cross' | 'road_end'
  // zoned buildings (commercial / residential-suburban / industrial / civic)
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

export const CITY_ZONES = ['commercial', 'residential', 'industrial', 'civic', 'park'] as const;
export type CityZone = (typeof CITY_ZONES)[number];

// ── Contract API types ───────────────────────────────────────────────────────

/** Road tile pitch, world units (frozen by the Wave D1 contract). */
export const TILE = 2.6;

export interface CityInstance { x: number; z: number; rotY: number; s?: number }

export interface CityBlock { cx: number; cz: number; zone: CityZone }

export interface CityPlan {
  pieces: Record<CityPieceKey, CityInstance[]>;
  blocks: CityBlock[];
  /** Outer half-size used (Chebyshev, from the town centroid), world units. */
  extent: number;
}

// ── Tunables ─────────────────────────────────────────────────────────────────

/** Seed when the snapshot predates W15 / omits city_seed (matches backend). */
export const DEFAULT_CITY_SEED = 1337;

/** Hard cap on total emitted instances (contract budget). */
export const MAX_CITY_INSTANCES = 3000;

/** Floor for the historic-core radius (degenerate / empty towns). */
export const MIN_CORE_RADIUS = 12;

/**
 * Breathing room added beyond the measured occupied extent. The slot band
 * (BAND_MAX) is already counted per place; this just keeps the first avenue
 * off the treeline fringe.
 */
export const CORE_MARGIN = 2.5;

/** Per-block lot range (contract: blocks subdivide into 4–8 lots). */
const LOTS_MIN = 4;
const LOTS_SPAN = 5; // 4 + [0..4] ⇒ 4..8

/** Zone shaping: commercial within this many block pitches of the core ring;
 *  industrial beyond this normalized ring distance (on the seeded edge). */
const COMMERCIAL_RING_PITCHES = 1.4;
const INDUSTRIAL_RING_T = 0.5;
const PARK_BLOCK_CHANCE = 1 / 9;
const CIVIC_BLOCK_CHANCE = 0.08;

/** Curb-life densities (per block side). */
const PROP_SIDE_CHANCE = 0.75;
const FENCE_SIDE_CHANCE = 0.5;
const CAR_SIDE_CHANCE = 0.18;

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

// ── Town measurements ────────────────────────────────────────────────────────

/** The town centroid (mean of place world positions) — the city grid origin. */
export function townCenter(places: Place[]): { x: number; z: number } {
  if (places.length === 0) return { x: 0, z: 0 };
  let x = 0;
  let z = 0;
  for (const p of places) {
    const w = placeToWorld(p);
    x += w.x;
    z += w.z;
  }
  return { x: x / places.length, z: z / places.length };
}

/**
 * Historic-core radius (EM-156): the Wave C town's occupied extent + margin,
 * measured from the town centroid. Counts, for every snapshot shape:
 *   • each place's distance + BAND_MAX (the building-slot band around it),
 *   • every townLayout lane endpoint (bends included — lanes route around
 *     places, so endpoints can sit outside the bounding circle),
 *   • every district ground-zone disc (center distance + radius).
 * Never hardcoded — recomputed from computeTownLayout per snapshot.
 */
export function deriveCoreRadius(places: Place[]): number {
  if (places.length === 0) return MIN_CORE_RADIUS;
  const c = townCenter(places);
  const layout = computeTownLayout(places);
  let reach = 0;
  for (const p of places) {
    const w = placeToWorld(p);
    reach = Math.max(reach, Math.hypot(w.x - c.x, w.z - c.z) + BAND_MAX);
  }
  for (const l of layout.lanes) {
    reach = Math.max(
      reach,
      Math.hypot(l.ax - c.x, l.az - c.z),
      Math.hypot(l.bx - c.x, l.bz - c.z),
    );
  }
  for (const z of layout.zones) {
    reach = Math.max(reach, Math.hypot(z.x - c.x, z.z - c.z) + z.radius);
  }
  return Math.max(MIN_CORE_RADIUS, reach + CORE_MARGIN);
}

// ── Seeded hash (the repo idiom, keyed on seed/gridX/gridZ/purpose) ──────────

function h(seed: number, purpose: string, gridX = 0, gridZ = 0): number {
  return hashUnit(`city:${seed}:${gridX}:${gridZ}:${purpose}`);
}

// ── The generator ────────────────────────────────────────────────────────────

interface Grid {
  seed: number;
  center: { x: number; z: number };
  coreRadius: number;
  extent: number;
  /** Block edge in tiles (4..6, seeded). */
  blockSize: number;
  /** Road pitch in tiles (blockSize + 1). */
  period: number;
  /** Max |tile index| kept strictly inside the extent. */
  half: number;
}

function emptyPieces(): Record<CityPieceKey, CityInstance[]> {
  const out = {} as Record<CityPieceKey, CityInstance[]>;
  for (const k of CITY_PIECE_KEYS) out[k] = [];
  return out;
}

/**
 * Tile eligibility: strictly inside the extent square AND its center more
 * than coreRadius + TILE from the centroid. Every instance offsets < TILE
 * from an eligible tile's center, so eligibility alone guarantees both the
 * core-clearance and the bounds invariants.
 */
function tileEligible(g: Grid, gx: number, gz: number): boolean {
  if (Math.abs(gx) > g.half || Math.abs(gz) > g.half) return false;
  return Math.hypot(gx * TILE, gz * TILE) > g.coreRadius + TILE;
}

function onRoadLine(g: Grid, v: number): boolean {
  return ((v % g.period) + g.period) % g.period === 0;
}

function isRoadTile(g: Grid, gx: number, gz: number): boolean {
  return tileEligible(g, gx, gz) && (onRoadLine(g, gx) || onRoadLine(g, gz));
}

function tileWorld(g: Grid, gx: number, gz: number): { x: number; z: number } {
  return { x: g.center.x + gx * TILE, z: g.center.z + gz * TILE };
}

/** Roads: classify every road tile from its actual road neighbors. */
function emitRoads(g: Grid, pieces: Record<CityPieceKey, CityInstance[]>): void {
  for (let gz = -g.half; gz <= g.half; gz++) {
    for (let gx = -g.half; gx <= g.half; gx++) {
      if (!isRoadTile(g, gx, gz)) continue;
      let mask = 0;
      for (const d of SIDES) {
        if (isRoadTile(g, gx + d.dx, gz + d.dz)) mask |= d.bit;
      }
      if (mask === 0) continue; // drop isolated stubs — keeps connectivity law
      const { x, z } = tileWorld(g, gx, gz);
      if (mask === 15) pieces.road_cross.push({ x, z, rotY: 0 });
      else if (mask in TEE_ROT) pieces.road_tee.push({ x, z, rotY: TEE_ROT[mask] });
      else if (mask in STRAIGHT_ROT) pieces.road_straight.push({ x, z, rotY: STRAIGHT_ROT[mask] });
      else if (mask in CORNER_ROT) pieces.road_corner.push({ x, z, rotY: CORNER_ROT[mask] });
      else pieces.road_end.push({ x, z, rotY: END_ROT[mask] });
    }
  }
}

/** Zone-matched building variants. */
const ZONE_BUILDINGS: Readonly<Record<Exclude<CityZone, 'park'>, readonly CityPieceKey[]>> = {
  commercial: ['com_a', 'com_b', 'com_c'],
  residential: ['res_a', 'res_b', 'res_c'],
  industrial: ['ind_a', 'ind_b'],
  civic: ['civic_a'],
};

const CAR_KEYS: readonly CityPieceKey[] = ['car_a', 'car_b', 'car_c'];

/** Zone for a block: park lottery, seeded industrial edge, ring distance. */
function pickZone(g: Grid, bx: number, bz: number, rcx: number, rcz: number): CityZone {
  if (h(g.seed, 'zone-park', bx, bz) < PARK_BLOCK_CHANCE) return 'park';
  const d = Math.hypot(rcx, rcz);
  const span = Math.max(g.extent - g.coreRadius, 1e-6);
  const t = Math.min(1, Math.max(0, (d - g.coreRadius) / span));
  // ONE seeded compass edge hosts industry (0:+X 1:−X 2:+Z 3:−Z).
  const edge = Math.floor(h(g.seed, 'industrial-edge') * 4) % 4;
  const ax = Math.abs(rcx);
  const az = Math.abs(rcz);
  const onEdge =
    (edge === 0 && rcx > 0 && ax >= az) ||
    (edge === 1 && rcx < 0 && ax >= az) ||
    (edge === 2 && rcz > 0 && az >= ax) ||
    (edge === 3 && rcz < 0 && az >= ax);
  if (onEdge && t >= INDUSTRIAL_RING_T) return 'industrial';
  if (h(g.seed, 'zone-civic', bx, bz) < CIVIC_BLOCK_CHANCE) return 'civic';
  // commercial hugs the core ring: within ~1.4 block pitches of the boundary
  if (d - g.coreRadius < COMMERCIAL_RING_PITCHES * g.period * TILE) return 'commercial';
  return 'residential';
}

/** Lots, props, greenery, fences and curb cars for one developed block. */
function populateBlock(
  g: Grid,
  bx: number,
  bz: number,
  zone: CityZone,
  pieces: Record<CityPieceKey, CityInstance[]>,
): void {
  const blockHalf = (g.blockSize * TILE) / 2;
  // Block center, relative to the centroid / absolute world.
  const rcx = (bx + 0.5) * g.period * TILE;
  const rcz = (bz + 0.5) * g.period * TILE;
  const wx = g.center.x + rcx;
  const wz = g.center.z + rcz;

  // Buildings on perimeter lots, facing their street (zone-matched keys).
  if (zone !== 'park') {
    const variants = ZONE_BUILDINGS[zone];
    const lots = LOTS_MIN + Math.floor(h(g.seed, 'lots', bx, bz) * LOTS_SPAN);
    for (let i = 0; i < lots; i++) {
      const side = SIDES[i % 4];
      const slot = Math.floor(i / 4);
      const onThisSide = Math.floor((lots - 1 - (i % 4)) / 4) + 1;
      const lateralSpan = g.blockSize * TILE - TILE;
      const lateral =
        ((slot + 0.5) / onThisSide - 0.5) * lateralSpan +
        (h(g.seed, `lot-jitter-${i}`, bx, bz) - 0.5) * 0.5;
      const inset = blockHalf - 1.5;
      const tx = -side.dz; // side tangent
      const tz = side.dx;
      const key = variants[Math.floor(h(g.seed, `lot-key-${i}`, bx, bz) * variants.length) % variants.length];
      pieces[key].push({
        x: wx + side.dx * inset + tx * lateral,
        z: wz + side.dz * inset + tz * lateral,
        rotY: dirRot(side.dx, side.dz),
        s: 0.92 + h(g.seed, `lot-scale-${i}`, bx, bz) * 0.16,
      });
    }
  }

  // Greenery: parks fill with city trees; residential blocks get a couple.
  if (zone === 'park') {
    const trees = 5 + Math.floor(h(g.seed, 'park-trees', bx, bz) * 4);
    const spread = blockHalf - 1.0;
    for (let i = 0; i < trees; i++) {
      pieces.tree_city.push({
        x: wx + (h(g.seed, `park-tree-x-${i}`, bx, bz) - 0.5) * 2 * spread,
        z: wz + (h(g.seed, `park-tree-z-${i}`, bx, bz) - 0.5) * 2 * spread,
        rotY: h(g.seed, `park-tree-r-${i}`, bx, bz) * Math.PI * 2,
        s: 0.85 + h(g.seed, `park-tree-s-${i}`, bx, bz) * 0.4,
      });
    }
  } else if (zone === 'residential') {
    const spread = Math.max(blockHalf - 3.4, 0.8); // inside the building ring
    for (let i = 0; i < 2; i++) {
      pieces.tree_city.push({
        x: wx + (h(g.seed, `res-tree-x-${i}`, bx, bz) - 0.5) * 2 * spread,
        z: wz + (h(g.seed, `res-tree-z-${i}`, bx, bz) - 0.5) * 2 * spread,
        rotY: h(g.seed, `res-tree-r-${i}`, bx, bz) * Math.PI * 2,
        s: 0.8 + h(g.seed, `res-tree-s-${i}`, bx, bz) * 0.35,
      });
    }
  }

  for (let s = 0; s < 4; s++) {
    const side = SIDES[s];
    const tx = -side.dz;
    const tz = side.dx;

    // Sidewalk props at block corners along the road edge.
    if (h(g.seed, `prop-${s}`, bx, bz) < PROP_SIDE_CHANCE) {
      const r = h(g.seed, `prop-kind-${s}`, bx, bz);
      const key: CityPieceKey = r < 0.4 ? 'lamp' : r < 0.6 ? 'bin' : r < 0.8 ? 'hydrant' : 'bench';
      const cornerSign = h(g.seed, `prop-corner-${s}`, bx, bz) < 0.5 ? -1 : 1;
      const inset = blockHalf - 0.5;
      const lateral = cornerSign * (blockHalf - 0.7);
      pieces[key].push({
        x: wx + side.dx * inset + tx * lateral,
        z: wz + side.dz * inset + tz * lateral,
        rotY: dirRot(side.dx, side.dz),
      });
    }

    // Fence runs edge residential blocks and parks.
    if (
      (zone === 'residential' || zone === 'park') &&
      h(g.seed, `fence-${s}`, bx, bz) < FENCE_SIDE_CHANCE
    ) {
      for (const k of [-1, 1]) {
        const inset = blockHalf - 0.9;
        const lateral = k * blockHalf * 0.35;
        pieces.fence.push({
          x: wx + side.dx * inset + tx * lateral,
          z: wz + side.dz * inset + tz * lateral,
          rotY: dirRot(side.dx, side.dz) + HALF_PI, // rail runs along the side
        });
      }
    }

    // Sparse parked cars on the curb of the adjacent road tile.
    if (h(g.seed, `car-${s}`, bx, bz) < CAR_SIDE_CHANCE) {
      const along = 1 + Math.floor(h(g.seed, `car-at-${s}`, bx, bz) * g.blockSize);
      let rgx: number;
      let rgz: number;
      if (side.dx !== 0) {
        rgx = side.dx > 0 ? (bx + 1) * g.period : bx * g.period;
        rgz = bz * g.period + along;
      } else {
        rgx = bx * g.period + along;
        rgz = side.dz > 0 ? (bz + 1) * g.period : bz * g.period;
      }
      if (isRoadTile(g, rgx, rgz)) {
        const key = CAR_KEYS[Math.floor(h(g.seed, `car-key-${s}`, bx, bz) * CAR_KEYS.length) % CAR_KEYS.length];
        const flip = h(g.seed, `car-flip-${s}`, bx, bz) < 0.5 ? 0 : Math.PI;
        const t = tileWorld(g, rgx, rgz);
        pieces[key].push({
          // pulled from the road center toward the block's curb
          x: t.x - side.dx * TILE * 0.32,
          z: t.z - side.dz * TILE * 0.32,
          rotY: dirRot(side.dx, side.dz) + HALF_PI + flip, // along the road
        });
      }
    }
  }
}

/** One full generation pass at a fixed extent. */
function generate(g: Grid): CityPlan {
  const pieces = emptyPieces();

  emitRoads(g, pieces);

  // Pass 1 — find every developable block and zone it.
  interface Developed { bx: number; bz: number; rcx: number; rcz: number; zone: CityZone }
  const developed: Developed[] = [];
  const bMin = Math.floor(-g.half / g.period) - 1;
  const bMax = Math.ceil(g.half / g.period) + 1;
  for (let bz = bMin; bz <= bMax; bz++) {
    for (let bx = bMin; bx <= bMax; bx++) {
      // Develop a block only when EVERY tile of it is eligible (fully outside
      // the historic core, fully inside the extent).
      let eligible = true;
      for (let dz = 1; dz <= g.blockSize && eligible; dz++) {
        for (let dx = 1; dx <= g.blockSize && eligible; dx++) {
          if (!tileEligible(g, bx * g.period + dx, bz * g.period + dz)) eligible = false;
        }
      }
      if (!eligible) continue;
      const rcx = (bx + 0.5) * g.period * TILE;
      const rcz = (bz + 0.5) * g.period * TILE;
      developed.push({ bx, bz, rcx, rcz, zone: pickZone(g, bx, bz, rcx, rcz) });
    }
  }

  // Park guarantee: the lottery is ~1 in 9, but a small / unlucky city can
  // miss entirely — deterministically convert the block that came closest to
  // winning (lowest park hash; loop order breaks exact ties).
  if (developed.length > 0 && !developed.some((b) => b.zone === 'park')) {
    let best = developed[0];
    let bestRoll = h(g.seed, 'zone-park', best.bx, best.bz);
    for (const b of developed) {
      const roll = h(g.seed, 'zone-park', b.bx, b.bz);
      if (roll < bestRoll) {
        bestRoll = roll;
        best = b;
      }
    }
    best.zone = 'park';
  }

  // Pass 2 — emit blocks + their contents in deterministic loop order.
  const blocks: CityBlock[] = [];
  for (const b of developed) {
    blocks.push({ cx: g.center.x + b.rcx, cz: g.center.z + b.rcz, zone: b.zone });
    populateBlock(g, b.bx, b.bz, b.zone, pieces);
  }

  return { pieces, blocks, extent: g.extent };
}

function countInstances(pieces: Record<CityPieceKey, CityInstance[]>): number {
  let n = 0;
  for (const k of CITY_PIECE_KEYS) n += pieces[k].length;
  return n;
}

/**
 * Compute the deterministic city plan for a world snapshot.
 *
 * seed = world.city_seed ?? 1337; coreRadius defaults to deriveCoreRadius
 * (the measured Wave C occupied extent + margin); extent defaults to
 * 2 × coreRadius and auto-shrinks by one block period until the total
 * instance count fits the MAX_CITY_INSTANCES budget. `extent` in the result
 * is the half-size actually used.
 */
export function computeCityPlan(
  world: { places: Place[]; city_seed?: number | null },
  opts?: { coreRadius?: number; extent?: number },
): CityPlan {
  const places = world.places ?? [];
  const seed = world.city_seed ?? DEFAULT_CITY_SEED;
  const center = townCenter(places);
  const coreRadius = opts?.coreRadius ?? deriveCoreRadius(places);
  const blockSize = LOTS_MIN + Math.floor(h(seed, 'block-size') * 3); // 4..6 tiles
  const period = blockSize + 1;

  let extent = opts?.extent ?? coreRadius * 2;
  const makeGrid = (e: number): Grid => ({
    seed,
    center,
    coreRadius,
    extent: e,
    blockSize,
    period,
    half: Math.max(0, Math.floor((e - TILE) / TILE)),
  });

  let plan = generate(makeGrid(extent));
  // Budget cap: shrink the ring one block period at a time until it fits.
  while (
    countInstances(plan.pieces) > MAX_CITY_INSTANCES &&
    extent - period * TILE > coreRadius + 2 * TILE
  ) {
    extent -= period * TILE;
    plan = generate(makeGrid(extent));
  }
  return plan;
}
