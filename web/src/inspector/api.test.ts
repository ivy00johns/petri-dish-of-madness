/**
 * inspectorApi run scoping (W11a EM-086, api.openapi.yaml v1.3.0) — every
 * fetcher threads an OPTIONAL runId as the `run_id` query param, and OMITS it
 * entirely when unset (omitted = active run, byte-identical to pre-W11a
 * URLs). Plus /api/runs parsing: defensive newest-first ordering and the
 * null-on-failure contract that powers the RunBrowser's labeled
 * "no backend" state. fetch is mocked; no network.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { inspectorApi } from './api';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, json: async () => [] });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function requestedPath(call = 0): string {
  return fetchMock.mock.calls[call][0] as string;
}

function runIdParam(path: string): string | null {
  const qs = path.split('?')[1] ?? '';
  return new URLSearchParams(qs).get('run_id');
}

describe('inspectorApi — run_id is included iff runId is provided', () => {
  it('events: omitted runId produces NO run_id param (active run)', async () => {
    await inspectorApi.events({ limit: 10 });
    const path = requestedPath();
    expect(path.startsWith('/api/events')).toBe(true);
    expect(runIdParam(path)).toBeNull();
  });

  it('events: runId is serialized as run_id alongside the other params', async () => {
    await inspectorApi.events({ runId: 7, fromTick: 1, kinds: ['conflict', 'economy'] });
    const path = requestedPath();
    expect(runIdParam(path)).toBe('7');
    const qs = new URLSearchParams(path.split('?')[1]);
    expect(qs.get('from_tick')).toBe('1');
    expect(qs.get('kinds')).toBe('conflict,economy');
  });

  it('eventsResult: same path builder, null on failure (404 unknown run)', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({}) });
    expect(await inspectorApi.eventsResult({ runId: 9 })).toBeNull();
    expect(runIdParam(requestedPath())).toBe('9');
  });

  it('turn: /api/turns/{id} with and without run_id', async () => {
    await inspectorApi.turn('t1');
    expect(requestedPath(0)).toBe('/api/turns/t1');
    await inspectorApi.turn('t1', 4);
    expect(requestedPath(1)).toBe('/api/turns/t1?run_id=4');
  });

  it('rulesHistory / relationships / snapshots: scoped iff runId set', async () => {
    await inspectorApi.rulesHistory();
    await inspectorApi.rulesHistory(3);
    await inspectorApi.relationships({ agentId: 'Ada' });
    await inspectorApi.relationships({ runId: 3, agentId: 'Ada' });
    await inspectorApi.snapshots();
    await inspectorApi.snapshots(3);

    expect(requestedPath(0)).toBe('/api/rules/history');
    expect(requestedPath(1)).toBe('/api/rules/history?run_id=3');
    expect(runIdParam(requestedPath(2))).toBeNull();
    expect(runIdParam(requestedPath(3))).toBe('3');
    expect(requestedPath(4)).toBe('/api/snapshots');
    expect(requestedPath(5)).toBe('/api/snapshots?run_id=3');
  });

  it('replay / analytics / runAnalytics: scoped iff runId set', async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
    await inspectorApi.replay(12);
    await inspectorApi.replay(12, 5);
    await inspectorApi.analytics({ fromTick: 1 });
    await inspectorApi.analytics(undefined, 5);
    await inspectorApi.runAnalytics(5);

    expect(requestedPath(0)).toBe('/api/replay?tick=12');
    const scoped = new URLSearchParams(requestedPath(1).split('?')[1]);
    expect(scoped.get('tick')).toBe('12');
    expect(scoped.get('run_id')).toBe('5');
    expect(runIdParam(requestedPath(2))).toBeNull();
    expect(runIdParam(requestedPath(3))).toBe('5');
    expect(runIdParam(requestedPath(4))).toBe('5');
  });
});

describe('inspectorApi.runs — /api/runs parsing', () => {
  const row = (id: number, extra: Record<string, unknown> = {}) => ({
    id,
    started_at: `2026-06-0${id}T00:00:00Z`,
    ended_at: null,
    status: 'running',
    is_active: false,
    max_tick: 0,
    event_count: 0,
    config_summary: {},
    ...extra,
  });

  it('orders newest-first defensively even if the backend misorders', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [row(1), row(3), row(2)] });
    const runs = await inspectorApi.runs();
    expect(runs?.map((r) => r.id)).toEqual([3, 2, 1]);
  });

  it('returns null on failure so "no backend" is distinguishable from "zero runs"', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({}) });
    expect(await inspectorApi.runs()).toBeNull();

    fetchMock.mockRejectedValueOnce(new TypeError('network down'));
    expect(await inspectorApi.runs()).toBeNull();

    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [] });
    expect(await inspectorApi.runs()).toEqual([]); // zero runs is NOT a failure
  });

  it('coerces malformed rows safely and keeps is_active strictly boolean', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        row(2, { is_active: 'running', config_summary: 'not-an-object' }),
        { id: 'nope' }, // dropped: no numeric id
      ],
    });
    const runs = await inspectorApi.runs();
    expect(runs).toHaveLength(1);
    expect(runs?.[0].is_active).toBe(false); // truthy string must NOT mark active
    expect(runs?.[0].config_summary).toEqual({});
  });
});
