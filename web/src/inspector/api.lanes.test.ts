/**
 * EM-300 P5 — inspectorApi.lanes() + lanesRegistry(): the router's own
 * lane-health window + cooldown state, verbatim. fetch is mocked; no network.
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

describe('inspectorApi.lanes — GET /api/lanes', () => {
  const HEALTH = {
    'gemini-flash': {
      window: [
        { parsed: true, truncated: false },
        { parsed: true, truncated: true },
        { parsed: false, truncated: false, timed_out: true },
        { parsed: false, truncated: false, error: true },
      ],
      boosted: false,
      timeouts: 1,
      errors: 1,
      last_routed_via: 'gemini-2.0-flash',
      sick: true,
      detours_routed_here: 3,
    },
    'groq-llama': {
      window: [{ parsed: true, truncated: false }],
      boosted: false,
      timeouts: 0,
      errors: 0,
      last_routed_via: null,
      sick: false,
      detours_routed_here: 0,
      cooldown: { cooling: true, expires_in_s: 37.5, strikes: 2 },
    },
  };

  it('hits /api/lanes and parses window entries + cooldown verbatim', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => HEALTH });
    const lanes = await inspectorApi.lanes();
    expect(requestedPath()).toBe('/api/lanes');
    expect(lanes).not.toBeNull();
    expect(lanes!['gemini-flash'].sick).toBe(true);
    expect(lanes!['gemini-flash'].window).toHaveLength(4);
    expect(lanes!['gemini-flash'].window[1]).toEqual({ parsed: true, truncated: true });
    expect(lanes!['gemini-flash'].window[3].error).toBe(true);
    expect(lanes!['gemini-flash'].last_routed_via).toBe('gemini-2.0-flash');
    // cooldown rides the same payload only when present
    expect(lanes!['gemini-flash'].cooldown).toBeUndefined();
    expect(lanes!['groq-llama'].cooldown).toEqual({
      cooling: true,
      expires_in_s: 37.5,
      strikes: 2,
    });
  });

  it('returns null on failure / malformed body (mock mode degrades)', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({}) });
    expect(await inspectorApi.lanes()).toBeNull();
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [] });
    expect(await inspectorApi.lanes()).toBeNull();
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    expect(await inspectorApi.lanes()).toBeNull();
  });
});

describe('inspectorApi.lanesRegistry — GET /api/lanes/registry', () => {
  const REGISTRY = {
    lanes: [
      {
        id: 'auto',
        source: 'profile',
        model_id: '',
        profile: 'auto',
        priority: 1,
        enabled: true,
        health: 'ok',
        cooldown: null,
        cap_state: 'ok',
        discovered: false,
        free: false,
        out_hint: null,
        last_refresh_counter: 0,
      },
      {
        id: 'gemini-flash',
        source: 'catalog',
        model_id: 'gemini-2.0-flash',
        profile: 'gemini-flash',
        priority: 2,
        enabled: true,
        health: 'sick',
        cooldown: { cooling: true, expires_in_s: 10, strikes: 1 },
        cap_state: 'sick',
        discovered: true,
        free: true,
        out_hint: 'daily-cap',
        last_refresh_counter: 3,
      },
    ],
    discovery: {
      enabled: true,
      every_turns: 50,
      served_turns: 4,
      last_refresh_counter: 3,
      retired: [{ id: 'mistral-small', reason: 'not in catalog' }],
    },
  };

  it('hits /api/lanes/registry and parses lanes in priority order + discovery meta', async () => {
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => REGISTRY });
    const view = await inspectorApi.lanesRegistry();
    expect(requestedPath()).toBe('/api/lanes/registry');
    expect(view).not.toBeNull();
    expect(view!.lanes).toHaveLength(2);
    expect(view!.lanes[0].profile).toBe('auto');
    expect(view!.lanes[1].health).toBe('sick');
    expect(view!.lanes[1].discovered).toBe(true);
    expect(view!.lanes[1].cooldown?.expires_in_s).toBe(10);
    expect(view!.discovery.enabled).toBe(true);
    expect(view!.discovery.retired[0].id).toBe('mistral-small');
  });

  it('returns null on failure / missing lanes array', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({}) });
    expect(await inspectorApi.lanesRegistry()).toBeNull();
    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => ({ discovery: {} }) });
    expect(await inspectorApi.lanesRegistry()).toBeNull();
    fetchMock.mockRejectedValueOnce(new Error('offline'));
    expect(await inspectorApi.lanesRegistry()).toBeNull();
  });
});
