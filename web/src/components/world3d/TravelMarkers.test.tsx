/**
 * TravelMarkers tests (EM-110) — an in-transit agent renders ON THE ROUTE:
 *   • no travelers ⇒ renders NOTHING (a no-travel world is unchanged);
 *   • one traveler ⇒ one marker group, whose floating label + marker sit at a
 *     world-frame position strictly BETWEEN its home and target city centers
 *     (never inside a city), carrying the "{name} → {city}" heading.
 *
 * TravelMarkers uses no hooks, so we call it directly and inspect the returned
 * element tree (headless — no WebGL). The Billboard/Text are drei components;
 * we read their element props, we don't render them.
 */

import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { TravelMarkers, TRAVEL_LABEL_Y } from './TravelMarkers';
import type { Agent, Settlement } from '../../types';

const stl: Record<string, Settlement> = {
  home: { name: 'Hearthford', center: [0, 0] },
  away: { name: 'Larkspur', center: [20, 0] },
};

function agent(over: Partial<Agent>): Agent {
  return {
    id: 'a', name: 'Ada', personality: '', profile: 'p', profile_color: '#ff8800',
    location: 'plaza', energy: 100, credits: 0, mood: 'ok', alive: true,
    zero_energy_turns: 0, beliefs: [], relationships: {},
    ...over,
  } as Agent;
}

/** Flatten a marker group's children to the real elements (drop the false slot). */
function childElements(marker: ReactElement): ReactElement[] {
  const kids = (marker.props as { children: unknown }).children;
  return (Array.isArray(kids) ? kids : [kids]).filter(
    (c): c is ReactElement => !!c && typeof c === 'object',
  );
}

describe('TravelMarkers (EM-110)', () => {
  it('renders NOTHING when no agent is in transit (no regression)', () => {
    expect(
      TravelMarkers({ agents: [agent({ in_transit_to: null })], settlements: stl, tick: 5 }),
    ).toBeNull();
    expect(
      TravelMarkers({ agents: [agent({})], settlements: {}, tick: 0 }),
    ).toBeNull();
  });

  it('renders one route marker for an in-transit agent, on the line between cities', () => {
    const el = TravelMarkers({
      agents: [agent({ id: 'a', in_transit_to: 'away', home_settlement_id: 'home', transit_arrival_tick: 10 })],
      settlements: stl,
      tick: 6,
    }) as ReactElement;
    expect(el).not.toBeNull();
    expect((el as { type: unknown }).type).toBe('group');
    const markers = (el.props as { children: ReactElement[] }).children;
    expect(markers).toHaveLength(1);
    expect((markers[0].props as { name: string }).name).toBe('travel-marker-a');

    // The Billboard (non-host element type) carries the label at the eased pos.
    const kids = childElements(markers[0]);
    const billboard = kids.find((c) => typeof c.type !== 'string');
    expect(billboard).toBeDefined();
    const pos = (billboard!.props as { position: number[] }).position;
    // On the ROUTE: x strictly between the two city centers (0 → 20), not in a city.
    expect(pos[0]).toBeGreaterThan(0);
    expect(pos[0]).toBeLessThan(20);
    expect(pos[1]).toBe(TRAVEL_LABEL_Y);

    // "{name} → {city}" heading.
    const text = (billboard!.props as { children: ReactElement }).children;
    const label = (text.props as { children: string }).children;
    expect(label).toContain('Ada');
    expect(label).toContain('Larkspur');
  });
});
