/**
 * VirtualList (wave F EM-194, extended wave G EM-197) — a hand-rolled window.
 *
 * The inspector's high-volume lists (Animal Chaos Feed, Decision Trace turn
 * rail) used to mount EVERY matching event as a DOM row — tens of thousands
 * of nodes on a long session. This renders only the rows intersecting the
 * scroll viewport (± `overscan`), positioned absolutely inside a full-height
 * spacer so the scrollbar geometry is identical to the naive list.
 *
 * Dependency choice (contract global rule): hand-rolled over
 * @tanstack/react-virtual / react-window — zero new vendor code, no
 * dynamic-measurement machinery, trivially testable in jsdom (the
 * unmeasurable container falls back to `fallbackViewportHeight`).
 *
 * Wave G (EM-197) extensions:
 *
 *  • PER-ITEM-KIND HEIGHTS — `itemHeight(item, index)` is a DETERMINISTIC
 *    height function (a row's height depends only on its data kind, never on
 *    measurement). Offsets are prefix sums computed once per items change;
 *    the window start is found by binary search. The wave-F bounded-rows
 *    invariant still holds with `rowHeight` as the minimum row height:
 *      rows ≤ ceil(viewport / minRowHeight) + 1 + 2 * overscan.
 *
 *  • SCROLL ANCHORING (`anchorNewest`, the EM-093 live-feed technique) —
 *    these lists are newest-first, so data updates PREPEND at the top. While
 *    the reader is scrolled away from the newest edge the rendered item set
 *    is a FROZEN SNAPSHOT of what was visible when they left the top:
 *    arrivals mutate nothing, so the reading position cannot move (the
 *    compensation needed is zero). An "↑ N new" pin counts arrivals against
 *    the snapshot; clicking it (or scrolling back to the top) thaws and
 *    re-pins to newest. The jump is INSTANT (no smooth-scroll dependence),
 *    so prefers-reduced-motion needs no special case.
 *
 * The only inline styles are the DYNAMIC windowing geometry (heights/offsets
 * computed from props/scroll state) — no hardcoded design literals.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode, UIEvent } from 'react';

export interface VirtualListProps<T> {
  items: T[];
  /**
   * Fixed row height in px. With `itemHeight` absent every row is clamped to
   * exactly this; with `itemHeight` present it is the MINIMUM row height
   * (the bounded-rows guarantee derives from it).
   */
  rowHeight: number;
  /**
   * Wave G (EM-197): deterministic per-item-kind height in px. Must be a pure
   * function of the item data (never measurement) so prefix sums stay exact.
   */
  itemHeight?: (item: T, index: number) => number;
  /** Stable React key per item (seq / turn id …). */
  itemKey: (item: T, index: number) => string | number;
  renderRow: (item: T, index: number) => ReactNode;
  /** Extra rows rendered above/below the viewport (default 6). */
  overscan?: number;
  /** Classes for the list frame (the panel supplies flex/border). */
  className?: string;
  /** Viewport height used until the container measures (jsdom/tests). */
  fallbackViewportHeight?: number;
  /** Accessible label for the list. */
  ariaLabel?: string;
  /**
   * Wave G (EM-197): EM-093-style anchoring for newest-first lists. While
   * scrolled away from the top edge, the rendered set freezes and an
   * "↑ N new" pin counts arrivals; top-edge scroll (or the pin) re-pins.
   */
  anchorNewest?: boolean;
}

// How close to the newest (top) edge counts as "pinned" (px) — EM-093's value.
const TOP_THRESHOLD = 8;

