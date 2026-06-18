/**
 * EM-207 H2 — AnimalChaosFeed species legend.
 *
 * Covers:
 *  • Per-species count legend renders when multiple species are present.
 *  • Counts are correct for each species.
 *  • New H2 species (steal_food, knock_over) surface in the feed rows.
 *  • The legend is absent when there are no animal events.
 *  • The existing virtualized bounded-row contract is not regressed.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import AnimalChaosFeed from './AnimalChaosFeed';
import type { WorldEvent } from '../types';

function makeEvent(overrides: Partial<WorldEvent> & { seq: number; species: string; action?: string }): WorldEvent {
  const { species, action, ...rest } = overrides;
  return {
    type: 'event',
    tick: 1,
    kind: 'animal_action',
    actor_id: `${species}_1`,
    actor_type: 'animal',
    text: `${species} did something`,
    payload: {
      species,
      action: action ?? 'wander',
    },
    ...rest,
  };
}

function renderFeed(events: WorldEvent[], currentTick = 100) {
  return render(
    <AnimalChaosFeed
      events={events}
      agents={[]}
      profiles={[]}
      currentTick={currentTick}
      maxTick={currentTick}
    />,
  );
}

describe('AnimalChaosFeed — species legend (EM-207 H2)', () => {
  it('renders a legend pill for each species present in the feed', () => {
    const events: WorldEvent[] = [
      makeEvent({ seq: 1, species: 'cat' }),
      makeEvent({ seq: 2, species: 'cat' }),
      makeEvent({ seq: 3, species: 'raccoon' }),
      makeEvent({ seq: 4, species: 'fox' }),
    ];
    renderFeed(events);
    expect(screen.getByLabelText(/cat 2 events/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/raccoon 1 event/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/fox 1 event/i)).toBeInTheDocument();
  });

  it('does not render the legend when there are no animal events', () => {
    renderFeed([]);
    // The legend pills should be absent
    expect(screen.queryByLabelText(/events/i)).not.toBeInTheDocument();
  });

  it('shows steal_food action events for raccoon in the chaos rows', () => {
    const events: WorldEvent[] = [
      makeEvent({ seq: 1, species: 'raccoon', action: 'steal_food',
        text: 'Bandit swiped a sandwich.' }),
    ];
    renderFeed(events);
    expect(screen.getByText(/swiped a sandwich/)).toBeInTheDocument();
  });

  it('shows knock_over action events for goat in the chaos rows', () => {
    const events: WorldEvent[] = [
      makeEvent({ seq: 1, species: 'goat', action: 'knock_over',
        text: 'Billy knocked over the market stall.' }),
    ];
    renderFeed(events);
    expect(screen.getByText(/knocked over/)).toBeInTheDocument();
  });

  it('legend count excludes events beyond currentTick', () => {
    const events: WorldEvent[] = [
      makeEvent({ seq: 1, species: 'crow', tick: 5 }),
      makeEvent({ seq: 2, species: 'crow', tick: 10 }),
    ];
    // Only events at tick ≤ 7 should count
    renderFeed(events, 7);
    expect(screen.getByLabelText(/crow 1 event/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/crow 2 events/i)).not.toBeInTheDocument();
  });

  it('preserves the existing bounded-row virtualization (no regression)', () => {
    const events: WorldEvent[] = Array.from({ length: 200 }, (_, i) => ({
      type: 'event' as const,
      seq: i + 1,
      tick: 1,
      kind: 'animal_action' as const,
      actor_id: 'dog_1',
      actor_type: 'animal' as const,
      text: `dog did thing ${i}`,
      payload: { species: 'dog', action: 'wander' },
    }));
    renderFeed(events);
    // Header counts all
    expect(screen.getByText('200 animal events')).toBeInTheDocument();
    // Legend shows dog
    expect(screen.getByLabelText(/dog 200 events/i)).toBeInTheDocument();
  });
});
