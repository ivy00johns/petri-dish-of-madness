/**
 * townLayout — pure, deterministic town-planning math for EM-149 (Wave C).
 *
 * Derives the LANE NETWORK (the hub-and-spoke pinwheel is dead) from the
 * place list:
 *
 *   • Places are grouped into DISTRICTS — `place.district` when present
 *     (Wave C towns), else deterministic coordinate clustering (old
 *     snapshots / procgen towns still get lanes).
 *   • A MAIN-LANE SPINE rings the district anchor places (the member nearest
 *     each district's centroid), ordered by angle around the town centroid —
 *     a loop for ≥3 districts, a single street for 2.
 *   • CONNECTOR lanes wire every remaining place into its district via a
 *     Prim-style minimum spanning tree rooted at the anchor — every place
 *     reachable, no orphans, no duplicate segments.
 *   • Lanes route AROUND non-endpoint places: any segment passing within
 *     LANE_PLACE_CLEAR of a place it doesn't terminate at is bent away
 *     (bounded recursion), and the bend becomes a junction.
 *   • Per-district GROUND ZONES (centroid + radius + a subtle warm-green
 *     tint) let Ground.tsx wash each neighborhood with its own grass tone.
 *
 * Everything is a pure function of the place list — no randomness, no clock —
 * so the same world yields the same town plan every frame, reload, and test
 * run. All output coordinates are WORLD units (placeToWorld).
 *
 * Colors here are WebGL material hexes — the canvas palette is explicitly
 * OUTSIDE the CSS design-token system (Wave B convention; design-token-guard
 * governs DOM/CSS only).
 */

import type { Place } from '../../types';
import { placeToWorld, type WorldPoint } from './worldSpace';

// ── Types ────────────────────────────────────────────────────────────────────

export type LaneKind = 'spine' | 'connector';

export interface LaneSegment {
  ax: number;
  az: number;
  bx: number;
  bz: number;
  kind: LaneKind;
}

/** A lane endpoint that gets a round ground patch so corners read finished. */
export interface Junction extends WorldPoint {
  /** Patch radius (scaled from the widest lane meeting here). */
  r: number;
}

export interface DistrictZone {
  /** District name, or `zone-N` for clustered fallback groups. */
  key: string;
  x: number;
  z: number;
  radius: number;
  /** Subtle warm-green ground tint for this district. */
  tint: string;
  /** Member place ids (sorted). */
  placeIds: string[];
}

export interface TownLayout {
  lanes: LaneSegment[];
  junctions: Junction[];
  zones: DistrictZone[];
}

// ── Tunables (world units unless noted) ──────────────────────────────────────

/** Lane strip widths — the spine reads as the main street. */
export const LANE_WIDTHS: Record<LaneKind, number> = {
  spine: 2.3,
  connector: 1.55,
};

/** Warm-toon lane colors (spine a shade deeper so the hierarchy reads). */
export const LANE_COLORS: Record<LaneKind, string> = {
  spine: '#bf9560',
  connector: '#c9a36b',
};

/**
 * Lanes never pass within this distance of a place center they don't
 * terminate at (the place's own structure is ~2 units of footprint).
 */
export const LANE_PLACE_CLEAR = 2.6;

/** How far past the clearance disc a bend point is pushed. */
const BEND_MARGIN = 0.5;

/** Bounded avoidance recursion (documented limit; tests assert the result). */
const MAX_BEND_DEPTH = 3;

/** Junction patch radius as a fraction of the widest lane meeting there. */
const JUNCTION_RADIUS_FACTOR = 0.78;

/**
 * Fallback clustering radius in LOGICAL (0..1000) units: a districtless place
 * joins the nearest group whose centroid is within this; else it founds a new
 * group. Wave C district centroids sit ≥250 apart and intra-district spacing
 * is ≥60, so 170 splits old towns sensibly.
 */
export const FALLBACK_CLUSTER_RADIUS = 170;

/** Zone disc sizing: member spread + padding, floored so tiny zones still read. */
const ZONE_PAD = 4.0;
const ZONE_MIN_RADIUS = 7;

