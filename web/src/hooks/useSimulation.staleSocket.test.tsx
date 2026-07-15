/**
 * STALE-SOCKET GUARD (EM-305) — the feed-flicker root cause. Every WS handler
 * used to act unconditionally on shared state, so ANY closing socket
 * (StrictMode's first-mount socket, a superseded reconnect) nulled wsRef,
 * bumped the reconnect counter and spawned another socket — orphaning the live
 * one and breeding N parallel sockets that each reprocessed every message.
 * This pins the guard contract:
 *
 *   1. StrictMode's mount→cleanup→mount leaves exactly ONE live socket: the
 *      retired first socket has its handlers DETACHED by effect cleanup, and
 *      its late browser close spawns nothing.
 *   2. A socket replaced by reconnect is inert: its onopen/onmessage/onclose
 *      never touch state — no events added, no connected flip, no ref null,
 *      no reconnect bred — while the CURRENT socket keeps working.
 *   3. The CURRENT socket closing still reconnects on the existing backoff,
 *      and the mock fallback still trips after MAX_RECONNECTS_BEFORE_MOCK.
 *
 * inspectorApi is spied directly (no fetch); WebSocket is a capturing stub so
 * the tests drive handlers by hand. Fake timers drive the reconnect backoff.
 */
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useSimulation } from './useSimulation';
import { inspectorApi } from '../inspector/api';

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

/** A live WS event message as the backend sends it (seq = DB event_id). */
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
      ts: '2026-07-15T00:00:01Z',
    }),
  };
}

beforeEach(() => {
  sockets.length = 0;
  vi.useFakeTimers();
  vi.stubGlobal('WebSocket', FakeWebSocket);
  // Backend quiet: the mount backfill degrades silently (stats null, no rows).
  vi.spyOn(inspectorApi, 'eventStats').mockResolvedValue(null);
  vi.spyOn(inspectorApi, 'events').mockResolvedValue([]);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('useSimulation — stale-socket guard (EM-305)', () => {
  it('StrictMode double-mount leaves ONE live socket; the retired socket is detached and its late close spawns nothing', async () => {
    const { result, unmount } = renderHook(() => useSimulation(), {
      wrapper: StrictMode,
    });
    await act(async () => {}); // flush the (empty) initial backfills

    // mount → cleanup → mount: two sockets constructed, the second is current.
    expect(sockets.length).toBe(2);
    // Cleanup DETACHED the retired socket's handlers — a deliberate close can
    // never re-enter the reconnect path.
    expect(sockets[0].onopen).toBeNull();
    expect(sockets[0].onmessage).toBeNull();
    expect(sockets[0].onclose).toBeNull();
    expect(sockets[0].onerror).toBeNull();

    // The retired socket's close event arrives late (browser async): nothing
    // to run, and no reconnect ever fires — the socket count stays at 2.
    act(() => {
      sockets[0].onclose?.();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(sockets.length).toBe(2);

    // The current socket was untouched by the whole sequence: it opens and
    // delivers events normally.
    act(() => {
      sockets[1].onopen?.();
    });
    expect(result.current.connected).toBe(true);
    act(() => {
      sockets[1].onmessage?.(wsEvent(1, 'real-e1'));
    });
    expect(result.current.events.map((e) => e.seq)).toEqual([1]);

    unmount();
  });

  it('a socket replaced by reconnect is inert: no events, no connected flip, no bred reconnect', async () => {
    const { result, unmount } = renderHook(() => useSimulation());
    await act(async () => {});
    expect(sockets.length).toBe(1);

    // The CURRENT socket drops → the hook schedules the 2s reconnect, which
    // spawns a replacement; sockets[0] is now stale but its handlers are
    // still attached (it was replaced, not retired by unmount cleanup).
    act(() => {
      sockets[0].onclose?.();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(sockets.length).toBe(2);

    // Stale onopen must not flip connected…
    act(() => {
      sockets[0].onopen?.();
    });
    expect(result.current.connected).toBe(false);
    // …stale onmessage must not add events…
    act(() => {
      sockets[0].onmessage?.(wsEvent(99, 'stale-e99'));
    });
    expect(result.current.events).toEqual([]);
    // …and a stale close must not null the ref, bump attempts, or spawn a
    // reconnect: no new socket appears no matter how long the clock runs.
    act(() => {
      sockets[0].onclose?.();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(sockets.length).toBe(2);

    // The current socket still works end to end.
    act(() => {
      sockets[1].onopen?.();
    });
    expect(result.current.connected).toBe(true);
    act(() => {
      sockets[1].onmessage?.(wsEvent(1, 'real-e1'));
    });
    expect(result.current.events.map((e) => e.seq)).toEqual([1]);

    unmount();
  });

  it('the CURRENT socket closing still reconnects on the existing backoff (and the mock fallback still trips)', async () => {
    const { result, unmount } = renderHook(() => useSimulation());
    await act(async () => {});
    expect(sockets.length).toBe(1);

    // Open, then drop: attempts reset on open, so the first backoff is 2s —
    // no replacement at 1999ms, one at 2000ms.
    act(() => {
      sockets[0].onopen?.();
    });
    act(() => {
      sockets[0].onclose?.();
    });
    expect(result.current.connected).toBe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(sockets.length).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(sockets.length).toBe(2);

    // Second failure doubles the backoff (4s), third trips the mock fallback.
    act(() => {
      sockets[1].onclose?.();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000);
    });
    expect(sockets.length).toBe(3);
    act(() => {
      sockets[2].onclose?.();
    });
    expect(result.current.mockMode).toBe(true);

    unmount();
  });
});
