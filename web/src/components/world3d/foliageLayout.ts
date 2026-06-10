/**
 * foliageLayout — pure, DETERMINISTIC layout math for EM-118 (instanced trees
 * + lived-in town props). No React, no three.js, no randomness: every position
 * derives from `hashUnit` (worldSpace) + place geometry, so the same world
 * yields the same forest/prop layout every frame, reload, and test run.
 *
 * Clearance model (contract §B3):
 *   • Project structures spawn on slot rings radius SLOT_BASE_RADIUS(5.5)…~10
 *     around each place center (worldSpace.slotLayout — read-only for us).
 *   • TREES keep ≥ TREE_PLACE_CLEAR (10.5 > the contract's "~10") from EVERY
 *     place center, so they can never collide with structures.
 *   • NEAR props (lamps, benches) sit on a snug inner ring, NEAR_RING_MIN..
 *     NEAR_RING_MAX (3.2–4.6) from their OWN place — entirely below
 *     SLOT_BASE_RADIUS, so they can never touch their place's slot band —
 *     and keep ≥ NEIGHBOR_FLOOR (3.7) from every OTHER center, outside any
 *     neighbor structure's footprint and the inner edge of its first slot.
 *     (In real procgen towns adjacent places sit only ~8.6 world units apart,
 *     so neighbors' 5.5–10 slot bands blanket every inner ring — a strict
 *     "outside every place's band" rule is unsatisfiable there; the contract's
 *     "inside radius ~3.5–4.5" option is therefore enforced against the prop's
 *     own place, with the 3.7 neighbor floor as the cross-place guard.)
 *   • WILD props (fences, bushes, mushrooms, rocks) keep ≥ BAND_MAX (10.5)
 *     from every place center.
 *
 * Path-clearance model (orchestrator gate feedback — contract-level):
 *   Ground.tsx draws dirt-path ribbons (width 1.4) from the social hub to
 *   every other place. `pathSegments` mirrors that exact geometry here.
 *   • NON-LAMP items (trees, bushes, rocks, mushrooms, fences, benches) are
 *     rejected within PATH_CLEAR (= half-width 0.7 + 0.6 margin) of ANY
 *     ribbon's centerline (point-to-segment distance).
 *   • LAMPS are the deliberate exception: they LINE the paths, placed at
 *     LAMP_PATH_OFFSET (half-width + 0.8) beside the ribbon, alternating
 *     sides per spoke — never on the ribbon proper.
 */

import type { Place } from '../../types';
import { SIZE, placeToWorld, hashUnit, type WorldPoint } from './worldSpace';

// ── Contract constants ───────────────────────────────────────────────────────

/** Trees never come closer than this to any place center (contract: ≥ ~10). */
export const TREE_PLACE_CLEAR = 10.5;
/** Minimum tree-to-tree spacing so canopies don't merge into blobs. */
export const TREE_SPACING = 2.4;
/** Target treeline size (contract bound: ~50–80). */
export const TREE_COUNT = 60;
/** Tree scatter spread (square of side TREE_SPREAD centered on the village). */
export const TREE_SPREAD = SIZE * 1.5;
/** Trees within this distance of world origin render at full detail (LOD). */
export const TREE_LOD_RADIUS = 26;

/** The forbidden building-slot band around every place center: props must be
 *  ≤ BAND_MIN (snug against the place) or ≥ BAND_MAX (outside the rings). */
export const BAND_MIN = 5.0;
export const BAND_MAX = 10.5;

/** Near props live on this ring around their OWN place (below SLOT_BASE_RADIUS). */
export const NEAR_RING_MIN = 3.2;
export const NEAR_RING_MAX = 4.6;
/** …and keep at least this far from every OTHER place center. */
export const NEIGHBOR_FLOOR = 3.7;

/** Near-prop ring radii (inside NEAR_RING_*, outside the structure footprint). */
export const LAMP_RING_RADIUS = 4.15;
export const BENCH_RING_RADIUS = 3.9;

/** Half the dirt-path ribbon width Ground.tsx draws (planeGeometry [len, 1.4]). */
export const PATH_HALF_WIDTH = 0.7;
/** Non-lamp items keep this far from every path centerline (half + 0.6 margin). */
export const PATH_CLEAR = PATH_HALF_WIDTH + 0.6;
/** Lamps line the paths from just beside the ribbon (half-width + 0.8). */
export const LAMP_PATH_OFFSET = PATH_HALF_WIDTH + 0.8;
/** Fence arcs sit just outside the slot band. */
export const FENCE_RING_RADIUS = 11.2;

