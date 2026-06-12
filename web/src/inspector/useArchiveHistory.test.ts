/**
 * Wave F (EM-194) — tail-first archive backfill (useArchiveHistory).
 *
 * Same treatment as the live boot: stats sizes the run, the NEWEST page
 * (order=desc) streams in first so the panels are interactive immediately,
 * older pages follow via before_seq keyset. `failed` still distinguishes a
 * dead backend / unknown run from an empty run.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useArchiveHistory } from './useArchiveHistory';
import { inspectorApi } from './api';
import type { EventRow, EventStats } from './api';

function row(seq: number): EventRow {
  return {
    seq,
    run_id: 7,
    tick: Math.ceil(seq / 25),
    sim_time: null,
    kind: 'agent_speech',
    actor_id: 'a1',
    actor_type: 'human_agent',
    target_id: null,
    profile: 'model-a',
    turn_id: null,
    text: `e${seq}`,
    payload: {},
    ts: '2026-06-12T00:00:00Z',
  };
}

function descRows(fromSeq: number, toSeq: number): EventRow[] {
  const out: EventRow[] = [];
  for (let s = toSeq; s >= fromSeq; s--) out.push(row(s));
  return out;
}

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

const STATS: EventStats = { total: 1500, max_seq: 1500, max_tick: 60, min_seq: 1 };

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useArchiveHistory — tail-first backfill (wave F)', () => {
  it('streams the NEWEST page first (interactive), then completes with older pages', async () => {
    vi.spyOn(inspectorApi, 'eventStats').mockResolvedValue(STATS);
    const page2 = deferred<EventRow[] | null>();
    const eventsSpy = vi.spyOn(inspectorApi, 'eventsResult').mockImplementation((q = {}) => {
      if (q.beforeSeq === undefined) return Promise.resolve(descRows(501, 1500));
      if (q.beforeSeq === 501) return page2.promise;
      return Promise.resolve([]);
    });

    const { result, unmount } = renderHook(() => useArchiveHistory(7));

    // Interactive after page one — newest events first, still loading.
    await waitFor(() => expect(result.current.events.length).toBe(1000));
    expect(result.current.loading).toBe(true);
    expect(result.current.failed).toBe(false);
    expect(result.current.total).toBe(1500);
    expect(result.current.events[0].seq).toBe(1500); // newest-first

    // The tail contract: run-scoped, desc, keyset.
    expect(eventsSpy.mock.calls[0][0]).toMatchObject({ runId: 7, order: 'desc' });
    expect(eventsSpy.mock.calls[0][0]?.beforeSeq).toBeUndefined();
    expect(eventsSpy.mock.calls[1][0]).toMatchObject({ runId: 7, order: 'desc', beforeSeq: 501 });

    await act(async () => {
      page2.resolve(descRows(1, 500)); // short page ⇒ done
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.events.length).toBe(1500);
    expect(result.current.events[1499].seq).toBe(1);
    expect(result.current.truncated).toBe(false);
    unmount();
  });

  it('marks `failed` when the FIRST page fails (dead backend / unknown run)', async () => {
    vi.spyOn(inspectorApi, 'eventStats').mockResolvedValue(null);
    vi.spyOn(inspectorApi, 'eventsResult').mockResolvedValue(null);

    const { result, unmount } = renderHook(() => useArchiveHistory(404));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.failed).toBe(true);
    expect(result.current.events).toEqual([]);
    unmount();
  });

  it('stays inert for runId = null (live mode)', async () => {
    const statsSpy = vi.spyOn(inspectorApi, 'eventStats');
    const eventsSpy = vi.spyOn(inspectorApi, 'eventsResult');
    const { result, unmount } = renderHook(() => useArchiveHistory(null));
    expect(result.current).toEqual({
      events: [],
      loading: false,
      failed: false,
      total: null,
      truncated: false,
    });
    expect(statsSpy).not.toHaveBeenCalled();
    expect(eventsSpy).not.toHaveBeenCalled();
    unmount();
  });
});
