/**
 * ArenaPanel (EM-112 + EM-119) — component tests.
 *
 * The inspectorApi module is mocked (the panel is a pure view over it):
 *  - standings render: family blocks, per-run cards with outcome chips,
 *    sparkline SVGs, family means, first+last kept;
 *  - zero states: no-backend (null) vs no-stamped-runs (empty families);
 *  - tournament controls: chips toggle, start calls the client with the
 *    selection, failure renders the labeled message, abort renders while
 *    running, progress chip renders while running.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ArenaPanel from './ArenaPanel';
import type { ArenaSummary, TournamentStatus } from './api';

vi.mock('./api', () => ({
  inspectorApi: {
    arena: vi.fn(),
    tournamentStatus: vi.fn(),
    startTournament: vi.fn(),
    abortTournament: vi.fn(),
  },
}));

import { inspectorApi } from './api';

const arenaMock = vi.mocked(inspectorApi.arena);
const statusMock = vi.mocked(inspectorApi.tournamentStatus);
const startMock = vi.mocked(inspectorApi.startTournament);
const abortMock = vi.mocked(inspectorApi.abortTournament);

const ARENA: ArenaSummary = {
  families: [
    {
      family: 'gemini',
      avg_per_run: { population: 3, laws_passed: 1.5, buildings: 1, crimes: 2, credits: 40 },
      runs: [
        {
          run_id: 12,
          max_tick: 40,
          outcomes: { population: 4, laws_passed: 2, buildings: 1, crimes: 1, credits: 50 },
          population_sparkline: [
            { tick: 0, alive: 1 },
            { tick: 10, alive: 2 },
            { tick: 40, alive: 4 },
          ],
        },
        {
          run_id: 9,
          max_tick: 40,
          outcomes: { population: 2, laws_passed: 1, buildings: 1, crimes: 3, credits: 30 },
          population_sparkline: [],
        },
      ],
    },
    {
      family: 'llama',
      avg_per_run: { population: 2, laws_passed: 0, buildings: 0, crimes: 5, credits: 10 },
      runs: [
        {
          run_id: 11,
          max_tick: 40,
          outcomes: { population: 2, laws_passed: 0, buildings: 0, crimes: 5, credits: 10 },
          population_sparkline: [{ tick: 0, alive: 2 }],
        },
      ],
    },
  ],
};

const IDLE: TournamentStatus = {
  status: 'idle', families: [], ticks_per_family: 40, current_family: null,
  current_index: 0, current_run_id: null, ticks_done_in_current: 0,
  started_at: null, finished_at: null, error: null, results: [],
};

const RUNNING: TournamentStatus = {
  status: 'running', families: ['gemini', 'llama'], ticks_per_family: 40,
  current_family: 'llama', current_index: 1, current_run_id: 13,
  ticks_done_in_current: 7, started_at: '2026-10-03T00:00:00Z', finished_at: null,
  error: null,
  results: [
    { family: 'gemini', run_id: 12, ticks_run: 40, status: 'done', note: '' },
  ],
};

const DONE: TournamentStatus = {
  ...IDLE,
  status: 'done',
  families: ['gemini', 'llama'],
  results: [
    { family: 'gemini', run_id: 12, ticks_run: 40, status: 'done', note: '' },
    { family: 'llama', run_id: 13, ticks_run: 40, status: 'done', note: '' },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  arenaMock.mockResolvedValue(ARENA);
  statusMock.mockResolvedValue(IDLE);
  startMock.mockResolvedValue({ ok: true, status: 202, message: 'started' });
  abortMock.mockResolvedValue({ ok: true, status: 200, message: 'aborting' });
});

describe('ArenaPanel — standings (EM-119)', () => {
  it('renders both family blocks with run counts and means', async () => {
    render(<ArenaPanel />);
    await waitFor(() => expect(screen.getByTestId('arena-family-gemini')).toBeInTheDocument());
    expect(screen.getByTestId('arena-family-llama')).toBeInTheDocument();
    // family chips carry run counts
    expect(screen.getByTestId('arena-family-chip-gemini').textContent).toContain('(2)');
    expect(screen.getByTestId('arena-family-chip-llama').textContent).toContain('(1)');
    // means render (avg per run) — scoped to the gemini block (both blocks
    // carry the same titles)
    const gem = screen.getByTestId('arena-family-gemini');
    expect(within(gem).getByTitle('avg per run — laws').textContent).toContain('1.5');
    // per-run outcome chips
    expect(screen.getAllByText(/run #12/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/run #9/).length).toBeGreaterThan(0);
  });

  it('distinguishes no-backend (null) from no-stamped-runs (empty)', async () => {
    arenaMock.mockResolvedValue(null);
    render(<ArenaPanel />);
    await waitFor(() =>
      expect(screen.getByText(/no backend — the arena reads persisted runs/)).toBeInTheDocument());

    arenaMock.mockResolvedValue({ families: [] });
    render(<ArenaPanel />);
    await waitFor(() =>
      expect(screen.getAllByText(/no family-stamped runs yet/).length).toBeGreaterThan(0));
  });
});

describe('ArenaPanel — tournament controls (EM-112)', () => {
  it('toggles family chips and starts with the selection', async () => {
    render(<ArenaPanel />);
    const gem = await screen.findByTestId('arena-family-chip-gemini');
    const lla = screen.getByTestId('arena-family-chip-llama');
    fireEvent.click(gem);
    fireEvent.click(lla);
    const start = screen.getByTestId('arena-start');
    expect(start.textContent).toContain('(2)');
    fireEvent.click(start);
    await waitFor(() =>
      expect(startMock).toHaveBeenCalledWith(['gemini', 'llama'], 40));
  });

  it('renders a labeled failure when start is rejected (400/409)', async () => {
    startMock.mockResolvedValue({
      ok: false, status: 400,
      message: "unknown family 'bogus' — no configured lane matches",
    });
    render(<ArenaPanel />);
    fireEvent.click(await screen.findByTestId('arena-family-chip-gemini'));
    fireEvent.click(screen.getByTestId('arena-start'));
    expect(await screen.findByRole('alert')).toHaveTextContent(/unknown family/);
  });

  it('shows progress + abort while running', async () => {
    statusMock.mockResolvedValue(RUNNING);
    render(<ArenaPanel />);
    await waitFor(() => expect(screen.getByTestId('arena-progress').textContent).toContain('llama · 7/40'));
    const abort = screen.getByRole('button', { name: /abort/ });
    fireEvent.click(abort);
    await waitFor(() => expect(abortMock).toHaveBeenCalled());
    // start button hidden while running
    expect(screen.queryByTestId('arena-start')).not.toBeInTheDocument();
  });

  it('summarizes the last sweep after settle', async () => {
    statusMock.mockResolvedValue(DONE);
    render(<ArenaPanel />);
    const summary = await screen.findByTestId('arena-tournament-summary');
    expect(summary.textContent).toContain('last sweep: done');
    expect(summary.textContent).toContain('gemini done (40t)');
    expect(summary.textContent).toContain('llama done (40t)');
  });
});