/** Largest index i in [0, len] with offsets[i] <= value (binary search). */
function offsetIndex(offsets: number[], value: number): number {
  let lo = 0;
  let hi = offsets.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (offsets[mid] <= value) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

export function VirtualList<T>({
  items,
  rowHeight,
  itemHeight,
  itemKey,
  renderRow,
  overscan = 6,
  className = '',
  fallbackViewportHeight = 480,
  ariaLabel,
  anchorNewest = false,
}: VirtualListProps<T>) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(fallbackViewportHeight);

  // EM-093 freeze: null = pinned to newest (live); an array = the exact item
  // set rendered while the reader is scrolled away. Only with `anchorNewest`.
  const [frozen, setFrozen] = useState<T[] | null>(null);
  const display = anchorNewest && frozen !== null ? frozen : items;

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

  const total = display.length;

  // Wave G: prefix-sum offsets for the variable-height path. offsets[i] is the
  // top of row i; offsets[total] is the full spacer height. null = fixed path.
  const offsets = useMemo<number[] | null>(() => {
    if (!itemHeight) return null;
    const out = new Array<number>(total + 1);
    out[0] = 0;
    for (let i = 0; i < total; i++) out[i + 1] = out[i] + itemHeight(display[i], i);
    return out;
  }, [display, itemHeight, total]);

  let start: number;
  let end: number;
  if (offsets) {
    start = Math.max(0, Math.min(total, offsetIndex(offsets, scrollTop)) - overscan);
    // First row whose TOP is at/past the viewport bottom bounds the window.
    end = Math.min(total, offsetIndex(offsets, scrollTop + viewport) + 1 + overscan);
  } else {
    start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
    end = Math.min(total, Math.ceil((scrollTop + viewport) / rowHeight) + overscan);
  }
  const visible = display.slice(start, end);
  const spacerHeight = offsets ? offsets[total] : total * rowHeight;
  const windowTop = offsets ? offsets[start] : start * rowHeight;

  // The "↑ N new" pin: arrivals not present in the frozen snapshot, identified
  // by the stable item key (EM-093: set membership, never a max comparison).
  const unseen = useMemo(() => {
    if (!anchorNewest || frozen === null) return 0;
    const held = new Set(frozen.map((it, i) => itemKey(it, i)));
    let n = 0;
    for (let i = 0; i < items.length; i++) if (!held.has(itemKey(items[i], i))) n++;
    return n;
  }, [anchorNewest, frozen, items, itemKey]);

  const onScroll = (e: UIEvent<HTMLDivElement>) => {
    const top = e.currentTarget.scrollTop;
    setScrollTop(top);
    if (!anchorNewest) return;
    if (top <= TOP_THRESHOLD) {
      // Back at the newest edge: thaw and follow arrivals again.
      setFrozen((f) => (f === null ? f : null));
    } else {
      // Leaving the newest edge: freeze the item set exactly as rendered now.
      setFrozen((f) => f ?? items);
    }
  };

  const jumpToNewest = () => {
    setFrozen(null);
    const el = containerRef.current;
    if (el) el.scrollTop = 0; // instant — reduced-motion safe by construction
    setScrollTop(0);
  };

  return (
    <div className={`relative min-h-0 ${className}`}>
      <div
        ref={containerRef}
        onScroll={onScroll}
        className="absolute inset-0 overflow-y-auto"
        data-testid="virtual-list"
      >
        {/* Full-height spacer: scrollbar geometry matches the unvirtualized list. */}
        <div style={{ height: spacerHeight, position: 'relative' }}>
          <ul
            role="list"
            aria-label={ariaLabel}
            className="m-0 p-0 list-none"
            style={{
              position: 'absolute',
              top: windowTop,
              left: 0,
              right: 0,
            }}
          >
            {visible.map((item, i) => (
              <li
                key={itemKey(item, start + i)}
                style={{
                  height: offsets ? offsets[start + i + 1] - offsets[start + i] : rowHeight,
                  overflow: 'hidden',
                }}
              >
                {renderRow(item, start + i)}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* EM-093 pin — only while anchored away from the newest edge. */}
      {anchorNewest && frozen !== null && (
        <button
          type="button"
          onClick={jumpToNewest}
          title="Jump back to the newest entries (re-pins the list)"
          className="absolute top-1 left-1/2 -translate-x-1/2 z-10 cursor-pointer
                     font-mono text-[9px] px-1.5 py-0.5 rounded-full tabular-nums
                     bg-lab-chrome border border-lab-acid text-lab-acid
                     shadow-lg hover:bg-lab-acid/20 transition-colors duration-150"
        >
          ↑ {unseen > 0 ? `${unseen} new` : 'newest'}
        </button>
      )}
    </div>
  );
}
