/**
 * MOCK-FALLBACK PURGE — a WS outage (3 failed reconnects) falls the hook back
 * to the mock generator, whose events carry POSITIVE monotonic seqs. Since the
 * WS/DB seq unification the backend's seqs are DB event_ids in the very same
 * positive id space, so fallback events both LINGER in the feed/history after
 * live recovery and SHADOW real backend events out of the seq-dedupe (the
 * audit-C10 negative-seq fix covers only client-synthesized control events,
 * not the generator). This pins the recovery contract:
 *
 *   1. ws.onopen after a fallback purges every fallback-synthesized event
 *      from the feed AND the history, then the backfill re-runs against the
 *      real run — real rows land even on seqs the mock previously owned.
 *   2. The defensive onmessage recovery branch (first live message while the
 *      mock loop still runs) purges the same way.
 *   3. Post-recovery WS dedupe still holds under DB-rowid seqs: a resent seq
 *      is dropped, a fresh seq lands.
 *
 * inspectorApi is spied directly (no fetch); WebSocket is a capturing stub so
 * the test drives onclose/onopen/onmessage by hand. Fake timers drive the
 * reconnect backoff + the mock tick interval.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { useSimulation } from './useSimulation';
import { inspectorApi } from '../inspector/api';
import type { EventRow, EventStats } from '../inspector/api';

// ── capturing WebSocket stub (jsdom has none) ────────────────────────────────
const sockets: FakeWebSocket[] = [];

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 0;
  constructor() {
    sockets.push(this);
  }
  close(): void {}
  send(): void {}
}

function row(seq: number): EventRow {
  return {
    seq,
    run_id: 1,
    tick: 1,
    sim_time: null,
    kind: 'agent_speech',
    actor_id: 'real-actor',
    actor_type: 'human_agent',
    target_id: null,
    profile: 'model-a',
    turn_id: null,
    text: `real-e${seq}`,
    payload: {},
    ts: '2026-07-11T00:00:00Z',
  };
}

/** Rows seq toSeq..fromSeq, NEWEST-FIRST (the desc backfill contract). */
function descRows(fromSeq: number, toSeq: number): EventRow[] {
  const out: EventRow[] = [];
  for (let s = toSeq; s >= fromSeq; s--) out.push(row(s));
  return out;
}

/** A live WS event message as the backend now sends it (seq = DB event_id). */
function wsEvent(seq: number, text: string): { data: string } {
  return {
    data: JSON.stringify({
      type: 'event',
      seq,
      tick: 1,
      kind: 'agent_speech',
      actor_id: 'real-actor',
      text,
      payload: {},
      ts: '2026-07-11T00:00:01Z',
    }),
  };
}

/**
 * Drive 3 failed close→reconnect cycles → the mock fallback starts. Each close
 * must land on the socket the hook currently owns (a stale socket's onclose is
 * inert under the EM-305 guard, exactly as a real socket fires onclose once),
 * so the backoff timer is advanced between closes to spawn each replacement.
 * Leaves sockets.length === 3 with the 8s post-3rd-close reconnect pending.
 */
async function tripMockFallback() {
  act(() => {
    sockets[sockets.length - 1].onclose?.();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2000); // backoff #1 → replacement socket
  });
  act(() => {
    sockets[sockets.length - 1].onclose?.();
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4000); // backoff #2 → replacement socket
  });
  act(() => {
    sockets[sockets.length - 1].onclose?.();
  });
}