// ── District zone tints ──────────────────────────────────────────────────────

/**
 * Slightly varied warm greens around GOLDEN_HOUR.terrain (#8fb85a) — subtle,
 * toon-banded washes, never a paint-bucket biome look.
 */
export const DISTRICT_TINTS: Record<string, string> = {
  core: '#9cc25e',
  market: '#a6bd55',
  civic: '#85b164',
  residential: '#95bf67',
  farm: '#a9c352',
};

/** Tint cycle for fallback `zone-N` groups (and unknown district names). */
const TINT_CYCLE = ['#9cc25e', '#a6bd55', '#85b164', '#95bf67', '#a9c352'];

/** Resolve a zone tint: known districts map directly, others cycle. */
export function zoneTint(key: string, index: number): string {
  // Own-property check: keys can be arbitrary strings — never resolve
  // 'constructor' etc. through the prototype chain (repo convention).
  if (Object.prototype.hasOwnProperty.call(DISTRICT_TINTS, key)) {
    return DISTRICT_TINTS[key];
  }
  return TINT_CYCLE[((index % TINT_CYCLE.length) + TINT_CYCLE.length) % TINT_CYCLE.length];
}

// ── Internal helpers ─────────────────────────────────────────────────────────

interface Pt {
  x: number;
  z: number;
}

interface Group {
  key: string;
  members: Place[];
}

const EPS = 1e-4;

function byId(a: Place, b: Place): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

function samePt(a: Pt, b: Pt): boolean {
  return Math.abs(a.x - b.x) < EPS && Math.abs(a.z - b.z) < EPS;
}

/** Mean of the members' LOGICAL coordinates. */
function logicalCentroid(members: Place[]): { x: number; y: number } {
  let x = 0;
  let y = 0;
  for (const m of members) {
    x += m.x;
    y += m.y;
  }
  return { x: x / members.length, y: y / members.length };
}

/** Mean of the members' WORLD coordinates. */
function worldCentroid(members: Place[]): Pt {
  let x = 0;
  let z = 0;
  for (const m of members) {
    const w = placeToWorld(m);
    x += w.x;
    z += w.z;
  }
  return { x: x / members.length, z: z / members.length };
}

/** Closest point on segment ab to p, plus the distance. */
function closestOnSeg(p: Pt, a: Pt, b: Pt): { d: number; cx: number; cz: number } {
  const dx = b.x - a.x;
  const dz = b.z - a.z;
  const len2 = dx * dx + dz * dz;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.z - a.z) * dz) / len2));
  const cx = a.x + dx * t;
  const cz = a.z + dz * t;
  return { d: Math.hypot(p.x - cx, p.z - cz), cx, cz };
}

// ── Districts ────────────────────────────────────────────────────────────────

/**
 * Group places into districts. Places carrying `district` group by it;
 * districtless places (old snapshots / procgen) are clustered by coordinate
 * proximity — each (in sorted-id order) joins the nearest existing group
 * whose logical centroid is within FALLBACK_CLUSTER_RADIUS, else it founds a
 * new `zone-N` group. Deterministic: sorted ids, strict-improvement picks.
 */
export function groupByDistrict(places: Place[]): Array<{ key: string; members: Place[] }> {
  const sorted = [...places].sort(byId);
  const byDistrict = new Map<string, Place[]>();
  const orphans: Place[] = [];
  for (const p of sorted) {
    const d = p.district;
    if (typeof d === 'string' && d.length > 0) {
      const list = byDistrict.get(d) ?? [];
      list.push(p);
      byDistrict.set(d, list);
    } else {
      orphans.push(p);
    }
  }

  const groups: Group[] = [...byDistrict.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([key, members]) => ({ key, members }));

  let n = 0;
  for (const p of orphans) {
    let best: Group | null = null;
    let bestD = Infinity;
    for (const g of groups) {
      const c = logicalCentroid(g.members);
      const d = Math.hypot(c.x - p.x, c.y - p.y);
      if (d < bestD - 1e-9) {
        bestD = d;
        best = g;
      }
    }
    if (best && bestD <= FALLBACK_CLUSTER_RADIUS) {
      best.members.push(p);
    } else {
      groups.push({ key: `zone-${n++}`, members: [p] });
    }
  }
  return groups;
}

