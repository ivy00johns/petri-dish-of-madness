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
 * Lane-clearance model (Wave C / EM-149 — townLayout is the single source of
 * truth for the lane network; the old hub-spoke mirror is gone):
 *   Ground.tsx draws the lane strips from townLayout's graph (spine 2.3 wide,
 *   connectors 1.55). `pathSegments` here returns the SAME segments, so all
 *   corridor clearances track the real lanes.
 *   • NON-LAMP items (trees, bushes, rocks, mushrooms, fences, benches) are
 *     rejected within PATH_CLEAR (= max half-width 1.15 + 0.6 margin) of ANY
 *     lane's centerline (point-to-segment distance).
 *   • LAMPS are the deliberate exception: they LINE the lanes, placed at
 *     LAMP_PATH_OFFSET (half-width + 0.8) beside the strip near each lane
 *     end, alternating sides per lane — never on the strip proper.
 *
 * Historic-core bound (Wave D1 gate fix, EM-156): the generated city ring
 * (cityLayout) owns everything OUTSIDE deriveCoreRadius of the town centroid —
 * its road tiles start just past that boundary — so all wilderness scatter
 * (treeline, bushes, rocks, mushrooms) is clamped INSIDE it via
 * `wildernessBound`. The radius is DERIVED per snapshot (never hardcoded),
 * exactly the radius the city generator clears. Ring-bound props
 * (lamps/benches/fences ≤ FENCE_RING_RADIUS = 11.2 from their place) sit
 * ≥ ~13 inside the boundary by construction and need no clamp. The city ring
 * supplies its own greenery (`tree_city`); the wilderness backdrop belongs in
 * the core meadow.
 */

import type { Place } from '../../types';
import { SIZE, placeToWorld, hashUnit, type WorldPoint } from './worldSpace';
import { computeTownLayout, LANE_WIDTHS } from './townLayout';
// NOTE: cityLayout also imports BAND_MAX from this module — a deliberate,
// benign cycle: both sides only dereference the import inside function bodies
// (runtime), never during module evaluation.
import { deriveCoreRadius, townCenter } from './cityLayout';

// ── Contract constants ───────────────────────────────────────────────────────

/** Trees never come closer than this to any place center (contract: ≥ ~10). */
export const TREE_PLACE_CLEAR = 10.5;
/** Minimum tree-to-tree spacing so canopies don't merge into blobs. */
export const TREE_SPACING = 2.4;
/** Target treeline size. Wave C aimed at the 50–80 contract band across the
 *  open ±49.5 meadow; since the Wave D1 clamp the meadow is the historic-core
 *  disc only (r ≈ 41 for the default town) and the SAME sampling yields ~42
 *  trees — the city ring's own `tree_city` greenery (~28) carries the outer
 *  canopy now, so the in-core treeline deliberately stays a backdrop, not a
 *  packed forest. TREE_COUNT remains the (rarely reached) upper target. */
export const TREE_COUNT = 72;
/** Tree scatter SAMPLING spread (square of side TREE_SPREAD centered on the
 *  village). Since Wave D1 every sample is additionally clamped inside
 *  `wildernessBound` (the historic-core disc) — the square is just the
 *  candidate space, the disc is the law. */
export const TREE_SPREAD = SIZE * 1.5;
/** Trees within this distance of world origin render at full detail (LOD). */
export const TREE_LOD_RADIUS = 34;

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

/** Half the WIDEST lane strip Ground.tsx draws (townLayout spine, 2.3 wide) —
 *  clearances are conservative against the spine so connectors are covered. */
export const PATH_HALF_WIDTH = LANE_WIDTHS.spine / 2;
/** Non-lamp items keep this far from every lane centerline (half + 0.6 margin). */
export const PATH_CLEAR = PATH_HALF_WIDTH + 0.6;
/** Lamps line the lanes from just beside the strip (half-width + 0.8). */
export const LAMP_PATH_OFFSET = PATH_HALF_WIDTH + 0.8;
/** Fence arcs sit just outside the slot band. */
export const FENCE_RING_RADIUS = 11.2;

/** Conservative prop counts (contract: total NEW instances ≲400 — the Wave C
 *  town has 4 homes and 2 social places, so per-place counts come down). */
export const MAX_LAMPS = 18;
export const BENCHES_PER_PLAZA = 3;
export const FENCE_SEGMENTS_PER_HOME = 5;
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

// ── Historic-core bound (Wave D1 gate fix — see file header) ────────────────

/** Canopy/footprint breathing room kept off the city ring's first road cap. */
export const WILDERNESS_EDGE_MARGIN = 1.0;

export interface WildernessBound {
  cx: number;
  cz: number;
  /** Max distance from the town centroid wilderness items may stand at. */
  maxR: number;
}

/**
 * The disc wilderness scatter must stay inside: the SAME historic-core radius
 * the city generator clears (cityLayout.deriveCoreRadius — measured per
 * snapshot, never hardcoded), centered on the SAME town centroid, minus a
 * canopy margin. Everything beyond it is the generated city's ground.
 */
export function wildernessBound(places: Place[]): WildernessBound {
  const c = townCenter(places);
  return {
    cx: c.x,
    cz: c.z,
    maxR: Math.max(0, deriveCoreRadius(places) - WILDERNESS_EDGE_MARGIN),
  };
}

