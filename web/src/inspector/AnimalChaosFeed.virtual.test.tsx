/**
 * Wave F (EM-194) — AnimalChaosFeed renders a BOUNDED window at 10k events.
 *
 * Before: the panel mapped every matching event into the DOM (the long-session
 * "infinite scroll"). Now the magenta stream is virtualized: rendered rows
 * stay ≤ window + 2×overscan regardless of event volume, while the summary
 * strip still counts the full set.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import AnimalChaosFeed, { ROW_HEIGHT } from './AnimalChaosFeed';
import type { WorldEvent } from '../types';

const TOTAL = 10_000;
// Derive from the component's exported geometry: ROW_HEIGHT, overscan 6
// (VirtualList default), fallback viewport 480.
const MAX_ROWS = Math.ceil(480 / ROW_HEIGHT) + 1 + 2 * 6;

function buildEvents(): WorldEvent[] {
  const out: WorldEvent[] = [];
  for (let i = 0; i < TOTAL; i++) {
    out.push({
      type: 'event',
      seq: i + 1,
      tick: Math.floor(i / 20),
      kind: 'animal_action',
      actor_id: i % 2 === 0 ? 'cat_1' : 'dog_1',
      actor_type: 'animal',
      text: `critter mischief #${i}`,
      payload: { species: i % 2 === 0 ? 'cat' : 'dog', action: 'knock_over' },
    });
  }
  return out.reverse(); // newest-first, the history convention
}

describe('AnimalChaosFeed — bounded rows at 10k events (wave F)', () => {
  it(`mounts ≤ ${MAX_ROWS} DOM rows while counting all ${TOTAL}`, () => {
    const events = buildEvents();
    render(
      <AnimalChaosFeed
        events={events}
        agents={[]}
        profiles={[]}
        currentTick={Math.ceil(TOTAL / 20)}
        maxTick={Math.ceil(TOTAL / 20)}
      />,
    );
    // The summary strip counts the FULL projection (scoping unchanged)…
    expect(screen.getByText(`${TOTAL} animal events`)).toBeInTheDocument();
    // …while the DOM only holds the visible window.
    const rows = screen.getAllByRole('listitem');
    expect(rows.length).toBeLessThanOrEqual(MAX_ROWS);
    expect(rows.length).toBeGreaterThan(0);
    // Newest entry is at the top of the window.
    expect(screen.getByText(`critter mischief #${TOTAL - 1}`)).toBeInTheDocument();
  });
});
