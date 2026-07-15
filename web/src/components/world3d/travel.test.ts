/**
 * travel tests (EM-110) — the in-transit route-marker helpers:
 *   • tripTicks mirrors the backend's travel_ticks formula exactly, so
 *     travelProgress eases 0→1 over the trip's REAL length (no parking at the
 *     home end on long trips, no mid-route teleport on short ones), monotonic,
 *     endpoint-exact;
 *   • travelMarkerEntries puts a traveler ON THE ROUTE between home + target
 *     centers (never inside a city), excludes non-travelers, and degrades
 *     tolerantly on a missing/unknown settlement — never a hole, never a throw;
 *   • inTransitAgentIds is the off-board exclusion set (empty for a no-travel
 *     world ⇒ the in-city render is unchanged).
 * Pure functions only; no canvas, no R3F.
 */

import { describe, expect, it } from 'vitest';
import type { Agent, Settlement } from '../../types';
import {
  TRAVEL_SPEED,
  TRAVEL_MIN_TICKS,
  tripTicks,
  travelProgress,
  travelMarkerEntries,
  inTransitAgentIds,
  dropInTransitPositions,
} from './travel';

const stl: Record<string, Settlement> = {
  home: { name: 'Hearthford', center: [0, 0] },
  away: { name: 'Larkspur', center: [20, 0] },  // dist 20 ⇒ trip 7 ticks
  far: { name: 'Duskmere', center: [60, 0] },   // dist 60 ⇒ trip 20 ticks
};

// Minimal Agent factory — only the fields the travel helpers read.
function agent(over: Partial<Agent>): Agent {
  return {
    id: 'a', name: 'Ada', personality: '', profile: 'p', location: 'plaza',
    energy: 100, credits: 0, mood: 'ok', alive: true, zero_energy_turns: 0,
    beliefs: [], relationships: {},
    ...over,
  } as Agent;
}

describe('tripTicks (backend world.py travel_ticks mirror)', () => {
  it('is ceil(dist / TRAVEL_SPEED), floored at TRAVEL_MIN_TICKS', () => {
    expect(tripTicks([0, 0], [20, 0])).toBe(Math.ceil(20 / TRAVEL_SPEED)); // 7
    expect(tripTicks([0, 0], [60, 0])).toBe(Math.ceil(60 / TRAVEL_SPEED)); // 20
    expect(tripTicks([0, 0], [0, 0])).toBe(TRAVEL_MIN_TICKS);   // zero dist ⇒ floor
    expect(tripTicks([0, 0], [1, 0])).toBe(TRAVEL_MIN_TICKS);   // adjacent ⇒ floor
    expect(tripTicks([-3, -4], [0, 0])).toBe(TRAVEL_MIN_TICKS); // dist 5 ⇒ ceil 2 < floor
  });
});

describe('travelProgress (EM-110)', () => {
  it('is 1 exactly at the arrival tick', () => {
    expect(travelProgress(10, 10, 7)).toBe(1);
  });

  it('eases up monotonically as the arrival tick nears', () => {
    const trip = 8;
    const arrival = 10;
    const a = travelProgress(arrival, 10 - trip, trip); // just departed
    const b = travelProgress(arrival, 10 - trip / 2, trip);
    const c = travelProgress(arrival, 10 - 1, trip);
    expect(a).toBeLessThan(b);
    expect(b).toBeLessThan(c);
    expect(c).toBeLessThan(1);
    expect(a).toBeGreaterThanOrEqual(0);
  });

  it('spans a LONG trip instead of parking at the home end (C2 regression)', () => {
    // trip 20 (dist 60): halfway through, the old fixed-nominal-8 interpolation
    // clamped to 0 (marker parked AT the home city for half the trip).
    expect(travelProgress(30, 20, 20)).toBe(0.5);
  });

  it('starts a SHORT trip at 0 instead of teleporting down the route (C2 regression)', () => {
    // trip 3 (the floor): at the depart tick the old fixed-nominal-8
    // interpolation read (8-3)/8 = 0.625 — a teleport 62% down the route.
    expect(travelProgress(13, 10, 3)).toBe(0);
  });

  it('clamps to [0,1] for pre-depart / overshoot ticks', () => {
    expect(travelProgress(100, 0, 8)).toBe(0);   // far from arrival ⇒ pinned home
    expect(travelProgress(5, 999, 8)).toBe(1);   // past arrival ⇒ pinned target
  });

  it('falls back to mid-route when arrival/tick/trip is unusable', () => {
    expect(travelProgress(null, 5, 8)).toBe(0.5);
    expect(travelProgress(10, null, 8)).toBe(0.5);
    expect(travelProgress(10, 5, 0)).toBe(0.5);
    expect(travelProgress(10, 5, Number.NaN)).toBe(0.5);
  });
});