/** True if (x,z) lies inside the wilderness disc (never on the city ring). */
export function insideWilderness(x: number, z: number, b: WildernessBound): boolean {
  return Math.hypot(x - b.cx, z - b.cz) <= b.maxR;
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

// ── Lane corridors (townLayout is the single source of truth — EM-149) ──────

export interface PathSeg {
  ax: number;
  az: number;
  bx: number;
  bz: number;
}

/**
 * The lane centerlines Ground.tsx draws — the EXACT townLayout graph (spine +
 * connectors, post-avoidance-routing), so every corridor clearance below
 * tracks the real lanes. Pure + deterministic, like everything here.
 */
export function pathSegments(places: Place[]): PathSeg[] {
  return computeTownLayout(places).lanes.map((l) => ({
    ax: l.ax,
    az: l.az,
    bx: l.bx,
    bz: l.bz,
  }));
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
  const bound = wildernessBound(places);
  const out: TreeItem[] = [];
  let attempts = 0;
  let i = 0;
  while (out.length < TREE_COUNT && attempts < TREE_COUNT * 30) {
    attempts++;
    const seed = `treeline-${i++}`;
    const x = (hashUnit(`${seed}-x`) - 0.5) * TREE_SPREAD;
    const z = (hashUnit(`${seed}-z`) - 0.5) * TREE_SPREAD;
    if (!insideWilderness(x, z, bound)) continue; // never on the city ring
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
  const bound = wildernessBound(places);
  const out: ScatterItem[] = [];
  let attempts = 0;
  let i = 0;
  while (out.length < count && attempts < count * 14) {
    attempts++;
    const seed = `${prefix}-${i++}`;
    const x = (hashUnit(`${seed}-x`) - 0.5) * spread;
    const z = (hashUnit(`${seed}-z`) - 0.5) * spread;
    if (!insideWilderness(x, z, bound)) continue; // never on the city ring
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
  // An edge wild place's annulus (≤ BAND_MAX + 5 out) can poke past the
  // core boundary — same clamp as the rest of the wilderness.
  const bound = wildernessBound(places);
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
    if (!insideWilderness(x, z, bound)) continue; // never on the city ring
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

// ── Lamps (gateway lights flanking the lanes) ────────────────────────────────

/**
 * Lamp-spot validity against the place clearance model: never within
 * NEIGHBOR_FLOOR of any place center (the structure itself), and never inside
 * the NEAREST place's building-slot band (BAND_MIN..BAND_MAX) where projects
 * rise — end-of-lane lamps land on the snug LAMP_RING_RADIUS ring
 * (< BAND_MIN) of the lane's terminal place; mid-lane lamps sit ≥ BAND_MAX
 * out. The band rule binds the OWN (nearest) place only: in the dense Wave C
 * districts every inner ring is blanketed by some neighbor's 5.0–10.5 band,
 * so a strict all-places band rule is unsatisfiable (same bound the near-prop
 * law documents above) — NEIGHBOR_FLOOR is the cross-place guard.
 */
export function lampSpotValid(x: number, z: number, centers: WorldPoint[]): boolean {
  let own = Infinity;
  for (const c of centers) {
    const d = Math.hypot(c.x - x, c.z - z);
    if (d < NEIGHBOR_FLOOR) return false;
    if (d < own) own = d;
  }
  return own <= BAND_MIN || own >= BAND_MAX;
}

/**
 * Lamp posts LINE the lanes Ground draws from townLayout's graph: one near
 * each lane end, set deliberately BESIDE the strip — LAMP_PATH_OFFSET
 * (half-width + 0.8) out from the centerline, alternating sides per lane —
 * pulled in along the lane so a lamp at a place-terminated lane end sits on
 * that place's LAMP_RING_RADIUS ring (below SLOT_BASE_RADIUS), exactly like
 * the old spoke gateways. Candidates failing the lamp clearance law, or
 * landing on ANY lane strip proper (a crossing lane's, say), are dropped.
 */
export function layoutLamps(places: Place[]): ScatterItem[] {
  if (places.length < 2) return [];
  const centers = places.map(placeToWorld);
  const segs = pathSegments(places);
  const out: ScatterItem[] = [];
  // distance along the lane that puts an end lamp on the terminal place ring
  const ringIn = Math.sqrt(LAMP_RING_RADIUS ** 2 - LAMP_PATH_OFFSET ** 2);

  const push = (x: number, z: number) => {
    if (out.length >= MAX_LAMPS) return;
    if (!lampSpotValid(x, z, centers)) return;
    // beside its own strip by construction, but never ON any strip
    if (distToNearestPath(x, z, segs) < PATH_HALF_WIDTH + 0.1) return;
    out.push({ x, z, scale: 1, rot: 0 });
  };

  segs.forEach((s, si) => {
    const dx = s.bx - s.ax;
    const dz = s.bz - s.az;
    const len = Math.hypot(dx, dz) || 1;
    if (len < ringIn + 0.8) return; // too short to set a lamp in from the end
    const ux = dx / len;
    const uz = dz / len;
    // perpendicular set-out so the lamp flanks (never blocks) the strip
    const side = si % 2 === 0 ? 1 : -1;
    const px = -uz * LAMP_PATH_OFFSET * side;
    const pz = ux * LAMP_PATH_OFFSET * side;
    // a-end lamp
    push(s.ax + ux * ringIn + px, s.az + uz * ringIn + pz);
    // b-end lamp (only if the lane is long enough for both)
    if (len >= ringIn * 2) push(s.bx - ux * ringIn + px, s.bz - uz * ringIn + pz);
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
