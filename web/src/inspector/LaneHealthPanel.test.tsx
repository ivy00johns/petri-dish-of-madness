/**
 * EM-300 P5 — LaneHealthPanel: draws the router's own health window +
 * cooldown state verbatim, with labeled no-backend/loading/empty states.
 * fetch is mocked. The 2s poll interval is cleared on unmount (RTL
 * auto-cleanup), so no timers are needed here.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import LaneHealthPanel from './LaneHealthPanel';

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockLanes() {
  fetchMock.mockImplementation((path: string) => {
    if (path === '/api/lanes') {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          'gemini-flash': {
            window: [
              { parsed: true, truncated: false },
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
        }),
      });
    }
    if (path === '/api/lanes/registry') {
      return Promise.resolve({
        ok: true,
        json: async () => ({
          lanes: [
            {
              id: 'gemini-flash',
              source: 'catalog',
              model_id: 'gemini-2.0-flash',
              profile: 'gemini-flash',
              priority: 2,
              enabled: true,
              health: 'sick',
              cooldown: null,
              cap_state: 'sick',
              discovered: true,
              free: true,
              out_hint: null,
              last_refresh_counter: 0,
            },
          ],
          discovery: { enabled: false, every_turns: null, served_turns: 0, last_refresh_counter: 0, retired: [] },
        }),
      });
    }
    return Promise.resolve({ ok: false, json: async () => ({}) });
  });
}

const PROFILES = [
  { name: 'gemini-flash', color: '#5aa9e6' },
  { name: 'groq-llama', color: '#e6c15a' },
];

describe('LaneHealthPanel', () => {
  it('renders the labeled loading state before the first fetch resolves', () => {
    fetchMock.mockImplementation(() => new Promise(() => {}));
    render(<LaneHealthPanel profiles={PROFILES} />);
    expect(screen.getByText(/loading lane health/)).toBeTruthy();
  });

  it('renders the labeled no-backend state when the backend is unreachable', async () => {
    fetchMock.mockRejectedValue(new Error('offline'));
    render(<LaneHealthPanel profiles={PROFILES} />);
    await waitFor(() => {
      expect(screen.getByText(/no backend/)).toBeTruthy();
    });
  });

  it('renders the router window verbatim: sick lanes marked SKIP, window slots + cooldown shown', async () => {
    mockLanes();
    render(<LaneHealthPanel profiles={PROFILES} />);
    await waitFor(() => {
      expect(screen.getByText('SKIP')).toBeTruthy();
      expect(screen.getByText('1 SICK')).toBeTruthy();
    });
    // summary counts (scoped: the bare digit also appears in window glyphs)
    const summary = screen.getByText(/lanes/).closest('div');
    expect(summary).not.toBeNull();
    expect(summary!.textContent).toContain('2');
    expect(screen.getByText('1 COOLING')).toBeTruthy();
    expect(screen.getByText('DISCOVERY OFF')).toBeTruthy();
    // the cooling lane's auto badge + cooldown label
    expect(screen.getByText('AUTO')).toBeTruthy();
    expect(screen.getByText(/cooling — auto 38s · ×2/)).toBeTruthy();
    // the router's own window glyphs (error ✕ / timeout ⧖ / ok ✓)
    expect(screen.getAllByText('✕').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('⧖').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('✓').length).toBeGreaterThanOrEqual(2);
    // dash ≠ absent: groq-llama has no routed_via yet → em dash
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('renders the labeled empty state when no lane has recorded outcomes', async () => {
    fetchMock.mockImplementation((path: string) => {
      if (path === '/api/lanes') return Promise.resolve({ ok: true, json: async () => ({}) });
      if (path === '/api/lanes/registry') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            lanes: [],
            discovery: { enabled: false, every_turns: null, served_turns: 0, last_refresh_counter: 0, retired: [] },
          }),
        });
      }
      return Promise.resolve({ ok: false, json: async () => ({}) });
    });
    render(<LaneHealthPanel profiles={PROFILES} />);
    await waitFor(() => {
      expect(screen.getByText(/no lane outcomes recorded yet/)).toBeTruthy();
    });
  });
});
