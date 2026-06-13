/**
 * Wave F (EM-194), extended wave G (EM-197) — AnimalChaosFeed renders a
 * BOUNDED window at 10k events, now with PER-KIND row heights.
 *
 * Before wave F the panel mapped every matching event into the DOM (the
 * long-session "infinite scroll"). Wave F virtualized it at a fixed 96px.
 * Wave G makes the heights per-kind: dialogue rows (an animal_thought
 * present) KEEP the 96px two-line inline treatment; LLM-call / no-dialogue
 * rows shrink to the 40px compact line. The wave-F bound is EXTENDED to the
 * variable case (minimum row height drives the formula), never weakened:
 * rendered rows stay ≤ ceil(viewport / minRowHeight) + 1 + 2×overscan
 * regardless of event volume, while the header still counts the full set.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import AnimalChaosFeed, {
  ROW_HEIGHT,
  COMPACT_ROW_HEIGHT,
  chaosRowHeight,
} from './AnimalChaosFeed';
import type { WorldEvent } from '../types';

const TOTAL = 10_000;
// Derive from the component's exported geometry: overscan 6 (VirtualList
// default), fallback viewport 480. The bound uses the MINIMUM per-kind height
// (the worst case: a window of all-compact rows) — strictly more demanding
// than the wave-F fixed-96px bound ever was.
const MAX_ROWS = Math.ceil(480 / COMPACT_ROW_HEIGHT) + 1 + 2 * 6;

/** Even seq = dialogue (96px), odd = compact no-dialogue (40px). */
function buildEvents(withDialogue: boolean): WorldEvent[] {
  const out: WorldEvent[] = [];
  for (let i = 0; i < TOTAL; i++) {
    const dialogue = withDialogue && i % 2 === 0;
    out.push({
      type: 'event',
      seq: i + 1,
      tick: Math.floor(i / 20),
      kind: 'animal_action',
      actor_id: i % 2 === 0 ? 'cat_1' : 'dog_1',
      actor_type: 'animal',
      text: `critter mischief #${i}`,
      payload: {
        species: i % 2 === 0 ? 'cat' : 'dog',
        action: 'knock_over',
        ...(dialogue ? { animal_thought: `That tall thing offends me (#${i}).` } : {}),
      },
    });
  }
  return out.reverse(); // newest-first, the history convention
}

function renderFeed(events: WorldEvent[]) {
  return render(
    <AnimalChaosFeed
      events={events}
      agents={[]}
      profiles={[]}
      currentTick={Math.ceil(TOTAL / 20)}
      maxTick={Math.ceil(TOTAL / 20)}
    />,
  );
}

describe('AnimalChaosFeed — bounded rows at 10k events (wave F, extended wave G)', () => {
  it(`mounts ≤ ${MAX_ROWS} DOM rows while counting all ${TOTAL}`, () => {
    renderFeed(buildEvents(false));
    // The header counts the FULL projection (scoping unchanged)…
    expect(screen.getByText(`${TOTAL} animal events`)).toBeInTheDocument();
    // …while the DOM only holds the visible window.
    const rows = screen.getAllByRole('listitem');
    expect(rows.length).toBeLessThanOrEqual(MAX_ROWS);
    expect(rows.length).toBeGreaterThan(0);
    // Newest entry is at the top of the window.
    expect(screen.getByText(`critter mischief #${TOTAL - 1}`)).toBeInTheDocument();
  });

  it('mixed dialogue/compact rows stay bounded AND take their per-kind heights', () => {
    renderFeed(buildEvents(true));
    const rows = screen.getAllByRole('listitem');
    expect(rows.length).toBeLessThanOrEqual(MAX_ROWS);
    expect(rows.length).toBeGreaterThan(0);

    // Every rendered row's height matches the deterministic per-kind function:
    // dialogue rows two-line 96px (the kept user-requested inline dialogue),
    // no-dialogue rows the 40px compact line.
    const heights = new Set<string>();
    for (const row of rows) heights.add((row as HTMLElement).style.height);
    expect(heights).toEqual(new Set([`${ROW_HEIGHT}px`, `${COMPACT_ROW_HEIGHT}px`]));

    // Dialogue still reads INLINE (commit 99f3822) — the newest even-seq
    // entry's thought is in the DOM, not only in a title attribute.
    expect(
      screen.getByText(`“That tall thing offends me (#${TOTAL - 2}).”`),
    ).toBeInTheDocument();
  });

  it('chaosRowHeight is a pure per-kind function (dialogue 96 / compact 40)', () => {
    const [dialogue, compact] = [buildEvents(true)[1], buildEvents(true)[0]];
    // buildEvents reverses: index 0 = #9999 (odd, compact), 1 = #9998 (dialogue)
    expect(chaosRowHeight(dialogue)).toBe(ROW_HEIGHT);
    expect(chaosRowHeight(compact)).toBe(COMPACT_ROW_HEIGHT);
  });
});