/** The member nearest the group's logical centroid (ties → smallest id). */
function anchorOf(members: Place[]): Place {
  const c = logicalCentroid(members);
  let best = members[0];
  let bestD = Infinity;
  for (const m of [...members].sort(byId)) {
    const d = Math.hypot(c.x - m.x, c.y - m.y);
    if (d < bestD - 1e-9) {
      bestD = d;
      best = m;
    }
  }
  return best;
}

// ── Connectors (per-district MST) ────────────────────────────────────────────

/**
 * Prim's MST over the district's members, rooted at the anchor: each step
 * attaches the unconnected member closest to ANY connected member. Yields
 * organic branching lanes instead of per-district mini-pinwheels.
 */
function mstEdges(members: Place[], anchor: Place): Array<[Place, Place]> {
  const connected: Place[] = [anchor];
  const rest = [...members].sort(byId).filter((m) => m.id !== anchor.id);
  const edges: Array<[Place, Place]> = [];
  while (rest.length > 0) {
    let bestI = 0;
    let bestFrom = connected[0];
    let bestD = Infinity;
    for (let i = 0; i < rest.length; i++) {
      const rw = placeToWorld(rest[i]);
      for (const c of connected) {
        const cw = placeToWorld(c);
        const d = Math.hypot(rw.x - cw.x, rw.z - cw.z);
        if (d < bestD - 1e-9) {
          bestD = d;
          bestI = i;
          bestFrom = c;
        }
      }
    }
    edges.push([bestFrom, rest[bestI]]);
    connected.push(rest[bestI]);
    rest.splice(bestI, 1);
  }
  return edges;
}

// ── Lane routing (place avoidance) ───────────────────────────────────────────

/**
 * Route a lane from a to b as a polyline that keeps LANE_PLACE_CLEAR from
 * every obstacle (place center) that is not one of its own endpoints: the
 * closest-approach point is pushed radially out of the clearance disc and
 * both halves are re-routed (depth-bounded — tests assert the towns we ship
 * come out fully clear).
 */
function routeAround(a: Pt, b: Pt, obstacles: Pt[], depth: number): Pt[] {
  if (depth < MAX_BEND_DEPTH) {
    for (const o of obstacles) {
      if (samePt(o, a) || samePt(o, b)) continue;
      const { d, cx, cz } = closestOnSeg(o, a, b);
      if (d >= LANE_PLACE_CLEAR) continue;
      let dirX: number;
      let dirZ: number;
      if (d < 1e-6) {
        // Lane runs dead through the center — push perpendicular to the lane.
        const len = Math.hypot(b.x - a.x, b.z - a.z) || 1;
        dirX = -(b.z - a.z) / len;
        dirZ = (b.x - a.x) / len;
      } else {
        dirX = (cx - o.x) / d;
        dirZ = (cz - o.z) / d;
      }
      const push = LANE_PLACE_CLEAR + BEND_MARGIN;
      const bend = { x: o.x + dirX * push, z: o.z + dirZ * push };
      const head = routeAround(a, bend, obstacles, depth + 1);
      const tail = routeAround(bend, b, obstacles, depth + 1);
      return [...head.slice(0, -1), ...tail];
    }
  }
  return [a, b];
}

// ── The town plan ────────────────────────────────────────────────────────────

/**
 * Compute the full town plan: lane graph (spine + connectors, routed around
 * places, deduplicated), junction patches, and district ground zones.
 */