/** Conservative prop counts (contract: total NEW instances ≲400). */
export const MAX_LAMPS = 14;
export const BENCHES_PER_PLAZA = 3;
export const FENCE_SEGMENTS_PER_HOME = 7;
export const BUSH_COUNT = 22;
export const ROCK_COUNT = 16;
export const MUSHROOM_COUNT = 14;

// ── Types ────────────────────────────────────────────────────────────────────

export type TreeVariant = 'oak' | 'conifer' | 'blossom';

export interface ScatterItem {
  x: number;
  z: number;
  scale: number;
  rot: number;
}

export interface TreeItem extends ScatterItem {
  variant: TreeVariant;
}

// ── Shared guards ────────────────────────────────────────────────────────────

function dist(a: WorldPoint, x: number, z: number): number {
  return Math.hypot(a.x - x, a.z - z);
}

/**
 * Near-prop validity: on the snug inner ring of its OWN place (so it can never
 * touch that place's slot band) and ≥ NEIGHBOR_FLOOR from every other center.
 */
export function nearPropValid(
  x: number,
  z: number,
  own: WorldPoint,
  centers: WorldPoint[],
): boolean {
  const dOwn = dist(own, x, z);
  if (dOwn < NEAR_RING_MIN || dOwn > NEAR_RING_MAX) return false;
  return centers.every(
    (c) => (c.x === own.x && c.z === own.z) || dist(c, x, z) >= NEIGHBOR_FLOOR,
  );
}

/** True if (x,z) keeps ≥ minClear from EVERY place center. */
function clearOfAll(x: number, z: number, centers: WorldPoint[], minClear: number): boolean {
  return centers.every((c) => dist(c, x, z) >= minClear);
}

// ── Path corridors (mirrors Ground.tsx exactly) ──────────────────────────────

export interface PathSeg {
  ax: number;
  az: number;
  bx: number;
  bz: number;
}

/**
 * The dirt-path centerlines Ground.tsx draws: social hub (falling back to the
 * first place) → every other place. Must stay in lockstep with Ground.tsx's
 * path derivation.
 */
export function pathSegments(places: Place[]): PathSeg[] {
  if (places.length < 2) return [];
  const hub = places.find((p) => p.kind === 'social') ?? places[0];
  const hubW = placeToWorld(hub);
  return places
    .filter((p) => p.id !== hub.id)
    .map((p) => {
      const w = placeToWorld(p);
      return { ax: hubW.x, az: hubW.z, bx: w.x, bz: w.z };
    });
}

/** Point-to-segment distance on the XZ plane. */
function pointSegDist(x: number, z: number, s: PathSeg): number {
  const dx = s.bx - s.ax;
  const dz = s.bz - s.az;
  const len2 = dx * dx + dz * dz;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((x - s.ax) * dx + (z - s.az) * dz) / len2));
  return Math.hypot(x - (s.ax + dx * t), z - (s.az + dz * t));
}

/** Distance from (x,z) to the nearest path centerline (Infinity if no paths). */
export function distToNearestPath(x: number, z: number, segs: PathSeg[]): number {
  let best = Infinity;
  for (const s of segs) best = Math.min(best, pointSegDist(x, z, s));
  return best;
}

// ── Trees (EM-118 treeline / orchard) ────────────────────────────────────────

/**
 * Deterministic rejection scatter for the town-edge treeline. Trees keep
 * TREE_PLACE_CLEAR from every place center (so they never touch the building
 * slot rings) and TREE_SPACING from each other. Variant mix: ~45% round oak,
 * ~35% conifer, ~20% blossom.
 */
export function layoutTrees(places: Place[]): TreeItem[] {
  const centers = places.map(placeToWorld);
  const segs = pathSegments(places);
  const out: TreeItem[] = [];
  let attempts = 0;
  let i = 0;
  while (out.length < TREE_COUNT && attempts < TREE_COUNT * 30) {
    attempts++;
    const seed = `treeline-${i++}`;
    const x = (hashUnit(`${seed}-x`) - 0.5) * TREE_SPREAD;
    const z = (hashUnit(`${seed}-z`) - 0.5) * TREE_SPREAD;
    if (!clearOfAll(x, z, centers, TREE_PLACE_CLEAR)) continue;
    if (distToNearestPath(x, z, segs) < PATH_CLEAR) continue;
    if (out.some((t) => Math.hypot(t.x - x, t.z - z) < TREE_SPACING)) continue;
    const roll = hashUnit(`${seed}-v`);
    out.push({
      x,
      z,
      scale: 0.85 + hashUnit(`${seed}-s`) * 0.55,
      rot: hashUnit(`${seed}-r`) * Math.PI * 2,
      variant: roll < 0.45 ? 'oak' : roll < 0.8 ? 'conifer' : 'blossom',
    });
  }
  return out;
}

