/**
 * townLayout — pure, deterministic district math (Wave C EM-149, trimmed for
 * Wave D1.5).
 *
 * THE LANES ARE DEAD (contracts/wave-d1.5.md): the sim lives on the city grid
 * now and cityLayout's road network owns every street. `computeTownLayout`
 * keeps its signature for its consumers, but `lanes` and `junctions` are
 * always empty — the spine/MST/avoidance routing machinery is gone.
 *
 * What survives is the DISTRICT layer:
 *   • Places are grouped into DISTRICTS — `place.district` when present
 *     (Wave C towns), else deterministic coordinate clustering (old
 *     snapshots / procgen towns still get zones).
 *   • Per-district GROUND ZONES (centroid + radius + a subtle warm-green
 *     tint) let Ground.tsx wash each neighborhood with its own grass tone.
 *
 * Everything is a pure function of the place list — no randomness, no clock —
 * so the same world yields the same plan every frame, reload, and test run.
 * All output coordinates are WORLD units (placeToWorld).
 *
 * Colors here are WebGL material hexes — the canvas palette is explicitly
 * OUTSIDE the CSS design-token system (Wave B convention; design-token-guard
 * governs DOM/CSS only).
 */

import type { Place } from '../../types';
import { placeToWorld, type WorldPoint } from './worldSpace';

// ── Types (signature kept — lanes/junctions are always empty post-D1.5) ─────

export type LaneKind = 'spine' | 'connector';

export interface LaneSegment {
  ax: number;
  az: number;
  bx: number;
  bz: number;
  kind: LaneKind;
}

/** Retained for the TownLayout signature; never emitted since Wave D1.5. */
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
  /** Always [] since Wave D1.5 — cityLayout's road grid owns the streets. */
  lanes: LaneSegment[];
  /** Always [] since Wave D1.5. */
  junctions: Junction[];
  zones: DistrictZone[];
}

// ── Tunables ─────────────────────────────────────────────────────────────────

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

interface Group {
  key: string;
  members: Place[];
}

function byId(a: Place, b: Place): number {
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
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
function worldCentroid(members: Place[]): WorldPoint {
  let x = 0;
  let z = 0;
  for (const m of members) {
    const w = placeToWorld(m);
    x += w.x;
    z += w.z;
  }
  return { x: x / members.length, z: z / members.length };
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

// ── The town plan ────────────────────────────────────────────────────────────

/**
 * Compute the town plan: district ground zones only. Lanes and junctions are
 * permanently empty since Wave D1.5 — the city grid (cityLayout) owns every
 * street; Ground keeps tinting districts from `zones`.
 */
export function computeTownLayout(places: Place[]): TownLayout {
  if (places.length === 0) return { lanes: [], junctions: [], zones: [] };

  const groups = groupByDistrict(places);

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

  return { lanes: [], junctions: [], zones };
}
