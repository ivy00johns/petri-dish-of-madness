/**
 * Wave F (EM-194) — VirtualList bounded-row rendering.
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