/**
 * Static LOD split: trees near the village core (where the camera orbits)
 * render full multi-part detail; the outer ring renders a simplified two-part
 * silhouette. Deterministic — no per-frame re-bucketing.
 */
export function splitByLod(trees: TreeItem[]): { near: TreeItem[]; far: TreeItem[] } {
  const near: TreeItem[] = [];
  const far: TreeItem[] = [];
  for (const t of trees) {
    (Math.hypot(t.x, t.z) <= TREE_LOD_RADIUS ? near : far).push(t);
  }
  return { near, far };
}

// ── Wild scatter (bushes, rocks) ─────────────────────────────────────────────

/**
 * Generic deterministic scatter that keeps ≥ BAND_MAX from every place center
 * (entirely outside all building-slot rings) and PATH_CLEAR from every dirt
 * path. Used for bushes and rocks.
 */
export function layoutWildScatter(
  count: number,
  prefix: string,
  places: Place[],
  spread: number = TREE_SPREAD,
): ScatterItem[] {
  const centers = places.map(placeToWorld);
  const segs = pathSegments(places);
  const out: ScatterItem[] = [];
  let attempts = 0;
  let i = 0;
  while (out.length < count && attempts < count * 14) {
    attempts++;
    const seed = `${prefix}-${i++}`;
    const x = (hashUnit(`${seed}-x`) - 0.5) * spread;
    const z = (hashUnit(`${seed}-z`) - 0.5) * spread;
    if (!clearOfAll(x, z, centers, BAND_MAX)) continue;
    if (distToNearestPath(x, z, segs) < PATH_CLEAR) continue;
    out.push({
      x,
      z,
      scale: 0.65 + hashUnit(`${seed}-s`) * 0.6,
      rot: hashUnit(`${seed}-r`) * Math.PI * 2,
    });
  }
  return out;
}

/**
 * Mushrooms cluster toward the WILD places: each sits on an annulus just
 * outside the wild place's slot band (BAND_MAX + 0.2 … +5), rejected if it
 * lands inside any other place's band. No wild place → plain wild scatter.
 */
export function layoutMushrooms(places: Place[]): ScatterItem[] {
  const wilds = places.filter((p) => p.kind === 'wild').map(placeToWorld);
  if (wilds.length === 0) return layoutWildScatter(MUSHROOM_COUNT, 'mushroom', places);
  const centers = places.map(placeToWorld);
  const segs = pathSegments(places);
  const out: ScatterItem[] = [];
  let attempts = 0;
  let i = 0;
  while (out.length < MUSHROOM_COUNT && attempts < MUSHROOM_COUNT * 14) {
    attempts++;
    const seed = `mushroom-${i++}`;
    const home = wilds[Math.floor(hashUnit(`${seed}-w`) * wilds.length) % wilds.length];
    const radius = BAND_MAX + 0.2 + hashUnit(`${seed}-d`) * 4.8;
    const angle = hashUnit(`${seed}-a`) * Math.PI * 2;
    const x = home.x + Math.cos(angle) * radius;
    const z = home.z + Math.sin(angle) * radius;
    if (!clearOfAll(x, z, centers, BAND_MAX)) continue;
    if (distToNearestPath(x, z, segs) < PATH_CLEAR) continue;
    out.push({
      x,
      z,
      scale: 0.55 + hashUnit(`${seed}-s`) * 0.5,
      rot: hashUnit(`${seed}-r`) * Math.PI * 2,
    });
  }
  return out;
}

// ── Lamps (gateway lights flanking the dirt paths) ───────────────────────────

/**
 * Lamp posts LINE the dirt paths Ground draws from the social hub to every
 * other place: one at each spoke's hub end and one at its far-place end, set
 * deliberately BESIDE the ribbon — LAMP_PATH_OFFSET (half-width + 0.8) out
 * from the centerline, alternating sides per spoke — on the LAMP_RING_RADIUS
 * ring of their own place (below SLOT_BASE_RADIUS). Candidates failing the
 * near-prop clearance, or landing on ANY ribbon proper (a different spoke's,
 * say), are dropped.
 */
