/**
 * useArchiveHistory (W11a EM-086, frontend-inspector.md §8) — the archive-mode
 * event source.
 *
 * While the inspector views a PAST run, the WS/live rolling-history merge is
 * DISABLED: the panels render ONLY this hook's data.
 *
 * Wave F (EM-194): the backfill is TAIL-FIRST. The run is sized via
 * GET /api/events/stats?run_id=N, then the NEWEST page loads first
 * (order=desc + before_seq keyset, the mirror of the asc contract) and the
 * panels render immediately; older pages stream in behind it. Rows convert
 * through eventRowToWorldEvent so the run flows through the SAME pure
 * selectors as live history. `total` drives the honest progress label
 * ("12,000 / 99,140 events"); `truncated` flags a run larger than the page
 * cap (newest events win).
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
/** Safety cap: 50 pages = 50k events — the newest 50k win on a longer run. */
const MAX_PAGES = 50;

export interface ArchiveHistory {
  /** The run's full event log, NEWEST-FIRST (the `history` prop convention). */
  events: WorldEvent[];
  /** True while pages are still arriving. */
  loading: boolean;
  /** True when the FIRST page failed (no backend / unknown run_id → 404). */
  failed: boolean;
  /**
   * Wave F (EM-194): the run's total event count from /api/events/stats —
   * the progress denominator. `null` = unknown (pre-F1 backend).
   */
  total: number | null;
  /** Wave F (EM-194): true when the run exceeds the page cap (newest win). */
  truncated: boolean;
}

const EMPTY: ArchiveHistory = {
  events: [],
  loading: false,
  failed: false,
  total: null,
  truncated: false,
};

export function useArchiveHistory(runId: number | null): ArchiveHistory {
  const [state, setState] = useState<ArchiveHistory>(EMPTY);

  useEffect(() => {
    if (runId === null) {
      setState(EMPTY);
      return;
    }
    // Reset synchronously on run change — panels must never render run A's
    // events under run B's banner while the backfill is in flight.
    setState({ events: [], loading: true, failed: false, total: null, truncated: false });

    let alive = true;
    void (async () => {
      // 1) Size the run (null-tolerant: pre-F1 backends just get no figure).
      const stats = await inspectorApi.eventStats(runId);
      if (!alive) return;
      const total = stats?.total ?? null;
      const capTruncated = total !== null && total > PAGE_LIMIT * MAX_PAGES;
      if (total !== null) {
        setState((prev) => ({ ...prev, total, truncated: prev.truncated || capTruncated }));
      }

      // 2) Newest page first (order=desc), then older pages via before_seq.
      // Pages arrive newest→oldest and each page is itself newest-first, so a
      // straight concat keeps the NEWEST-FIRST convention exactly.
      const newestFirst: WorldEvent[] = [];
      let beforeSeq: number | undefined = undefined;
      for (let page = 0; page < MAX_PAGES; page++) {
        const rows = await inspectorApi.eventsResult({
          runId,
          beforeSeq,
          limit: PAGE_LIMIT,
          order: 'desc',
        });
        if (!alive) return;
        if (rows === null) {
          // Fetch failure: only the first page marks the whole run failed;
          // a mid-backfill failure keeps the partial pages (still labeled
          // loading=false) rather than discarding data already shown.
          setState((prev) => ({
            ...prev,
            loading: false,
            failed: page === 0,
          }));
          return;
        }
        const oldestSeq = rows.length > 0 ? rows[rows.length - 1].seq : undefined;
        // Keyset-progress guard: a backend ignoring before_seq/desc would
        // resend the same page forever — stop instead of spinning.
        if (
          beforeSeq !== undefined &&
          oldestSeq !== undefined &&
          oldestSeq >= beforeSeq
        ) {
          setState((prev) => ({ ...prev, loading: false }));
          return;
        }
        for (const row of rows) newestFirst.push(eventRowToWorldEvent(row));
        const done = rows.length < PAGE_LIMIT;
        // Stream pages in as they land — the panels are interactive after
        // page one (the run's NEWEST events), per the wave-F contract.
        setState((prev) => ({
          events: [...newestFirst],
          loading: !done,
          failed: false,
          total: prev.total,
          truncated: prev.truncated,
        }));
        if (done) return;
        beforeSeq = oldestSeq;
      }
      // MAX_PAGES exhausted: surface what we have (the newest 50k), labeled.
      if (alive) {
        setState((prev) => ({
          events: [...newestFirst],
          loading: false,
          failed: false,
          total: prev.total,
          truncated: true,
        }));
      }
    })();

    return () => {
      alive = false;
    };
  }, [runId]);

  return state;
}