export function computeTownLayout(places: Place[]): TownLayout {
  if (places.length === 0) return { lanes: [], junctions: [], zones: [] };

  const groups = groupByDistrict(places);

  // District ground zones.
  const zones: DistrictZone[] = groups.map((g, i) => {
    const c = worldCentroid(g.members);
    let spread = 0;
    for (const m of g.members) {
      const w = placeToWorld(m);
      spread = Math.max(spread, Math.hypot(w.x - c.x, w.z - c.z));
    }
    return {
      key: g.key,
      x: c.x,
      z: c.z,
      radius: Math.max(ZONE_MIN_RADIUS, spread + ZONE_PAD),
      tint: zoneTint(g.key, i),
      placeIds: g.members.map((m) => m.id).sort(),
    };
  });

  // Raw graph edges (place → place), before avoidance routing.
  const raw: Array<{ a: Pt; b: Pt; kind: LaneKind }> = [];

  // Spine: district anchors ordered by angle around the town centroid.
  const anchors = groups.map((g) => anchorOf(g.members));
  if (anchors.length >= 2) {
    const centroids = groups.map((g) => worldCentroid(g.members));
    const town = {
      x: centroids.reduce((s, c) => s + c.x, 0) / centroids.length,
      z: centroids.reduce((s, c) => s + c.z, 0) / centroids.length,
    };
    const order = groups
      .map((g, i) => ({
        i,
        key: g.key,
        angle: Math.atan2(centroids[i].z - town.z, centroids[i].x - town.x),
      }))
      .sort((a, b) => a.angle - b.angle || (a.key < b.key ? -1 : 1))
      .map((o) => o.i);
    const loop = anchors.length >= 3;
    const last = loop ? order.length : order.length - 1;
    for (let k = 0; k < last; k++) {
      const from = anchors[order[k]];
      const to = anchors[order[(k + 1) % order.length]];
      const aw = placeToWorld(from);
      const bw = placeToWorld(to);
      raw.push({ a: { x: aw.x, z: aw.z }, b: { x: bw.x, z: bw.z }, kind: 'spine' });
    }
  }

  // Connectors: per-district MST rooted at the anchor.
  groups.forEach((g, gi) => {
    for (const [from, to] of mstEdges(g.members, anchors[gi])) {
      const aw = placeToWorld(from);
      const bw = placeToWorld(to);
      raw.push({ a: { x: aw.x, z: aw.z }, b: { x: bw.x, z: bw.z }, kind: 'connector' });
    }
  });

  // Route every edge around non-endpoint places, then dedupe segments.
  const obstacles: Pt[] = places.map((p) => {
    const w = placeToWorld(p);
    return { x: w.x, z: w.z };
  });
  const lanes: LaneSegment[] = [];
  const seen = new Set<string>();
  const segKey = (a: Pt, b: Pt): string => {
    const ka = `${a.x.toFixed(4)},${a.z.toFixed(4)}`;
    const kb = `${b.x.toFixed(4)},${b.z.toFixed(4)}`;
    return ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`;
  };
  for (const edge of raw) {
    const polyline = routeAround(edge.a, edge.b, obstacles, 0);
    for (let i = 0; i < polyline.length - 1; i++) {
      const a = polyline[i];
      const b = polyline[i + 1];
      if (Math.hypot(b.x - a.x, b.z - a.z) < 0.05) continue;
      const key = segKey(a, b);
      if (seen.has(key)) continue;
      seen.add(key);
      lanes.push({ ax: a.x, az: a.z, bx: b.x, bz: b.z, kind: edge.kind });
    }
  }

  // Junction patches at every unique lane endpoint (anchor crossings, bends,
  // and place forecourts) — radius scaled from the widest lane meeting there.
  const junctionWidth = new Map<string, { pt: Pt; width: number }>();
  for (const lane of lanes) {
    for (const pt of [
      { x: lane.ax, z: lane.az },
      { x: lane.bx, z: lane.bz },
    ]) {
      const key = `${pt.x.toFixed(4)},${pt.z.toFixed(4)}`;
      const width = LANE_WIDTHS[lane.kind];
      const prev = junctionWidth.get(key);
      if (!prev || width > prev.width) junctionWidth.set(key, { pt, width });
    }
  }
  const junctions: Junction[] = [...junctionWidth.values()].map(({ pt, width }) => ({
    x: pt.x,
    z: pt.z,
    r: width * JUNCTION_RADIUS_FACTOR,
  }));

  return { lanes, junctions, zones };
}
