/**
 * useArchiveHistory (W11a EM-086, frontend-inspector.md §8) — the archive-mode
 * event source.
 *
 * While the inspector views a PAST run, the WS/live rolling-history merge is
 * DISABLED: the panels render ONLY this hook's data. It backfills the selected
 * run from GET /api/events?run_id=N using the existing keyset pagination
 * (after_seq ascending, the same scheme the live backfill uses), converting
 * rows through eventRowToWorldEvent so the run flows through the SAME pure
 * selectors as live history.
 *
 * State is keyed to `runId`: changing runs resets to empty IMMEDIATELY (no
 * stale run bleeding into the next), and `runId = null` (live mode) holds the
 * inert empty state at zero cost. `failed` distinguishes "backend unreachable
 * / unknown run (404)" from a legitimately EMPTY run, so the layout can label
 * the two differently (§7 empty-state rule).
 */

import { useEffect, useState } from 'react';
import { inspectorApi, eventRowToWorldEvent } from './api';
import type { WorldEvent } from '../types';

/** Page size for the keyset backfill (matches the live backfill's scale). */
const PAGE_LIMIT = 1000;
/** Safety cap: 50 pages = 50k events — beyond any run this lab produces. */
const MAX_PAGES = 50;

export interface ArchiveHistory {
  /** The run's full event log, NEWEST-FIRST (the `history` prop convention). */
  events: WorldEvent[];
  /** True while pages are still arriving. */
  loading: boolean;
  /** True when the FIRST page failed (no backend / unknown run_id → 404). */
  failed: boolean;
}

const EMPTY: ArchiveHistory = { events: [], loading: false, failed: false };

export function useArchiveHistory(runId: number | null): ArchiveHistory {
  const [state, setState] = useState<ArchiveHistory>(EMPTY);

  useEffect(() => {
    if (runId === null) {
      setState(EMPTY);
      return;
    }
    // Reset synchronously on run change — panels must never render run A's
    // events under run B's banner while the backfill is in flight.
    setState({ events: [], loading: true, failed: false });

    let alive = true;
    void (async () => {
      const ascendingRows: WorldEvent[] = [];
      let afterSeq = 0;
      for (let page = 0; page < MAX_PAGES; page++) {
        const rows = await inspectorApi.eventsResult({
          runId,
          afterSeq,
          limit: PAGE_LIMIT,
          order: 'asc',
        });
        if (!alive) return;
        if (rows === null) {
          // Fetch failure: only the first page marks the whole run failed;
          // a mid-backfill failure keeps the partial pages (still labeled
          // loading=false) rather than discarding data already shown.
          setState((prev) => ({
            events: prev.events,
            loading: false,
            failed: page === 0,
          }));
          return;
        }
        for (const row of rows) ascendingRows.push(eventRowToWorldEvent(row));
        const done = rows.length < PAGE_LIMIT;
        // Stream pages in as they land (newest-first copy for the panels).
        setState({
          events: [...ascendingRows].reverse(),
          loading: !done,
          failed: false,
        });
        if (done) return;
        afterSeq = ascendingRows[ascendingRows.length - 1]?.seq ?? afterSeq;
      }
      // MAX_PAGES exhausted: surface what we have, stop loading.
      if (alive) setState({ events: [...ascendingRows].reverse(), loading: false, failed: false });
    })();

    return () => {
      alive = false;
    };
  }, [runId]);

  return state;
}
