/**
 * inspectorApi.godMiracle (wave-e EM-184/B6 item 3) — POST /api/god/intervene
 * with a WORLD kind. The contract REQUIRES agent_id ABSENT for world kinds
 * (the backend 422s a world kind carrying one), so the body must be {kind}
 * alone — never an agent_id key. Labeled-result mapping like the rest of the
 * god console (422 / 503 / network — never thrown). fetch mocked; no network.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { inspectorApi } from './api';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function requestBody(call = 0): Record<string, unknown> {
  const init = fetchMock.mock.calls[call][1] as RequestInit;
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

describe('inspectorApi.godMiracle — POST /api/god/intervene (world kinds)', () => {
  it.each(['send_rain', 'bountiful_harvest', 'calm_spirits'] as const)(
    'posts {kind: %s} with NO agent_id key',
    async (kind) => {
      const result = await inspectorApi.godMiracle(kind);
      expect(fetchMock.mock.calls[0][0]).toBe('/api/god/intervene');
      expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST');
      const body = requestBody();
      expect(body).toEqual({ kind });
      expect('agent_id' in body).toBe(false);
      expect(result).toEqual({ ok: true });
    },
  );

  it('maps 422 (disabled / agent_id mismatch / unknown kind) to a labeled failure', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({}) });
    const rejected = await inspectorApi.godMiracle('send_rain');
    expect(rejected).toMatchObject({ ok: false, status: 422 });
  });

  it('maps 503 (world not initialized) to a labeled failure', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) });
    const uninit = await inspectorApi.godMiracle('calm_spirits');
    expect(uninit).toMatchObject({ ok: false, status: 503 });
    expect((uninit as { message: string }).message).toMatch(/not initialized/);
  });

  it('a network failure resolves to the labeled unreachable result — never throws', async () => {
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    expect(await inspectorApi.godMiracle('bountiful_harvest')).toEqual({
      ok: false,
      status: null,
      message: 'backend unreachable — miracle not sent',
    });
  });
});