describe('travelMarkerEntries (EM-110)', () => {
  it('renders a traveler on the route between home and target centers', () => {
    const arrival = 10;
    const tick = arrival - 3; // mid trip (trip = 7)
    const out = travelMarkerEntries(
      [agent({ id: 'a', name: 'Ada', in_transit_to: 'away', home_settlement_id: 'home', transit_arrival_tick: arrival })],
      stl,
      tick,
    );
    expect(out).toHaveLength(1);
    const m = out[0];
    expect(m.hasRoute).toBe(true);
    expect(m.from).toEqual([0, 0]);
    expect(m.to).toEqual([20, 0]);
    expect(m.targetName).toBe('Larkspur');
    // pos strictly BETWEEN the endpoints (on the route, not inside a city).
    expect(m.pos[0]).toBeGreaterThan(0);
    expect(m.pos[0]).toBeLessThan(20);
    expect(m.pos[1]).toBe(0);
    // Interpolated against the trip's REAL length: 4/7 of the way at 3-of-7
    // ticks remaining.
    expect(m.progress).toBeCloseTo(4 / 7, 6);
  });

  it('keeps a LONG trip on the route — never parked inside a city (C2 regression)', () => {
    // trip 20 (home → far): halfway through, the old fixed-nominal-8 progress
    // clamped to 0 and drew the marker AT the home settlement center —
    // contract §3 forbids rendering inside either city.
    const out = travelMarkerEntries(
      [agent({ id: 'a', name: 'Ada', in_transit_to: 'far', home_settlement_id: 'home', transit_arrival_tick: 30 })],
      stl,
      20,
    );
    expect(out).toHaveLength(1);
    const m = out[0];
    expect(m.progress).toBeCloseTo(0.5, 6);
    expect(m.pos[0]).toBeCloseTo(30, 6); // mid-route, strictly between 0 and 60
    expect(m.pos[0]).toBeGreaterThan(0);
    expect(m.pos[0]).toBeLessThan(60);
  });

  it('excludes agents that are not traveling', () => {
    const out = travelMarkerEntries(
      [agent({ id: 'x', in_transit_to: null }), agent({ id: 'y' })],
      stl,
      5,
    );
    expect(out).toHaveLength(0);
  });

  it('skips a traveler whose TARGET settlement is unknown (nowhere to render)', () => {
    const out = travelMarkerEntries(
      [agent({ id: 'a', in_transit_to: 'ghost', home_settlement_id: 'home', transit_arrival_tick: 10 })],
      stl,
      5,
    );
    expect(out).toHaveLength(0);
  });

  it('degrades to the destination (no route line) when HOME is unknown', () => {
    const out = travelMarkerEntries(
      [agent({ id: 'a', in_transit_to: 'away', home_settlement_id: null, transit_arrival_tick: 10 })],
      stl,
      5,
    );
    expect(out).toHaveLength(1);
    expect(out[0].hasRoute).toBe(false);
    expect(out[0].from).toEqual(out[0].to); // from == to ⇒ marker sits at target
  });

  it('tolerates absent settlements / agents ⇒ []', () => {
    expect(travelMarkerEntries(undefined, undefined, 0)).toEqual([]);
    expect(travelMarkerEntries([], null, 0)).toEqual([]);
  });
});

describe('inTransitAgentIds (EM-110)', () => {
  it('collects only the in-transit agents (the off-board exclusion set)', () => {
    const ids = inTransitAgentIds([
      agent({ id: 'a', in_transit_to: 'away' }),
      agent({ id: 'b', in_transit_to: null }),
      agent({ id: 'c' }),
    ]);
    expect([...ids]).toEqual(['a']);
  });

  it('is empty for a no-travel world (in-city render unchanged)', () => {
    expect(inTransitAgentIds([agent({ id: 'a' }), agent({ id: 'b' })]).size).toBe(0);
    expect(inTransitAgentIds(undefined).size).toBe(0);
  });
});

describe('dropInTransitPositions (C12 regression)', () => {
  it('clears only the travelers, so an arrival re-seeds AT its new city', () => {
    // The renderers seed a MISSING id at its current place; a surviving stale
    // entry made the arrival glide cross-map from the pre-departure spot.
    const positions = new Map([
      ['a', { x: 1, z: 2 }], // in transit — must be dropped
      ['b', { x: 3, z: 4 }], // resident — untouched
    ]);
    dropInTransitPositions(inTransitAgentIds([
      agent({ id: 'a', in_transit_to: 'away' }),
      agent({ id: 'b' }),
    ]), positions);
    expect(positions.has('a')).toBe(false);
    expect(positions.get('b')).toEqual({ x: 3, z: 4 });
  });

  it('is a no-op for an empty in-transit set (no-travel world unchanged)', () => {
    const positions = new Map([['a', { x: 1, z: 2 }]]);
    dropInTransitPositions(new Set<string>(), positions);
    expect(positions.size).toBe(1);
  });
});
