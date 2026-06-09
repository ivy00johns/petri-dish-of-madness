/**
 * RunBrowser FORK affordance + lineage chips (W11b EM-101, frontend-inspector
 * v1.3.0 §10) — separate file from RunBrowser.test.tsx (the W11a suite is
 * read-only to wave 2). Covers: fork only on archived rows, the inline tick
 * form defaulting to max_tick, client-side range validation (no API call),
 * the success notice + list refresh, the labeled inline failure, and the
 * "↩ #N @ tick T" lineage chip. The api module is mocked; no network.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('./api', () => ({
  inspectorApi: {
    runs: vi.fn(),
    forkRun: vi.fn(),
    runAnalytics: vi.fn(async () => null),
  },
}));
vi.mock('./RunComparison', () => ({ default: () => null }));

import { inspectorApi } from './api';
import type { RunRow } from './api';
import RunBrowser from './RunBrowser';

const runsMock = inspectorApi.runs as Mock;
const forkMock = inspectorApi.forkRun as Mock;

function runRow(partial: Partial<RunRow> & { id: number }): RunRow {
  return {
    started_at: '2026-06-09T10:00:00Z',
    ended_at: null,
    status: 'ended',
    is_active: false,
    max_tick: 50,
    event_count: 10,
    config_summary: { agents: [] },
    ...partial,
  };
}

function renderBrowser() {
  render(<RunBrowser mockMode={false} selectedRunId={null} onSelectRun={vi.fn()} />);
}

beforeEach(() => {
  runsMock.mockReset();
  forkMock.mockReset();
});

describe('RunBrowser — fork affordance (EM-101)', () => {
  it('offers FORK on archived rows only (the live run is still writing)', async () => {
    runsMock.mockResolvedValue([
      runRow({ id: 2, is_active: true, status: 'running' }),
      runRow({ id: 1 }),
    ]);
    renderBrowser();
    expect(await screen.findByText('#2')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /⑂ fork$/i })).toHaveLength(1);
  });

  it('the inline form defaults the tick to the run’s max_tick', async () => {
    const user = userEvent.setup();
    runsMock.mockResolvedValue([runRow({ id: 1, max_tick: 42 })]);
    renderBrowser();

    await user.click(await screen.findByRole('button', { name: /⑂ fork$/i }));
    expect(screen.getByLabelText('fork at tick')).toHaveValue(42);
    expect(screen.getByText('/ 42')).toBeInTheDocument();
  });

  it('rejects an out-of-range tick inline WITHOUT calling the API', async () => {
    const user = userEvent.setup();
    runsMock.mockResolvedValue([runRow({ id: 1, max_tick: 42 })]);
    renderBrowser();

    await user.click(await screen.findByRole('button', { name: /⑂ fork$/i }));
    const input = screen.getByLabelText('fork at tick');
    await user.clear(input);
    await user.type(input, '99');
    await user.click(screen.getByRole('button', { name: 'Fork run 1 at the chosen tick' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'tick must be an integer in 0–42',
    );
    expect(forkMock).not.toHaveBeenCalled();
  });

  it('a successful fork posts {run_id, tick}, announces the new run and refreshes', async () => {
    const user = userEvent.setup();
    runsMock.mockResolvedValue([runRow({ id: 1, max_tick: 42 })]);
    forkMock.mockResolvedValue({ ok: true, runId: 9 });
    renderBrowser();

    await user.click(await screen.findByRole('button', { name: /⑂ fork$/i }));
    const input = screen.getByLabelText('fork at tick');
    await user.clear(input);
    await user.type(input, '26');
    await user.click(screen.getByRole('button', { name: 'Fork run 1 at the chosen tick' }));

    expect(forkMock).toHaveBeenCalledWith(1, 26);
    const notice = await screen.findByRole('status');
    expect(notice).toHaveTextContent('forked run #1 @ tick 26 → run #9 created');
    expect(notice).toHaveTextContent('paused');
    // The list re-fetches so the new run (MAX(id)) tops the newest-first list.
    await waitFor(() => expect(runsMock).toHaveBeenCalledTimes(2));
  });

  it('renders a fork FAILURE inline, labeled — never thrown', async () => {
    const user = userEvent.setup();
    runsMock.mockResolvedValue([runRow({ id: 1, max_tick: 42 })]);
    forkMock.mockResolvedValue({
      ok: false,
      status: 404,
      message: 'run #1 not found on the backend',
    });
    renderBrowser();

    await user.click(await screen.findByRole('button', { name: /⑂ fork$/i }));
    await user.click(screen.getByRole('button', { name: 'Fork run 1 at the chosen tick' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'run #1 not found on the backend',
    );
    expect(runsMock).toHaveBeenCalledTimes(1); // no refresh on failure
  });
});

describe('RunBrowser — lineage chips (EM-101)', () => {
  it('a forked run wears the "↩ #parent @ tick T" chip', async () => {
    runsMock.mockResolvedValue([
      runRow({ id: 3, forked_from: 2, forked_at_tick: 7 }),
      runRow({ id: 2 }),
    ]);
    renderBrowser();

    expect(await screen.findByText(/↩ #2/)).toBeInTheDocument();
    expect(screen.getByText(/@ tick 7/)).toBeInTheDocument();
  });

  it('root runs (forked_from null/absent) carry no lineage chip', async () => {
    runsMock.mockResolvedValue([
      runRow({ id: 2, forked_from: null, forked_at_tick: null }),
      runRow({ id: 1 }),
    ]);
    renderBrowser();
    expect(await screen.findByText('#2')).toBeInTheDocument();
    expect(screen.queryByText(/↩ #/)).not.toBeInTheDocument();
  });
});
