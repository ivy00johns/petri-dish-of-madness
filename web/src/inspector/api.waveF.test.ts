/**
 * Wave F (EM-194) — inspectorApi additions: GET /api/events/stats and the
 * before_seq/desc TAIL mode on GET /api/events. Also regression-pins that the
 * asc path serializes EXACTLY as before (no before_seq leakage). fetch is
 * mocked; no network.
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

function params(path: string): URLSearchParams {
  return new URLSearchParams(path.split('?')[1] ?? '');
}

describe('inspectorApi.eventStats — GET /api/events/stats', () => {
  const STATS = { total: 99_140, max_seq: 99_140, max_tick: 4097, min_seq: 1 };

  it('hits /api/events/stats (no run_id when omitted) and parses the shape', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => STATS });
    expect(await inspectorApi.eventStats()).toEqual(STATS);
    expect(requestedPath()).toBe('/api/events/stats');
  });

  it('threads runId as run_id (archive mode)', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => STATS });
    await inspectorApi.eventStats(7);
    expect(requestedPath()).toBe('/api/events/stats?run_id=7');
  });

  it('returns null on failure (no backend / pre-F1 404) and on a malformed body', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({}) });
    expect(await inspectorApi.eventStats()).toBeNull();
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ total: 'lots' }) });
    expect(await inspectorApi.eventStats()).toBeNull();
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    expect(await inspectorApi.eventStats()).toBeNull();
  });
});

describe('inspectorApi.events — before_seq/desc tail mode (EM-194)', () => {
  it('serializes beforeSeq + order=desc for the tail page', async () => {
    await inspectorApi.events({ beforeSeq: 1501, order: 'desc', limit: 1000 });
    const qs = params(requestedPath());
    expect(qs.get('before_seq')).toBe('1501');
    expect(qs.get('order')).toBe('desc');
    expect(qs.get('limit')).toBe('1000');
    expect(qs.get('after_seq')).toBeNull();
  });

  it('the newest chunk omits before_seq entirely (first page of the tail)', async () => {
    await inspectorApi.events({ order: 'desc', limit: 1000 });
    const qs = params(requestedPath());
    expect(qs.get('before_seq')).toBeNull();
    expect(qs.get('order')).toBe('desc');
  });

  it('REGRESSION PIN: the asc path serializes exactly as before', async () => {
    await inspectorApi.events({ afterSeq: 42, order: 'asc', limit: 1000 });
    const qs = params(requestedPath());
    expect(qs.get('after_seq')).toBe('42');
    expect(qs.get('order')).toBe('asc');
    expect(qs.get('before_seq')).toBeNull();
  });

  it('eventsResult supports the same tail params (archive backfill)', async () => {
    await inspectorApi.eventsResult({ runId: 9, beforeSeq: 501, order: 'desc', limit: 1000 });
    const qs = params(requestedPath());
    expect(qs.get('run_id')).toBe('9');
    expect(qs.get('before_seq')).toBe('501');
    expect(qs.get('order')).toBe('desc');
  });
});