beforeEach(() => {
  sockets.length = 0;
  vi.useFakeTimers();
  vi.stubGlobal('WebSocket', FakeWebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('useSimulation — mock-fallback purge on live recovery', () => {
  it('onopen after a fallback purges mock events; the real backfill repopulates (colliding seqs included)', async () => {
    // Backend down at mount: stats null, no rows (the backfill degrades).
    const statsSpy = vi.spyOn(inspectorApi, 'eventStats').mockResolvedValue(null);
    const eventsSpy = vi.spyOn(inspectorApi, 'events').mockResolvedValue([]);

    const { result, unmount } = renderHook(() => useSimulation());
    expect(sockets.length).toBe(1);
    await act(async () => {}); // flush the (empty) initial backfill

    // ── Outage: 3 failed reconnects trip the mock fallback ──────────────────
    await tripMockFallback();
    expect(result.current.mockMode).toBe(true);

    // The generator synthesizes events with POSITIVE seqs — the collision
    // surface with the backend's DB event_ids.
    act(() => {
      result.current.injectEvent();
    });
    expect(result.current.events.length).toBeGreaterThan(0);
    expect(result.current.history.length).toBeGreaterThan(0);
    const mockSeqs = result.current.history.map((e) => e.seq);
    expect(mockSeqs.every((s) => s > 0)).toBe(true);
    // The real rows below (seqs 1..3) overlap seqs the mock already owns —
    // without the purge, the seq-dedupe would shadow them out.
    expect(Math.max(...mockSeqs)).toBeGreaterThanOrEqual(3);

    // ── Backend recovers: the real run is 3 events, seqs 1..3 ───────────────
    const stats: EventStats = { total: 3, max_seq: 3, max_tick: 1, min_seq: 1 };
    statsSpy.mockResolvedValue(stats);
    eventsSpy.mockImplementation((q = {}) =>
      q.beforeSeq === undefined ? Promise.resolve(descRows(1, 3)) : Promise.resolve([]),
    );

    // Fire the pending reconnect (8s backoff after the 3rd close) → a new
    // socket; the mock interval also ticks along the way (more mock events).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    expect(sockets.length).toBe(4);
    act(() => {
      sockets[3].onopen?.();
    });
    expect(result.current.mockMode).toBe(false);
    expect(result.current.connected).toBe(true);

    // ── Purge + repopulate: nothing mock survives anywhere ──────────────────
    vi.useRealTimers();
    await waitFor(() => expect(result.current.historyLoading).toBe(false));
    await waitFor(() => expect(result.current.history.length).toBe(3));
    expect(result.current.history.map((e) => e.seq)).toEqual([3, 2, 1]);
    expect(result.current.history.every((e) => e.actor_id === 'real-actor')).toBe(true);
    expect(result.current.events.map((e) => e.seq)).toEqual([3, 2, 1]);
    expect(result.current.events.every((e) => e.text?.startsWith('real-e'))).toBe(true);

    // ── Sanity: WS dedupe still correct now that seq = DB rowid ─────────────
    // A backend resend of a seq the backfill already delivered is dropped…
    act(() => {
      sockets[3].onmessage?.(wsEvent(3, 'real-e3-resend'));
    });
    expect(result.current.events.filter((e) => e.seq === 3)).toHaveLength(1);
    expect(result.current.events.find((e) => e.seq === 3)?.text).toBe('real-e3');
    // …and a fresh seq lands at the top of the feed and in the history.
    act(() => {
      sockets[3].onmessage?.(wsEvent(4, 'real-e4'));
    });
    expect(result.current.events[0].seq).toBe(4);
    expect(result.current.history[0].seq).toBe(4);

    unmount();
  });

  it('the defensive onmessage recovery branch purges too (live message beats onopen)', async () => {
    vi.spyOn(inspectorApi, 'eventStats').mockResolvedValue(null);
    vi.spyOn(inspectorApi, 'events').mockResolvedValue([]);

    const { result, unmount } = renderHook(() => useSimulation());
    await act(async () => {});

    await tripMockFallback();
    expect(result.current.mockMode).toBe(true);
    act(() => {
      result.current.injectEvent();
    });
    expect(result.current.events.length).toBeGreaterThan(0);

    // Reconnect fires (new socket) but the first LIVE MESSAGE arrives while
    // the mock loop is still running — the defensive branch must purge.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });
    expect(sockets.length).toBe(4);
    act(() => {
      sockets[3].onmessage?.(wsEvent(1, 'real-e1'));
    });
    expect(result.current.mockMode).toBe(false);

    // Only the live event survives — every mock event is gone from both the
    // feed and the history (backend still returns no backfill rows here).
    vi.useRealTimers();
    await waitFor(() => expect(result.current.historyLoading).toBe(false));
    expect(result.current.events.map((e) => e.seq)).toEqual([1]);
    expect(result.current.events[0].text).toBe('real-e1');
    expect(result.current.history.map((e) => e.seq)).toEqual([1]);

    unmount();
  });
});
