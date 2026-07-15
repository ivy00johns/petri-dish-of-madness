/**
 * travel — pure, frame-agnostic helpers for the multi-city TRAVEL layer
 * (EM-110). An agent with `in_transit_to != null` is OFF-BOARD (0 LLM calls on
 * the backend) — it is NOT inside either city; it renders as a marker gliding
 * along the straight line from its HOME settlement center to its TARGET center.
 *
 * Coordinates here are WORLD-frame (±33) — the same frame `Settlement.center`
 * is stored in (the anti-EM-243 discipline: settlements are converted ONCE,
 * backend-side). The 3D <TravelMarkers> consume these directly; the 2D
 * <WorldMap> converts them world→logical via worldSpace.toLogicalX/Y before it
 * plots them in its logical (0..1000) drawing frame.
 *
 * PROGRESS DERIVATION: the backend does not serialize the depart tick, only
 * `transit_arrival_tick` — but the trip LENGTH is derivable (contract §3:
 * "departTick is derivable"): the backend computes it as a pure function of the
 * two settlement centers, which the snapshot carries. We mirror that formula
 * exactly ({@link tripTicks}), so progress = 1 - remaining/trip spans the whole
 * route for ANY trip length — no parking at the home end on a long trip, no
 * teleporting mid-route on a short one. Pure + deterministic — no clock, no
 * RNG — so a replay renders identically.
 */

import type { Agent, Settlement } from '../../types';

// MIRROR of backend/petridish/engine/world.py (TRAVEL_SPEED / TRAVEL_MIN_TICKS,
// consumed by World.travel_ticks). Both sides must agree or the marker drifts
// off the backend's real ETA — change them TOGETHER.
/** World units crossed per tick (backend world.py TRAVEL_SPEED). */
export const TRAVEL_SPEED = 3.0;
/** Trip-length floor in ticks (backend world.py TRAVEL_MIN_TICKS). */
export const TRAVEL_MIN_TICKS = 3;

/** A world-frame point [x, z]. */
export type XZ = readonly [number, number];

