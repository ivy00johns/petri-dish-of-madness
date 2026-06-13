/**
 * Wave F (EM-194) — VirtualList bounded-row rendering.
 * Wave G (EM-197) — extended (not weakened) to variable per-item-kind
 * heights (prefix sums + binary search) and the EM-093 anchoring contract.
 *
 * The contract's structural assertion: with a 10k-item fixture the rendered
 * row count stays ≤ window + 2×overscan, independent of items.length — and
 * scrolling shifts the window instead of growing it.
 */
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { VirtualList } from './VirtualList';

const ITEMS = Array.from({ length: 10_000 }, (_, i) => `item-${i}`);
const ROW_HEIGHT = 40;
const OVERSCAN = 6;
const VIEWPORT = 480; // jsdom can't measure; the component falls back to this.
// window rows = ceil(viewport / rowHeight) + 1 partial row.
const MAX_ROWS = Math.ceil(VIEWPORT / ROW_HEIGHT) + 1 + 2 * OVERSCAN;

function renderList() {
  return render(
    <VirtualList
      items={ITEMS}
      rowHeight={ROW_HEIGHT}
      overscan={OVERSCAN}
      fallbackViewportHeight={VIEWPORT}
      itemKey={(item) => item}
      ariaLabel="ten thousand rows"
      renderRow={(item) => <span>{item}</span>}
    />,
  );
}

describe('VirtualList — bounded rendering at 10k items', () => {
  it(`renders ≤ ${MAX_ROWS} rows out of 10,000`, () => {
    renderList();
    const rows = screen.getAllByRole('listitem');
    expect(rows.length).toBeLessThanOrEqual(MAX_ROWS);
    expect(rows.length).toBeGreaterThan(0);
    expect(screen.getByText('item-0')).toBeInTheDocument();
    expect(screen.queryByText('item-5000')).not.toBeInTheDocument();
  });

  it('keeps scrollbar geometry honest (full-height spacer)', () => {
    renderList();
    const container = screen.getByTestId('virtual-list');
    const spacer = container.firstElementChild as HTMLElement;
    expect(spacer.style.height).toBe(`${10_000 * ROW_HEIGHT}px`);
  });

  it('scrolling SHIFTS the window (still bounded), it does not grow it', () => {
    renderList();
    const container = screen.getByTestId('virtual-list');
    fireEvent.scroll(container, { target: { scrollTop: 5000 * ROW_HEIGHT } });
    const rows = screen.getAllByRole('listitem');
    expect(rows.length).toBeLessThanOrEqual(MAX_ROWS);
    expect(screen.getByText('item-5000')).toBeInTheDocument();
    expect(screen.queryByText('item-0')).not.toBeInTheDocument();
  });
});

// ── Wave G (EM-197): variable per-item-kind heights ──────────────────────────
//
// Deterministic height function: even items are SHORT (40px), odd items TALL
// (96px) — the chaos feed's compact/dialogue split. The bound EXTENDS the
// wave-F invariant with the minimum height as the worst case.

const SHORT = 40;
const TALL = 96;
const varHeight = (item: string) => (Number(item.split('-')[1]) % 2 === 0 ? SHORT : TALL);
const VAR_MAX_ROWS = Math.ceil(VIEWPORT / SHORT) + 1 + 2 * OVERSCAN;

function renderVariableList(extra?: { anchorNewest?: boolean; items?: string[] }) {
  return render(
    <VirtualList
      items={extra?.items ?? ITEMS}
      rowHeight={SHORT}
      itemHeight={varHeight}
      overscan={OVERSCAN}
      fallbackViewportHeight={VIEWPORT}
      itemKey={(item) => item}
      ariaLabel="variable rows"
      anchorNewest={extra?.anchorNewest}
      renderRow={(item) => <span>{item}</span>}
    />,
  );
}

