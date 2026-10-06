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

const ZERO_FAIL = {
  counts: { action_rejected: 0, provider_error: 0, parse_failure: 0 },
  shares: { action_rejected: 0, provider_error: 0, parse_failure: 0 },
  total: 0, turns: 0, failure_rate: 0, legacy_rows_reclassified: 0,
};

const ARENA: ArenaSummary = {
  contact_runs: [
    {
      run_id: 26,
      max_tick: 1692,
      family_a: 'gemini',
      family_b: 'llama',
      name_b: 'Kettlebrook',
      outcomes: { population: 5, laws_passed: 0, buildings: 0, crimes: 0, credits: 0 },
      failures: {
        counts: { action_rejected: 109, provider_error: 288, parse_failure: 20 },
        shares: { action_rejected: 0.2614, provider_error: 0.6906, parse_failure: 0.048 },
        total: 417, turns: 1652, failure_rate: 0.2524, legacy_rows_reclassified: 417,
      },
      population_by_town: { Ashvale: 3, Kettlebrook: 2 },
      contact_made: { tick: 81, agent_id: 'a1', from_settlement: 's1', to_settlement: 's2' },
      ledger: { crossings: 442, by_family: { gemini: { hops: 139, mutated: 100 } } },
      events: { contact_made: 1, meme_crossed_border: 442 },
    },
  ],
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
          failures: {
            counts: { action_rejected: 147, provider_error: 30, parse_failure: 145 },
            shares: { action_rejected: 0.4565, provider_error: 0.0932, parse_failure: 0.4503 },
            total: 322, turns: 1103, failure_rate: 0.292, legacy_rows_reclassified: 322,
          },
        },
        {
          run_id: 9,
          max_tick: 40,
          outcomes: { population: 2, laws_passed: 1, buildings: 1, crimes: 3, credits: 30 },
          population_sparkline: [],
          failures: { ...ZERO_FAIL, turns: 40 },
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
          failures: ZERO_FAIL,
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

    arenaMock.mockResolvedValue({ families: [], contact_runs: [] });
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

describe('ArenaPanel — failure taxonomy (EM-343)', () => {
  it('renders the true per-run shares + per-turn rate off the arena card', async () => {
    render(<ArenaPanel />);
    const line = await screen.findByTestId('arena-run-failures-12');
    // the TRUE taxonomy, not the raw overloaded kind tally
    expect(line.textContent).toContain('rej 147 (46%)');
    expect(line.textContent).toContain('prov 30 (9%)');
    expect(line.textContent).toContain('parse 145 (45%)');
    expect(line.textContent).toContain('29.2%/turn');
    // the tooltip carries the denominators + how much came from history
    const title = line.getAttribute('title') ?? '';
    expect(title).toContain('322 of 1103 llm calls');
    expect(title).toContain('pre-EM-340 row(s) re-derived from payload');
  });

  it('labels a failure-free run without inventing shares', async () => {
    render(<ArenaPanel />);
    const line = await screen.findByTestId('arena-run-failures-9');
    expect(line.textContent).toContain('0/40 turns');
    expect(line.textContent).not.toContain('%');
  });

  it('renders the taxonomy on a contact run card too', async () => {
    render(<ArenaPanel />);
    const line = await screen.findByTestId('arena-contact-failures-26');
    expect(line.textContent).toContain('prov 288 (69%)');
    expect(line.textContent).toContain('25.2%/turn');
  });
});
