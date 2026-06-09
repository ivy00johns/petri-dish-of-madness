/**
 * EventFeed frozen-snapshot scroll stability (W11a EM-093, contract §9).
 *
 * The mechanism is a literal row-set freeze — NOT scrollTop compensation — so
 * it is unit-testable without simulating real scroll geometry: we drive the
 * component's own onScroll handler (jsdom fires the event; scrollTop is
 * defined per-element since jsdom does no layout) and assert on the RENDERED
 * ROW SET, which is the whole contract:
 *   • un-pinned = the displayed rows are a frozen snapshot; arrivals (and the
 *     upstream 200-cap trim) mutate nothing;
 *   • the "X new" pill counts arrivals by seq SET MEMBERSHIP (a trim must not
 *     under/over-count);
 *   • clicking the pill — or scrolling back to the top — thaws and re-pins;
 *   • changing a filter while frozen re-pins too.
 * What is NOT covered here (honestly): real viewport pixel stability under
 * browser layout — that is gate-3 Playwright territory.
 */
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EventFeed } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';
import type { WorldEvent } from '../../types';

beforeAll(() => {
  // jsdom has no Element.scrollTo; the jump-to-newest handler calls it.
  Element.prototype.scrollTo = vi.fn();
});

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the feed persists its filter focus
});

function speech(text: string, tick: number): WorldEvent {
  return ev({ kind: 'agent_speech', tick, actor_id: 'a1', text });
}

/** The scrollable list container (the element owning onScroll). */
function scroller(container: HTMLElement): HTMLElement {
  const el = container.querySelector('.overflow-y-auto');
  if (!(el instanceof HTMLElement)) throw new Error('feed scroller not found');
  return el;
}

/** Simulate the reader sitting at `top` px and fire the scroll handler.
 * Installed as a real getter/setter pair (jsdom does no layout) so the
 * component's own pin-to-top `el.scrollTop = 0` write keeps working. */
function scrollTo(el: HTMLElement, top: number) {
  let current = top;
  Object.defineProperty(el, 'scrollTop', {
    configurable: true,
    get: () => current,
    set: (v: number) => { current = v; },
  });
  fireEvent.scroll(el);
}

describe('EventFeed — EM-093 frozen snapshot', () => {
  it('freezes the row set when scrolled away: arrivals mutate nothing', () => {
    const initial = [speech('third', 3), speech('second', 2), speech('first', 1)];
    const { container, rerender } = render(<EventFeed events={initial} />);
    expect(screen.getByText('LIVE')).toBeInTheDocument();

    scrollTo(scroller(container), 120);
    expect(screen.getByText('PAUSED')).toBeInTheDocument();

    // Two arrivals while scrolled away (newest-first prop order).
    rerender(
      <EventFeed events={[speech('fifth', 5), speech('fourth', 4), ...initial]} />,
    );

    // The frozen snapshot renders EXACTLY the old rows — no prepend, no shift.
    expect(screen.queryByText('fifth')).not.toBeInTheDocument();
    expect(screen.queryByText('fourth')).not.toBeInTheDocument();
    expect(screen.getByText('third')).toBeInTheDocument();
    expect(screen.getByText('first')).toBeInTheDocument();

    // The pill counts the unseen arrivals.
    expect(screen.getByRole('button', { name: '↑ 2 new' })).toBeInTheDocument();
  });

  it('counts unseen by seq set membership, immune to the 200-cap trim', () => {
    const e1 = speech('first', 1);
    const e2 = speech('second', 2);
    const e3 = speech('third', 3);
    const { container, rerender } = render(<EventFeed events={[e3, e2, e1]} />);
    scrollTo(scroller(container), 120);

    // Upstream cap trims the oldest row while two new ones arrive: the length
    // delta is 1, but the true arrival count is 2 — set membership must win.
    rerender(<EventFeed events={[speech('fifth', 5), speech('fourth', 4), e3, e2]} />);
    expect(screen.getByRole('button', { name: '↑ 2 new' })).toBeInTheDocument();
    // And the trimmed-away row is STILL rendered (the snapshot is literal).
    expect(screen.getByText('first')).toBeInTheDocument();
  });

  it('clicking the pill thaws, re-pins, and shows the arrivals', async () => {
    const user = userEvent.setup();
    const initial = [speech('second', 2), speech('first', 1)];
    const { container, rerender } = render(<EventFeed events={initial} />);
    scrollTo(scroller(container), 120);
    rerender(<EventFeed events={[speech('third', 3), ...initial]} />);

    await user.click(screen.getByRole('button', { name: '↑ 1 new' }));

    expect(screen.getByText('LIVE')).toBeInTheDocument();
    expect(screen.getByText('third')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /new$/ })).not.toBeInTheDocument();
  });

  it('scrolling back to the top thaws and re-pins without the pill', () => {
    const initial = [speech('second', 2), speech('first', 1)];
    const { container, rerender } = render(<EventFeed events={initial} />);
    const el = scroller(container);
    scrollTo(el, 120);
    rerender(<EventFeed events={[speech('third', 3), ...initial]} />);
    expect(screen.getByText('PAUSED')).toBeInTheDocument();

    scrollTo(el, 0); // within TOP_THRESHOLD = the live edge
    expect(screen.getByText('LIVE')).toBeInTheDocument();
    expect(screen.getByText('third')).toBeInTheDocument();
  });

  it('changing a filter while frozen re-pins (no unpredictable jump)', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <EventFeed events={[speech('hello', 1)]} />,
    );
    scrollTo(scroller(container), 120);
    expect(screen.getByText('PAUSED')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Chat/ }));
    expect(screen.getByText('LIVE')).toBeInTheDocument();
  });
});
