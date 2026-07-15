/**
 * travel focus-chain tests (EM-121) — follow-agent-across-cities. The camera's
 * focus resolver chains the LIVE in-city position → the route-marker position
 * → the arrival re-seed, driven by the same helpers the renderers use, so a
 * followed traveler is trackable through a WHOLE journey and every handoff is
 * a resolvable point the camera can EASE toward (never a dropped target, never
 * a snap to origin):
 *   • resident (pre-departure): the animMap entry wins;
 *   • departure: dropInTransitPositions clears the stale entry and the chain
 *     hands off to the route marker, which advances toward the destination;
 *   • arrival: the marker is gone and the destination re-seed wins;
 *   • unresolvable id: null (the camera holds still).
 * Pure functions only; no canvas, no R3F.
 */

import { describe, expect, it } from 'vitest';
import type { Agent, Settlement } from '../../types';
import {
  dropInTransitPositions,
  focusChainPos,
  inTransitAgentIds,
  travelMarkerEntries,
  type XZ,
} from './travel';

const stl: Record<string, Settlement> = {
  home: { name: 'Hearthford', center: [0, 0] },
  away: { name: 'Larkspur', center: [30, 0] }, // dist 30 ⇒ trip 10 ticks
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

/** The route-marker position map CozyWorld derives per snapshot. */
function travelPos(agents: Agent[], tick: number): Map<string, XZ> {
  return new Map(travelMarkerEntries(agents, stl, tick).map((t) => [t.id, t.pos]));
}

describe('focusChainPos (EM-121) — the follow chain across a whole journey', () => {
  it('tracks home pos → route marker → destination pos with no dropped stage', () => {
    const arrival = 20; // trip 10 ⇒ departs at tick 10
    const anim = new Map<string, { x: number; z: number }>([
      ['ada', { x: 1.2, z: -0.8 }], // in-city animated position at HOME
    ]);

    // Stage 1 — resident: the live animated position wins.
    expect(focusChainPos('ada', anim, new Map())).toEqual({ x: 1.2, z: -0.8 });

    // Stage 2 — departure: the snapshot marks Ada in transit; the renderer
    // drops her cached position (dropInTransitPositions) and the chain hands
    // off to the route marker.
    const traveling = [
      agent({
        id: 'ada',
        in_transit_to: 'away',
        home_settlement_id: 'home',
        transit_arrival_tick: arrival,
      }),
    ];
    dropInTransitPositions(inTransitAgentIds(traveling), anim);
    expect(anim.has('ada')).toBe(false);
    const mid = focusChainPos('ada', anim, travelPos(traveling, 15))!;
    expect(mid.x).toBeCloseTo(15, 6); // 5-of-10 ticks remaining ⇒ mid-route
    expect(mid.z).toBeCloseTo(0, 6);

    // …and the marker ADVANCES toward the destination each tick — the eased
    // camera glides along the trip, never parks or teleports.
    let prevRemaining = Infinity;
    for (let tick = 11; tick <= arrival; tick++) {
      const p = focusChainPos('ada', anim, travelPos(traveling, tick))!;
      const remaining = Math.hypot(30 - p.x, 0 - p.z);
      expect(remaining).toBeLessThan(prevRemaining);
      prevRemaining = remaining;
    }
    expect(prevRemaining).toBe(0); // at the arrival tick the marker IS the city

    // Stage 3 — arrival: in_transit_to clears (no marker), and the in-city
    // renderer re-seeds the animated position AT the destination (the
    // snap-on-missing path) — the chain returns the new-city point for the
    // camera to ease into.
    anim.set('ada', { x: 30.9, z: 0.4 });
    expect(focusChainPos('ada', anim, new Map())).toEqual({ x: 30.9, z: 0.4 });
  });

  it('prefers the live in-city position over a marker (residents never track routes)', () => {
    const anim = new Map([['ada', { x: 2, z: 3 }]]);
    const markers = new Map<string, XZ>([['ada', [15, 0]]]);
    expect(focusChainPos('ada', anim, markers)).toEqual({ x: 2, z: 3 });
  });

  it('is null for an unresolvable id — the camera holds, never snaps to origin', () => {
    expect(focusChainPos('ghost', new Map(), new Map())).toBeNull();
  });
});