export function layoutLamps(places: Place[]): ScatterItem[] {
  if (places.length < 2) return [];
  const hub = places.find((p) => p.kind === 'social') ?? places[0];
  const hubW = placeToWorld(hub);
  const centers = places.map(placeToWorld);
  const segs = pathSegments(places);
  const out: ScatterItem[] = [];

  const push = (x: number, z: number, own: WorldPoint) => {
    if (out.length >= MAX_LAMPS) return;
    if (!nearPropValid(x, z, own, centers)) return;
    // beside the ribbon by construction, but never ON any other ribbon either
    if (distToNearestPath(x, z, segs) < PATH_HALF_WIDTH + 0.1) return;
    out.push({ x, z, scale: 1, rot: 0 });
  };

  places
    .filter((p) => p.id !== hub.id)
    .forEach((p, si) => {
      const w = placeToWorld(p);
      const dx = hubW.x - w.x;
      const dz = hubW.z - w.z;
      const len = Math.hypot(dx, dz) || 1;
      const ux = dx / len;
      const uz = dz / len;
      // perpendicular set-out so the lamp flanks (never blocks) the ribbon
      const px = -uz * LAMP_PATH_OFFSET;
      const pz = ux * LAMP_PATH_OFFSET;
      const side = si % 2 === 0 ? 1 : -1;
      // distance along the spoke that keeps the lamp on its own place ring
      const ringIn = Math.sqrt(LAMP_RING_RADIUS ** 2 - LAMP_PATH_OFFSET ** 2);
      // far-place gateway lamp
      push(w.x + ux * ringIn + px * side, w.z + uz * ringIn + pz * side, w);
      // hub-end lamp
      push(hubW.x - ux * ringIn + px * side, hubW.z - uz * ringIn + pz * side, hubW);
    });

  return out;
}

// ── Benches (plaza seating) ──────────────────────────────────────────────────

/**
 * A few benches around each SOCIAL place, on the BENCH_RING_RADIUS ring,
 * rotated to face the place center — placed just OFF the path corridors,
 * never on a ribbon. Scans a deterministic fan of candidate angles (hashed
 * start) and keeps the first BENCHES_PER_PLAZA that clear both the near-prop
 * rule and every path corridor.
 */
export function layoutBenches(places: Place[]): ScatterItem[] {
  const centers = places.map(placeToWorld);
  const segs = pathSegments(places);
  const out: ScatterItem[] = [];
  const CANDIDATES = 12;
  for (const p of places) {
    if (p.kind !== 'social') continue;
    const c = placeToWorld(p);
    const angle0 = hashUnit(`${p.id}-bench`) * Math.PI * 2;
    let placed = 0;
    for (let k = 0; k < CANDIDATES && placed < BENCHES_PER_PLAZA; k++) {
      const angle = angle0 + (k / CANDIDATES) * Math.PI * 2;
      const x = c.x + Math.cos(angle) * BENCH_RING_RADIUS;
      const z = c.z + Math.sin(angle) * BENCH_RING_RADIUS;
      if (!nearPropValid(x, z, c, centers)) continue;
      if (distToNearestPath(x, z, segs) < PATH_CLEAR) continue;
      // face the plaza: local +Z (the bench back) points outward
      out.push({ x, z, scale: 1, rot: Math.PI / 2 - angle });
      placed++;
    }
  }
  return out;
}

// ── Fences (home-edge arcs) ──────────────────────────────────────────────────

/**
 * Rustic fence arcs around HOME places, just outside the slot band
 * (FENCE_RING_RADIUS > BAND_MAX). Segments lie tangent to the arc; any segment
 * that would fall inside another place's clearance — or across a dirt path
 * (the hub→home path crosses this ring!) — is dropped.
 */
export function layoutFences(places: Place[]): ScatterItem[] {
  const centers = places.map(placeToWorld);
  const segs = pathSegments(places);
  const out: ScatterItem[] = [];
  const span = Math.PI * 0.62; // arc the fence covers
  for (const p of places) {
    if (p.kind !== 'home') continue;
    const c = placeToWorld(p);
    const angle0 = hashUnit(`${p.id}-fence`) * Math.PI * 2;
    const step = span / FENCE_SEGMENTS_PER_HOME;
    for (let k = 0; k < FENCE_SEGMENTS_PER_HOME; k++) {
      const angle = angle0 - span / 2 + (k + 0.5) * step;
      const x = c.x + Math.cos(angle) * FENCE_RING_RADIUS;
      const z = c.z + Math.sin(angle) * FENCE_RING_RADIUS;
      if (!clearOfAll(x, z, centers, BAND_MAX)) continue;
      // fence segments are ~2.15 long around their center — keep the whole
      // rail out of the corridor, not just the midpoint
      if (distToNearestPath(x, z, segs) < PATH_CLEAR + 1.1) continue;
      // segment runs tangent to the arc (local +X along the tangent)
      out.push({ x, z, scale: 1, rot: -(angle + Math.PI / 2) });
    }
  }
  return out;
}
