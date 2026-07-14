/**
 * travel tests (EM-110) — the in-transit route-marker helpers:
 *   • travelProgress eases 0→1 as tick→arrival, monotonic, endpoint-exact;
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
  TRAVEL_NOMINAL_TICKS,
  travelProgress,
  travelMarkerEntries,
  inTransitAgentIds,
} from './travel';

const stl: Record<string, Settlement> = {
  home: { name: 'Hearthford', center: [0, 0] },
  away: { name: 'Larkspur', center: [20, 0] },
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

describe('travelProgress (EM-110)', () => {
  it('is 1 exactly at the arrival tick', () => {
    expect(travelProgress(10, 10)).toBe(1);
  });

  it('eases up monotonically as the arrival tick nears', () => {
    const arrival = 10;
    const a = travelProgress(arrival, 10 - TRAVEL_NOMINAL_TICKS); // just departed
    const b = travelProgress(arrival, 10 - TRAVEL_NOMINAL_TICKS / 2);
    const c = travelProgress(arrival, 10 - 1);
    expect(a).toBeLessThan(b);
    expect(b).toBeLessThan(c);
    expect(c).toBeLessThan(1);
    expect(a).toBeGreaterThanOrEqual(0);
  });

  it('clamps to [0,1] for a long trip / overshoot', () => {
    expect(travelProgress(100, 0)).toBe(0);      // far from arrival ⇒ pinned home
    expect(travelProgress(5, 999)).toBe(1);      // past arrival ⇒ pinned target
  });

  it('falls back to mid-route when arrival/tick is missing', () => {
    expect(travelProgress(null, 5)).toBe(0.5);
    expect(travelProgress(10, null)).toBe(0.5);
  });
});

describe('travelMarkerEntries (EM-110)', () => {
  it('renders a traveler on the route between home and target centers', () => {
    const arrival = 10;
    const tick = arrival - TRAVEL_NOMINAL_TICKS / 2; // mid trip
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
