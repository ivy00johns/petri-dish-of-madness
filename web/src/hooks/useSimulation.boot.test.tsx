/**
 * Wave F (EM-194) — tail-first boot order for the live history backfill.
 *
 * Pins the contract: (1) the FIRST request is /api/events/stats, (2) the
 * SECOND is the NEWEST chunk (order=desc, no before_seq) which renders
 * IMMEDIATELY — the annex is interactive after chunk one, while older pages
 * are still in flight — and (3) background pages walk before_seq keyset
 * newest→oldest, keeping the history newest-first and the truncation flag
 * honest. Page 2 is gated behind a deferred promise so "first render before
 * backfill completes" is asserted deterministically.
 *
 * inspectorApi is spied directly (no fetch); WebSocket is stubbed inert.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useSimulation } from './useSimulation';
import { inspectorApi } from '../inspector/api';
import type { EventRow, EventStats } from '../inspector/api';

// ── inert WebSocket stub (jsdom has none; the hook must not fall to mock) ───
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  onopen: (() => void) | null = null;
  onmessage: ((e: unknown) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  close(): void {}
  send(): void {}
}

function row(seq: number): EventRow {
  return {
    seq,
    run_id: 1,
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

/** Rows seq toSeq..fromSeq, NEWEST-FIRST (the desc tail contract). */
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

const STATS: EventStats = { total: 2500, max_seq: 2500, max_tick: 100, min_seq: 1 };

beforeEach(() => {
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('useSimulation — tail-first boot (wave F)', () => {
  it('renders the NEWEST chunk first, then backfills older pages in the background', async () => {
    const statsSpy = vi.spyOn(inspectorApi, 'eventStats').mockResolvedValue(STATS);
    const page2 = deferred<EventRow[]>();
    const eventsSpy = vi.spyOn(inspectorApi, 'events').mockImplementation((q = {}) => {
      if (q.beforeSeq === undefined) return Promise.resolve(descRows(1501, 2500)); // newest chunk
      if (q.beforeSeq === 1501) return page2.promise; // held back deliberately
      if (q.beforeSeq === 501) return Promise.resolve(descRows(1, 500)); // final short page
      return Promise.resolve([]);
    });

    const { result, unmount } = renderHook(() => useSimulation());

    // ── Interactive after chunk one: newest 1000 rendered, backfill ongoing ──
    await waitFor(() => expect(result.current.history.length).toBe(1000));
    expect(result.current.historyLoading).toBe(true); // older pages still in flight
    expect(result.current.historyTotal).toBe(2500); // stats drove the progress figure
    expect(result.current.history[0].seq).toBe(2500); // newest-first
    expect(result.current.history[999].seq).toBe(1501);
    // EM-088: the same newest page seeded the live feed (200 cap, newest win).
    expect(result.current.events.length).toBe(200);
    expect(result.current.events[0].seq).toBe(2500);

    // ── Boot order: stats FIRST, then the newest desc chunk (no before_seq) ──
    expect(statsSpy).toHaveBeenCalledTimes(1);
    expect(eventsSpy.mock.calls[0][0]).toMatchObject({ order: 'desc', limit: 1000 });
    expect(eventsSpy.mock.calls[0][0]?.beforeSeq).toBeUndefined();
    // Background pages walk the before_seq keyset newest→oldest.
    expect(eventsSpy.mock.calls[1][0]).toMatchObject({ order: 'desc', beforeSeq: 1501 });

    // ── Release the held page; the backfill completes behind the first render ─
    await act(async () => {
      page2.resolve(descRows(501, 1500));
    });
    await waitFor(() => expect(result.current.history.length).toBe(2500));
    await waitFor(() => expect(result.current.historyLoading).toBe(false));
    expect(result.current.historyTruncated).toBe(false); // 2500 ≤ the 50k cap
    // Newest-first maintained across appended background pages.
    expect(result.current.history[0].seq).toBe(2500);
    expect(result.current.history[2499].seq).toBe(1);

    unmount();
  });

  it('flags truncation up front when stats.total exceeds the memory cap', async () => {
    vi.spyOn(inspectorApi, 'eventStats').mockResolvedValue({
      total: 99_140,
      max_seq: 99_140,
      max_tick: 4097,
      min_seq: 1,
    });
    vi.spyOn(inspectorApi, 'events').mockImplementation((q = {}) => {
      if (q.beforeSeq === undefined) return Promise.resolve(descRows(98_141, 99_140));
      return Promise.resolve([]); // end the walk early — truncation came from stats
    });

    const { result, unmount } = renderHook(() => useSimulation());
    await waitFor(() => expect(result.current.history.length).toBe(1000));
    expect(result.current.historyTotal).toBe(99_140);
    expect(result.current.historyTruncated).toBe(true); // cap honesty, before any cap trip
    unmount();
  });

  it('degrades silently with no backend (stats null, empty pages)', async () => {
    vi.spyOn(inspectorApi, 'eventStats').mockResolvedValue(null);
    vi.spyOn(inspectorApi, 'events').mockResolvedValue([]);

    const { result, unmount } = renderHook(() => useSimulation());
    await waitFor(() => expect(result.current.historyLoading).toBe(false));
    expect(result.current.history).toEqual([]);
    expect(result.current.historyTotal).toBeNull();
    expect(result.current.historyTruncated).toBe(false);
    unmount();
  });
});