/** True for a render-safe world-frame center (finite [x, z] pair). */
function validCenter(c: unknown): c is [number, number] {
  return (
    Array.isArray(c) &&
    c.length === 2 &&
    Number.isFinite(c[0]) &&
    Number.isFinite(c[1])
  );
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

/**
 * Trip length in ticks between two world-frame centers — the EXACT mirror of
 * backend World.travel_ticks (world.py): max(TRAVEL_MIN_TICKS,
 * ceil(dist / TRAVEL_SPEED)). Pure fn of the two centers, deterministic.
 */
export function tripTicks(from: XZ, to: XZ): number {
  const dist = Math.hypot(to[0] - from[0], to[1] - from[1]);
  return Math.max(TRAVEL_MIN_TICKS, Math.ceil(dist / TRAVEL_SPEED));
}

/**
 * Fraction of the trip completed (0 at home, 1 at the destination), derived
 * from `transit_arrival_tick`, the current `tick`, and the trip length in
 * ticks ({@link tripTicks} of the route's real endpoints). Monotonically
 * non-decreasing in `tick`; reaches 1 exactly at arrival. A missing /
 * non-finite arrival, tick, or trip falls back to the mid-route (0.5) so the
 * marker still reads on the line rather than snapping to an endpoint.
 */
export function travelProgress(
  arrivalTick: number | null | undefined,
  tick: number | null | undefined,
  trip: number,
): number {
  if (!Number.isFinite(arrivalTick) || !Number.isFinite(tick)) return 0.5;
  if (!Number.isFinite(trip) || trip <= 0) return 0.5;
  const remaining = Math.max(0, (arrivalTick as number) - (tick as number));
  return clamp01(1 - remaining / trip);
}

/** One in-transit agent's route marker (all coords WORLD-frame). */
export interface TravelMarker {
  id: string;
  name: string;
  /** Actor profile color (or undefined ⇒ caller's neutral fallback). */
  color?: string;
  /** Home settlement center — the route origin. */
  from: XZ;
  /** Target settlement center — the route destination. */
  to: XZ;
  /** The marker's current world-frame position (lerp(from, to, progress)). */
  pos: XZ;
  /** Target settlement display name (for the "→ X" label). */
  targetName: string;
  /** 0..1 along the route. */
  progress: number;
  /** True when BOTH endpoints resolved (a real line to draw); false ⇒ home
   *  unknown, so from == to (marker sits at the destination, no route line). */
  hasRoute: boolean;
}

/**
 * The travel markers for every agent currently `in_transit_to` a resolvable
 * settlement. Tolerant by construction (never a hole, never a throw):
 *   • an agent NOT in transit is skipped (single-settlement / no-travel worlds
 *     yield [] ⇒ the render is unchanged — no regression);
 *   • an unresolvable / malformed TARGET settlement is skipped (nowhere to go);
 *   • a missing/unresolvable HOME degrades to `from == to` (hasRoute=false) so
 *     the traveler still shows at its destination with its label.
 * Pure: deterministic in agent order, no clock/RNG.
 */
export function travelMarkerEntries(
  agents: readonly Agent[] | null | undefined,
  settlements: Record<string, Settlement> | null | undefined,
  tick: number | null | undefined,
): TravelMarker[] {
  const stl = settlements ?? {};
  const out: TravelMarker[] = [];
  for (const a of agents ?? []) {
    const targetId = a.in_transit_to;
    if (!targetId) continue; // not traveling
    const target = Object.prototype.hasOwnProperty.call(stl, targetId)
      ? stl[targetId]
      : undefined;
    if (!target || !validCenter(target.center)) continue; // nowhere to render
    const to: XZ = [target.center[0], target.center[1]];

    const homeId = a.home_settlement_id;
    const home =
      homeId && Object.prototype.hasOwnProperty.call(stl, homeId)
        ? stl[homeId]
        : undefined;
    const hasRoute = !!home && validCenter(home.center);
    const from: XZ = hasRoute ? [home!.center[0], home!.center[1]] : to;

    // The backend seeded this trip's ETA from the HOME center — or the world
    // origin when home is unknown (world.py travel_ticks) — so measure the
    // mirrored trip length from the same point, not the degraded `from == to`.
    const measureFrom: XZ = hasRoute ? from : [0, 0];
    const progress = travelProgress(
      a.transit_arrival_tick,
      tick,
      tripTicks(measureFrom, to),
    );
    const pos: XZ = [
      from[0] + (to[0] - from[0]) * progress,
      from[1] + (to[1] - from[1]) * progress,
    ];

    out.push({
      id: a.id,
      name: a.name,
      color: a.profile_color,
      from,
      to,
      pos,
      targetName: typeof target.name === 'string' ? target.name : targetId,
      progress,
      hasRoute,
    });
  }
  return out;
}

/** The ids of agents currently in transit (off-board) — the set the in-city
 *  renders (3D villagers, 2D place clusters) must EXCLUDE. Absent field ⇒ never
 *  in the set, so a no-travel world's render is unchanged. */
export function inTransitAgentIds(
  agents: readonly Agent[] | null | undefined,
): Set<string> {
  const s = new Set<string>();
  for (const a of agents ?? []) if (a.in_transit_to) s.add(a.id);
  return s;
}

/**
 * Drop each in-transit agent's cached animated position (3D animMap / 2D
 * posRef). The in-city renderers seed a MISSING id at its current place (the
 * snap-on-new-agent path), so clearing while off-board makes an arrival appear
 * AT its destination city — without this, the stale entry survives the trip
 * and the mesh/dot resumes easing FROM the pre-departure spot, gliding across
 * the whole map on arrival. Idempotent; non-travelers untouched.
 */
export function dropInTransitPositions<V>(
  inTransit: ReadonlySet<string>,
  positions: Map<string, V>,
): void {
  for (const id of inTransit) positions.delete(id);
}
