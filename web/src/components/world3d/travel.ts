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
 * PROGRESS APPROXIMATION (v1): the backend does not serialize the depart tick,
 * only `transit_arrival_tick`. We interpolate against a fixed nominal trip
 * length (contract §3: "interpolate from transit_arrival_tick + a constant"),
 * so the marker eases toward the destination as arrival approaches and lands
 * exactly at the target on the arrival tick. A trip longer than the nominal
 * simply pins at the home end until it comes within NOMINAL ticks of arriving.
 * Pure + deterministic — no clock, no RNG — so a replay renders identically.
 */

import type { Agent, Settlement } from '../../types';

/**
 * The assumed trip length (ticks) used to interpolate marker progress from the
 * only travel field the snapshot carries (`transit_arrival_tick`). Tuned to the
 * contract's "a cross-map trip is ~a few rounds" — long enough that a typical
 * trip visibly animates, short enough that the marker isn't parked at home.
 */
export const TRAVEL_NOMINAL_TICKS = 8;

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
 * Fraction of the trip completed (0 at home, 1 at the destination), derived from
 * `transit_arrival_tick` and the current `tick` against {@link TRAVEL_NOMINAL_TICKS}.
 * Monotonically non-decreasing in `tick`; reaches 1 exactly at arrival. A missing
 * / non-finite arrival or tick falls back to the mid-route (0.5) so the marker
 * still reads on the line rather than snapping to an endpoint.
 */
export function travelProgress(
  arrivalTick: number | null | undefined,
  tick: number | null | undefined,
  nominal: number = TRAVEL_NOMINAL_TICKS,
): number {
  if (!Number.isFinite(arrivalTick) || !Number.isFinite(tick)) return 0.5;
  const remaining = Math.max(0, (arrivalTick as number) - (tick as number));
  return clamp01((nominal - remaining) / nominal);
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

    const progress = travelProgress(a.transit_arrival_tick, tick);
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
