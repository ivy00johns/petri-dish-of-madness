/**
 * VirtualList (wave F, EM-194) — a hand-rolled fixed-row-height window.
 *
 * The inspector's high-volume lists (Animal Chaos Feed, Decision Trace turn
 * rail) used to mount EVERY matching event as a DOM row — tens of thousands
 * of nodes on a long session. This renders only the rows intersecting the
 * scroll viewport (± `overscan`), positioned absolutely inside a full-height
 * spacer so the scrollbar geometry is identical to the naive list.
 *
 * Dependency choice (contract global rule): hand-rolled over
 * @tanstack/react-virtual / react-window — the surfaces here are fine with a
 * FIXED row height, which makes windowing ~40 lines of arithmetic; zero new
 * vendor code, no dynamic-measurement machinery, trivially testable in jsdom
 * (the unmeasurable container falls back to `fallbackViewportHeight`).
 *
 * Rendered-row bound (asserted in VirtualList.test.tsx):
 *   rows ≤ ceil(viewport / rowHeight) + 1 + 2 * overscan, independent of
 *   items.length.
 *
 * The only inline styles are the DYNAMIC windowing geometry (heights/offsets
 * computed from props/scroll state) — no hardcoded design literals.
 */

import { useEffect, useRef, useState } from 'react';
import type { ReactNode, UIEvent } from 'react';

export interface VirtualListProps<T> {
  items: T[];
  /** Fixed row height in px — every row is clamped to exactly this. */
  rowHeight: number;
  /** Stable React key per item (seq / turn id …). */
  itemKey: (item: T, index: number) => string | number;
  renderRow: (item: T, index: number) => ReactNode;
  /** Extra rows rendered above/below the viewport (default 6). */
  overscan?: number;
  /** Classes for the scroll container (the panel supplies flex/border). */
  className?: string;
  /** Viewport height used until the container measures (jsdom/tests). */
  fallbackViewportHeight?: number;
  /** Accessible label for the list. */
  ariaLabel?: string;
}

export function VirtualList<T>({
  items,
  rowHeight,
  itemKey,
  renderRow,
  overscan = 6,
  className = '',
  fallbackViewportHeight = 480,
  ariaLabel,
}: VirtualListProps<T>) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(fallbackViewportHeight);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      // jsdom (and a not-yet-laid-out container) reports 0 — keep the fallback.
      setViewport(el.clientHeight || fallbackViewportHeight);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallbackViewportHeight]);

  const total = items.length;
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const end = Math.min(total, Math.ceil((scrollTop + viewport) / rowHeight) + overscan);
  const visible = items.slice(start, end);

  const onScroll = (e: UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  };

  return (
    <div
      ref={containerRef}
      onScroll={onScroll}
      className={`overflow-y-auto ${className}`}
      data-testid="virtual-list"
    >
      {/* Full-height spacer: scrollbar geometry matches the unvirtualized list. */}
      <div style={{ height: total * rowHeight, position: 'relative' }}>
        <ul
          role="list"
          aria-label={ariaLabel}
          className="m-0 p-0 list-none"
          style={{
            position: 'absolute',
            top: start * rowHeight,
            left: 0,
            right: 0,
          }}
        >
          {visible.map((item, i) => (
            <li
              key={itemKey(item, start + i)}
              style={{ height: rowHeight, overflow: 'hidden' }}
            >
              {renderRow(item, start + i)}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