describe('VirtualList — variable per-item-kind heights (wave G)', () => {
  it(`renders ≤ ${VAR_MAX_ROWS} rows out of 10,000 with mixed kinds`, () => {
    renderVariableList();
    const rows = screen.getAllByRole('listitem');
    expect(rows.length).toBeLessThanOrEqual(VAR_MAX_ROWS);
    expect(rows.length).toBeGreaterThan(0);
    expect(screen.getByText('item-0')).toBeInTheDocument();
    expect(screen.queryByText('item-5000')).not.toBeInTheDocument();
  });

  it('every rendered row takes EXACTLY its per-kind height', () => {
    renderVariableList();
    for (const row of screen.getAllByRole('listitem')) {
      const label = (row.textContent ?? '').trim();
      expect((row as HTMLElement).style.height).toBe(`${varHeight(label)}px`);
    }
  });

  it('spacer height is the exact prefix-sum total (scrollbar honesty)', () => {
    renderVariableList();
    const container = screen.getByTestId('virtual-list');
    const spacer = container.firstElementChild as HTMLElement;
    const total = ITEMS.reduce((s, it) => s + varHeight(it), 0);
    expect(spacer.style.height).toBe(`${total}px`);
  });

  it('scrolling lands the binary-searched window on the right items', () => {
    renderVariableList();
    const container = screen.getByTestId('virtual-list');
    // Offset of item-5000 = 2500 SHORT + 2500 TALL rows before it.
    const offset5000 = 2500 * SHORT + 2500 * TALL;
    fireEvent.scroll(container, { target: { scrollTop: offset5000 } });
    const rows = screen.getAllByRole('listitem');
    expect(rows.length).toBeLessThanOrEqual(VAR_MAX_ROWS);
    expect(screen.getByText('item-5000')).toBeInTheDocument();
    expect(screen.queryByText('item-0')).not.toBeInTheDocument();
  });
});

// ── Wave G (EM-197): EM-093 anchoring — reading position never moves ─────────
//
// Newest-first lists PREPEND on live updates. With `anchorNewest`, leaving the
// top edge freezes the rendered item set (the EM-093 frozen-snapshot
// technique: the compensation needed is zero), an "↑ N new" pin counts
// arrivals, and the pin (or a top-edge scroll) thaws + re-pins instantly.

describe('VirtualList — EM-093 anchoring (wave G)', () => {
  it('away-from-edge scroll position survives prepends; the pin counts them', () => {
    const { rerender } = renderVariableList({ anchorNewest: true });
    const container = screen.getByTestId('virtual-list');
    const offset5000 = 2500 * SHORT + 2500 * TALL;
    fireEvent.scroll(container, { target: { scrollTop: offset5000 } });
    expect(screen.getByText('item-5000')).toBeInTheDocument();

    // Live arrivals prepend 3 new items (newest-first convention).
    const grown = ['new-2', 'new-1', 'new-0', ...ITEMS];
    rerender(
      <VirtualList
        items={grown}
        rowHeight={SHORT}
        itemHeight={varHeight}
        overscan={OVERSCAN}
        fallbackViewportHeight={VIEWPORT}
        itemKey={(item) => item}
        ariaLabel="variable rows"
        anchorNewest
        renderRow={(item) => <span>{item}</span>}
      />,
    );

    // The frozen snapshot still renders the SAME window — the reading
    // position cannot move because the row set did not change.
    expect(container.scrollTop).toBe(offset5000);
    expect(screen.getByText('item-5000')).toBeInTheDocument();
    expect(screen.queryByText('new-0')).not.toBeInTheDocument();

    // The pin counts the unseen arrivals.
    expect(screen.getByRole('button', { name: /3 new/i })).toBeInTheDocument();
  });

  it('clicking the pin thaws, jumps to the newest edge instantly, and shows arrivals', () => {
    const { rerender } = renderVariableList({ anchorNewest: true });
    const container = screen.getByTestId('virtual-list');
    fireEvent.scroll(container, { target: { scrollTop: 2500 * SHORT + 2500 * TALL } });
    const grown = ['new-0', ...ITEMS];
    rerender(
      <VirtualList
        items={grown}
        rowHeight={SHORT}
        itemHeight={varHeight}
        overscan={OVERSCAN}
        fallbackViewportHeight={VIEWPORT}
        itemKey={(item) => item}
        ariaLabel="variable rows"
        anchorNewest
        renderRow={(item) => <span>{item}</span>}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /1 new/i }));
    // Instant scrollTop assignment (no smooth-scroll dependence —
    // prefers-reduced-motion safe by construction).
    expect(container.scrollTop).toBe(0);
    expect(screen.getByText('new-0')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /new/i })).not.toBeInTheDocument();
  });

  it('scrolling back to the top edge re-pins (no pin, live arrivals render)', () => {
    const { rerender } = renderVariableList({ anchorNewest: true });
    const container = screen.getByTestId('virtual-list');
    fireEvent.scroll(container, { target: { scrollTop: 5000 } });
    const grown = ['new-0', ...ITEMS];
    rerender(
      <VirtualList
        items={grown}
        rowHeight={SHORT}
        itemHeight={varHeight}
        overscan={OVERSCAN}
        fallbackViewportHeight={VIEWPORT}
        itemKey={(item) => item}
        ariaLabel="variable rows"
        anchorNewest
        renderRow={(item) => <span>{item}</span>}
      />,
    );
    expect(screen.queryByText('new-0')).not.toBeInTheDocument();
    fireEvent.scroll(container, { target: { scrollTop: 0 } });
    expect(screen.getByText('new-0')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /new/i })).not.toBeInTheDocument();
  });
});
