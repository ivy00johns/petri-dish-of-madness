/**
 * inspectorApi god-console POSTs (wave-a2 EM-136/137/138) — separate file from
 * api.test.ts (the W11a suite stays read-scoped). Covers the CONTRACT bodies:
 * /api/god/intervene {kind, agent_id, amount?} and /api/god/whisper
 * {agent_id, text} (trimmed, capped at 280), plus the labeled-result mapping
 * (422 validation / 503 uninitialized / network — never thrown). fetch is
 * mocked; no network.
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

describe('inspectorApi.godIntervene — POST /api/god/intervene', () => {
  it('posts {kind, agent_id} and OMITS amount when unset (backend defaults)', async () => {
    const result = await inspectorApi.godIntervene('bless_energy', 'a1');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/god/intervene');
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST');
    expect(requestBody()).toEqual({ kind: 'bless_energy', agent_id: 'a1' });
    expect(result).toEqual({ ok: true });
  });

  it('threads an explicit amount alongside grant_credits', async () => {
    await inspectorApi.godIntervene('grant_credits', 'a2', 40);
    expect(requestBody()).toEqual({ kind: 'grant_credits', agent_id: 'a2', amount: 40 });
  });

  it('maps 422 / 503 / other statuses to labeled failures — never throws', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({}) });
    const rejected = await inspectorApi.godIntervene('bless_energy', 'ghost');
    expect(rejected).toMatchObject({ ok: false, status: 422 });
    expect((rejected as { message: string }).message).toMatch(/unknown\/dead agent/);

    fetchMock.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) });
    const uninit = await inspectorApi.godIntervene('bless_energy', 'a1');
    expect(uninit).toMatchObject({ ok: false, status: 503 });
    expect((uninit as { message: string }).message).toMatch(/not initialized/);

    fetchMock.mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({}) });
    const failed = await inspectorApi.godIntervene('grant_credits', 'a1');
    expect(failed).toMatchObject({ ok: false, status: 500 });
  });

  it('a network failure resolves to the labeled unreachable result', async () => {
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    expect(await inspectorApi.godIntervene('bless_energy', 'a1')).toEqual({
      ok: false,
      status: null,
      message: 'backend unreachable — intervention not sent',
    });
  });
});

describe('inspectorApi.godWhisper — POST /api/god/whisper', () => {
  it('posts {agent_id, text} trimmed', async () => {
    const result = await inspectorApi.godWhisper('a1', '  the river remembers  ');
    expect(fetchMock.mock.calls[0][0]).toBe('/api/god/whisper');
    expect(requestBody()).toEqual({ agent_id: 'a1', text: 'the river remembers' });
    expect(result).toEqual({ ok: true });
  });

  it('caps the text at 280 chars (the billboard cap)', async () => {
    await inspectorApi.godWhisper('a1', 'x'.repeat(400));
    expect((requestBody().text as string).length).toBe(280);
  });

  it('maps a 422 (unknown/dead agent) to the labeled failure', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({}) });
    const rejected = await inspectorApi.godWhisper('ghost', 'boo');
    expect(rejected).toMatchObject({ ok: false, status: 422 });
    expect((rejected as { message: string }).message).toMatch(/whisper rejected/);
  });
});
