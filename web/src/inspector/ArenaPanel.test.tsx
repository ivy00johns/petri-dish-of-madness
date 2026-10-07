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
  // EM-352 — the panel falls back to this rule when the backend omits it.
  DEFAULT_CHRONIC_RULE: { rate_threshold: 0.2, min_runs: 2 },
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

const ZERO_CORE = {
  counts: { action_rejected: 0, provider_error: 0, parse_failure: 0 },
  shares: { action_rejected: 0, provider_error: 0, parse_failure: 0 },
  total: 0, turns: 0, failure_rate: 0, legacy_rows_reclassified: 0,
};

const ZERO_FAIL = {
  ...ZERO_CORE,
  curve: [],
  by_agent: {},
  by_route: {},
  failures_attributed: 0,
  attempts_attributed: 0,
};

const ARENA: ArenaSummary = {
  // EM-352 — chronic lanes head the list, each carrying its run evidence.
  routes: [
    {
      lane: 'google/gemini-3.1-flash-lite', failures: 74, attempts: 255, runs: 3,
      failure_rate: 0.2902, worst_rate: 0.56, runs_high: 3, chronic: true,
    },
    {
      lane: 'kilo/inclusionai/ling-3.0-flash-sante:free', failures: 218, attempts: 1449,
      runs: 1, failure_rate: 0.1504, worst_rate: 0.1504, runs_high: 0, chronic: false,
    },
    // a HIGH rate over a single run — a draw, never a chronic flag
    {
      lane: 'openrouter/qwen/qwen3.8-27b:free', failures: 1, attempts: 2, runs: 1,
      failure_rate: 0.5, worst_rate: 0.5, runs_high: 1, chronic: false,
    },
    {
      lane: 'cohere/command-r-plus-08-2024', failures: 0, attempts: 13, runs: 1,
      failure_rate: 0, worst_rate: 0, runs_high: 0, chronic: false,
    },
  ],
  chronic_rule: { rate_threshold: 0.2, min_runs: 2 },
  // EM-353 — the default read has no per-lane curves.
  lane_curves: false,
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
        total: 417, turns: 1652, failure_rate: 0.2524, legacy_rows_reclassified: 417,        curve: [
          { tick: 0, action_rejected: 0, provider_error: 0, parse_failure: 0 },
          { tick: 800, action_rejected: 0, provider_error: 60, parse_failure: 0 },
          { tick: 1600, action_rejected: 2, provider_error: 19, parse_failure: 0 },
        ],
        by_route: {
          'gemini/gemini-3.1-flash-lite': {
            failures: 63, attempts: 217, failure_rate: 0.2903,
            curve: [
              { tick: 0, failures: 1, attempts: 10 },
              { tick: 800, failures: 30, attempts: 100 },
              { tick: 1600, failures: 32, attempts: 107 },
            ],
          },
          'groq/llama-3.3-70b-instruct-fp8-fast': {
            failures: 66, attempts: 446, failure_rate: 0.148, curve: [],
          },
        },
        failures_attributed: 417,
        attempts_attributed: 1652,
        by_agent: {
            // run 26 is the UNIFORM provider-outage shape (~17-18% per agent)
            agent_bram: {
              counts: { action_rejected: 21, provider_error: 62, parse_failure: 4 },
              shares: { action_rejected: 0.2414, provider_error: 0.7126, parse_failure: 0.046 },
              total: 87, turns: 479, failure_rate: 0.1816, legacy_rows_reclassified: 87,
              routes: { 'gemini/gemini-3.1-flash-lite': 63, 'ollama/gpt-oss:120b': 8 },
              top_route: 'gemini/gemini-3.1-flash-lite', routes_attributed: 71,
            },
            agent_vesper: {
              counts: { action_rejected: 13, provider_error: 66, parse_failure: 5 },
              shares: { action_rejected: 0.1548, provider_error: 0.7857, parse_failure: 0.0595 },
              total: 84, turns: 481, failure_rate: 0.1746, legacy_rows_reclassified: 84,
              routes: { 'groq/llama-3.3-70b-instruct-fp8-fast': 66 },
              top_route: 'groq/llama-3.3-70b-instruct-fp8-fast', routes_attributed: 84,
            },
          },
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
      failures: {
        counts: { action_rejected: 147, provider_error: 30, parse_failure: 145 },
        shares: { action_rejected: 0.4565, provider_error: 0.0932, parse_failure: 0.4503 },
        total: 322, turns: 1143, failure_rate: 0.2817, legacy_rows_reclassified: 322,
      },
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
            curve: [
              { tick: 0, action_rejected: 0, provider_error: 0, parse_failure: 0 },
              { tick: 500, action_rejected: 2, provider_error: 0, parse_failure: 0 },
              { tick: 1000, action_rejected: 0, provider_error: 30, parse_failure: 0 },
            ],
            by_route: {
              'kilo/inclusionai/ling-3.0-flash-sante:free': {
                failures: 81, attempts: 300, failure_rate: 0.27,
                curve: [
                  { tick: 0, failures: 2, attempts: 40 },
                  { tick: 500, failures: 9, attempts: 60 },
                  { tick: 1000, failures: 70, attempts: 200 },
                ],
              },
              'google/gemini-3.8-flash': {
                failures: 19, attempts: 149, failure_rate: 0.1275, curve: [],
              },
            },
            failures_attributed: 300,
            attempts_attributed: 1103,
            by_agent: {
              // run 23 is the CONCENTRATED shape: ONE bad lane drives the mass
              agent_ada: {
                counts: { action_rejected: 57, provider_error: 6, parse_failure: 47 },
                shares: { action_rejected: 0.5182, provider_error: 0.0545, parse_failure: 0.4273 },
                total: 110, turns: 367, failure_rate: 0.2997, legacy_rows_reclassified: 110,
                routes: { 'kilo/inclusionai/ling-3.0-flash-sante:free': 81, 'kilo/step-3.7-flash:free': 16 },
                top_route: 'kilo/inclusionai/ling-3.0-flash-sante:free', routes_attributed: 104,
              },
              agent_mox: {
                counts: { action_rejected: 5, provider_error: 5, parse_failure: 13 },
                shares: { action_rejected: 0.2174, provider_error: 0.2174, parse_failure: 0.5652 },
                total: 23, turns: 302, failure_rate: 0.0762, legacy_rows_reclassified: 23,
                routes: { 'kilo/inclusionai/ling-3.0-flash-sante:free': 11 },
                top_route: 'kilo/inclusionai/ling-3.0-flash-sante:free', routes_attributed: 15,
              },
            },
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
      failures: ZERO_CORE,
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

    arenaMock.mockResolvedValue({
      families: [], contact_runs: [], routes: [],
      chronic_rule: { rate_threshold: 0.2, min_runs: 2 }, lane_curves: false,
    });
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

  it('EM-345 — draws the failures-over-ticks curve with the outage bucket as the peak', async () => {
    render(<ArenaPanel />);
    const curve = await screen.findByTestId('arena-run-curve-12');
    expect(curve.tagName.toLowerCase()).toBe('svg');
    // the tall provider bucket at t1000 is the labelled peak
    expect(curve.getAttribute('aria-label')).toContain('peak t1000');
    expect(curve.getAttribute('aria-label')).toContain('prov 30');
    // a failure-free run gets a flat label instead of an empty chart
    const flat = screen.getByTestId('arena-run-curve-9');
    expect(flat.textContent).toContain('no failure curve');
  });

  it('EM-346 — the per-agent cut lists each actor with its own rate', async () => {
    render(<ArenaPanel />);
    const ada = await screen.findByTestId('arena-agent-failures-12-agent_ada');
    expect(ada.textContent).toContain('agent_ada fails');
    expect(ada.textContent).toContain('30.0%/turn');
    // ada sorts first (highest rate); mox (0.0762) still shows, not hidden
    const mox = screen.getByTestId('arena-agent-failures-12-agent_mox');
    expect(mox.textContent).toContain('7.6%/turn');
    // EM-348 — the cut NAMES the lane behind the agent's failure mass
    const adaRoute = screen.getByTestId('arena-agent-failures-12-agent_ada-route');
    expect(adaRoute.textContent).toContain('inclusionai/ling-3.0-flash-sante:free');
    expect(adaRoute.textContent).toContain('104/110 attributed');
    expect(adaRoute.getAttribute('title')).toContain('kilo/inclusionai/ling-3.0-flash-sante:free');
    // EM-349 — the lane's OWN rate travels with the attribution
    expect(adaRoute.textContent).toContain('lane 27% (81/300)');
    // the contact card carries the cut too
    expect(screen.getByTestId('arena-contact-agent-26-agent_bram')).toBeInTheDocument();
    expect(
      screen.getByTestId('arena-contact-agent-26-agent_bram-route').textContent,
    ).toContain('gemini-3.1-flash-lite');
  });

  it('EM-349 — the by-lane board rates each lane against its own attempts', async () => {
    render(<ArenaPanel />);
    const lane = await screen.findByTestId(
      'arena-run-routes-12-kilo/inclusionai/ling-3.0-flash-sante:free',
    );
    expect(lane.textContent).toContain('81/300 · 27%');
    expect(lane.getAttribute('title')).toBe('kilo/inclusionai/ling-3.0-flash-sante:free');
    // EM-350 — a lane with a time series draws its rate sparkline; one without
    // (a low-volume lane) does not
    expect(lane.querySelector('svg')).not.toBeNull();
    const noCurve = screen.getByTestId('arena-run-routes-12-google/gemini-3.8-flash');
    expect(noCurve.textContent).toContain('19/149 · 13%');
    expect(noCurve.querySelector('svg')).toBeNull();
    // the contact card carries the board too
    expect(screen.getByTestId('arena-contact-routes-26')).toBeInTheDocument();
  });

  it('EM-351 — the cross-run lane board pools lanes over the arena runs', async () => {
    render(<ArenaPanel />);
    const board = await screen.findByTestId('arena-lane-rates');
    expect(board.textContent).toContain('lane failure rates — all runs');
    // pooled rate + the sample size (runs) travel together
    expect(screen.getByTestId('arena-lane-rates-google/gemini-3.1-flash-lite').textContent)
      .toContain('74/255 · 29% · 3 runs');
    expect(screen.getByTestId('arena-lane-rates-cohere/command-r-plus-08-2024').textContent)
      .toContain('0/13 · 0% · 1 run');
    // a lane that looks bad in ONE draw is shown against a single run
    expect(
      screen.getByTestId('arena-lane-rates-kilo/inclusionai/ling-3.0-flash-sante:free')
        .textContent,
    ).toContain('218/1449 · 15% · 1 run');
  });

  it('EM-352 — a chronically bad lane flags itself, a single draw never does', async () => {
    render(<ArenaPanel />);
    const board = await screen.findByTestId('arena-lane-rates');
    // the count rides the summary so the warning is visible while collapsed
    expect(board.textContent).toContain('⚠ 1 chronic');

    const warn = screen.getByTestId('arena-lane-rates-chronic');
    expect(warn.textContent).toContain('1 chronically bad route');
    expect(warn.textContent).toContain('≥20% in 2+ runs');

    // the lane over the threshold in ALL of its runs carries the marker + the
    // evidence, so the flag is checkable rather than a bare assertion
    const chronic = screen.getByTestId('arena-lane-rates-google/gemini-3.1-flash-lite');
    expect(chronic.textContent).toContain('74/255 · 29% · 3 runs');
    expect(chronic.textContent).toContain('≥20% in 3/3 runs');
    expect(chronic.textContent).toContain('⚠');

    // a FIFTY-PERCENT lane over ONE run is a draw, not a bad lane — the flag
    // counts runs, so it must stay dark even though its pooled rate is higher
    const draw = screen.getByTestId('arena-lane-rates-openrouter/qwen/qwen3.8-27b:free');
    expect(draw.textContent).toContain('1/2 · 50% · 1 run');
    expect(draw.textContent).not.toContain('⚠');
  });

  it('EM-353 — the per-lane rate curves are opt-in and load on demand', async () => {
    render(<ArenaPanel />);
    const load = await screen.findByTestId('arena-lane-rates-load-curves');
    // the default read never asks for the heavy per-lane curves
    expect(arenaMock).toHaveBeenCalledWith({ laneCurves: false });

    arenaMock.mockResolvedValue({ ...ARENA, lane_curves: true });
    fireEvent.click(load);

    await waitFor(() => expect(arenaMock).toHaveBeenCalledWith({ laneCurves: true }));
    // once the curves have been fetched the affordance is gone
    await waitFor(() =>
      expect(screen.queryByTestId('arena-lane-rates-load-curves')).toBeNull(),
    );
  });

  it('EM-347 — the family block shows its pooled failure rollup', async () => {
    render(<ArenaPanel />);
    const line = await screen.findByTestId('arena-family-failures-gemini');
    expect(line.textContent).toContain('family fails');
    expect(line.textContent).toContain('rej 147 (46%)');
    expect(line.textContent).toContain('28.2%/turn');
    // a failure-free family is labelled, not charted
    const llama = screen.getByTestId('arena-family-failures-llama');
    expect(llama.textContent).toContain('family fails none');
  });
});
