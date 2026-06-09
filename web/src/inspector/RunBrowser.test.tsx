/**
 * RunBrowser (W11a EM-086, frontend-inspector.md §8) — component smoke:
 * newest-first rendering, the ACTIVE chip driven by `is_active` ONLY (a dead
 * run stored as status='running' must read ARCHIVED), the three labeled
 * empty/unreachable states (§7 idiom: never a blank), and view/return-to-live
 * selection semantics. The api module is mocked; no network.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('./api', () => ({
  inspectorApi: {
    runs: vi.fn(),
    // RunComparison (rendered only with two cmp picks) reaches for this.
    runAnalytics: vi.fn(async () => null),
  },
}));

// RunComparison pulls in AWIDashboard → uplot, whose module init needs a real
// matchMedia. It only renders once TWO cmp picks exist (not exercised here),
// so stub it out and keep this a pure RunBrowser unit test.
vi.mock('./RunComparison', () => ({ default: () => null }));

import { inspectorApi } from './api';
import type { RunRow } from './api';
import RunBrowser, { humanizeTimestamp } from './RunBrowser';

const runsMock = inspectorApi.runs as Mock;

function runRow(partial: Partial<RunRow> & { id: number }): RunRow {
  return {
    started_at: '2026-06-09T10:00:00Z',
    ended_at: null,
    status: 'running',
    is_active: false,
    max_tick: 0,
    event_count: 0,
    config_summary: { agents: [] },
    ...partial,
  };
}

function renderBrowser(props: Partial<Parameters<typeof RunBrowser>[0]> = {}) {
  const onSelectRun = vi.fn();
  render(
    <RunBrowser
      mockMode={false}
      selectedRunId={null}
      onSelectRun={onSelectRun}
      {...props}
    />,
  );
  return { onSelectRun };
}

beforeEach(() => {
  runsMock.mockReset();
});

describe('RunBrowser — run list', () => {
  it('renders runs newest-first with the ACTIVE chip ONLY on is_active', async () => {
    runsMock.mockResolvedValue([
      runRow({ id: 3, is_active: true, status: 'running', max_tick: 42, event_count: 900 }),
      // The EM-086 trap: a CRASHED run whose stored status is still 'running'.
      runRow({ id: 2, is_active: false, status: 'running' }),
      runRow({ id: 1, is_active: false, status: 'ended', ended_at: '2026-06-09T11:00:00Z' }),
    ]);
    renderBrowser();

    expect(await screen.findByText('#3')).toBeInTheDocument();
    // Document order = newest first (the api client guarantees the sort).
    expect(screen.getAllByText(/^#\d+$/).map((el) => el.textContent)).toEqual([
      '#3', '#2', '#1',
    ]);

    // Exactly ONE active chip, on run 3; the status='running' zombie reads
    // archived (status is secondary text, never a liveness signal).
    expect(screen.getAllByText('active')).toHaveLength(1);
    expect(screen.getAllByText('archived')).toHaveLength(2);
    expect(screen.getAllByText('status:running')).toHaveLength(2);

    // Aggregates render on the row.
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('900')).toBeInTheDocument();
  });

  it('renders the config_summary agent roster with profile chips', async () => {
    runsMock.mockResolvedValue([
      runRow({
        id: 1,
        config_summary: { agents: [{ name: 'Ada', profile: 'model-a' }] },
      }),
    ]);
    renderBrowser();
    expect(await screen.findByText(/Ada/)).toBeInTheDocument();
    expect(screen.getByText(/model-a/)).toBeInTheDocument();
  });

  it('labels a legacy run with no roster instead of rendering a hole', async () => {
    runsMock.mockResolvedValue([runRow({ id: 1, config_summary: {} })]);
    renderBrowser();
    expect(
      await screen.findByText('no agent roster in config summary'),
    ).toBeInTheDocument();
  });
});

describe('RunBrowser — selection semantics (§8)', () => {
  it('view on an archived run selects it; view on the active run returns to live', async () => {
    const user = userEvent.setup();
    const archived = runRow({ id: 1 });
    const active = runRow({ id: 2, is_active: true });
    runsMock.mockResolvedValue([active, archived]);
    const { onSelectRun } = renderBrowser();

    await user.click(await screen.findByRole('button', { name: 'view' }));
    expect(onSelectRun).toHaveBeenLastCalledWith(
      expect.objectContaining({ id: 1, is_active: false }),
    );

    await user.click(screen.getByRole('button', { name: 'live' }));
    expect(onSelectRun).toHaveBeenLastCalledWith(null);
  });

  it('viewing the already-viewed run toggles back to live', async () => {
    const user = userEvent.setup();
    runsMock.mockResolvedValue([runRow({ id: 1 })]);
    const { onSelectRun } = renderBrowser({ selectedRunId: 1 });

    await user.click(await screen.findByRole('button', { name: /viewing/ }));
    expect(onSelectRun).toHaveBeenLastCalledWith(null);
  });
});

describe('RunBrowser — labeled empty/unreachable states (§7)', () => {
  it('labels zero persisted runs', async () => {
    runsMock.mockResolvedValue([]);
    renderBrowser();
    expect(await screen.findByText('no persisted runs yet')).toBeInTheDocument();
  });

  it('labels an unreachable backend (runs() → null) distinctly from zero runs', async () => {
    runsMock.mockResolvedValue(null);
    renderBrowser();
    expect(
      await screen.findByText('no backend — live session only'),
    ).toBeInTheDocument();
    expect(screen.queryByText('no persisted runs yet')).not.toBeInTheDocument();
  });

  it('mock mode short-circuits: labeled state, NO fetch', () => {
    renderBrowser({ mockMode: true });
    expect(screen.getByText('no backend — live session only')).toBeInTheDocument();
    expect(runsMock).not.toHaveBeenCalled();
  });
});

describe('humanizeTimestamp', () => {
  it('formats an absolute stamp with a relative suffix', () => {
    const now = new Date('2026-06-09T15:00:00Z');
    expect(humanizeTimestamp('2026-06-09T12:00:00Z', now)).toMatch(/ · 3h ago$/);
    expect(humanizeTimestamp(new Date(now.getTime() - 30_000).toISOString(), now)).toMatch(
      / · just now$/,
    );
  });

  it('falls back to the raw string (or a dash) when unparsable', () => {
    expect(humanizeTimestamp('garbage')).toBe('garbage');
    expect(humanizeTimestamp('')).toBe('—');
  });
});
