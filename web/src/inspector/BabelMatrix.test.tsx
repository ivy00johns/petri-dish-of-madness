/**
 * EM-314 — BabelMatrix panel tests.
 *
 * The heatmap is FEED/VIEWER chrome behind the default-OFF babel_matrix.enabled
 * flag. These cover: the flag defaults OFF; the grid renders model rows/cols +
 * per-cell rates from the backend projection; a cell click reveals its feed
 * receipts (the click-through evidence); the family filter re-queries; and the
 * disabled / empty states are labeled rather than blank.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('./api', () => ({
  inspectorApi: { babelMatrix: vi.fn() },
}));

import { inspectorApi } from './api';
import type { BabelMatrix as BabelMatrixData } from './api';
import BabelMatrix, { BABEL_MATRIX_ENABLED } from './BabelMatrix';
import type { ModelProfile } from '../types';

const babelMock = inspectorApi.babelMatrix as Mock;

const PROFILES: ModelProfile[] = [
  { name: 'gemini-flash', adapter: 'gemini', model_id: 'g', color: '#00aaff' },
  { name: 'groq-llama', adapter: 'groq', model_id: 'l', color: '#ff8800' },
];

function sampleMatrix(): BabelMatrixData {
  return {
    version: '1.0.0',
    family: null,
    families: ['teach', 'trade'],
    models: ['gemini-flash', 'groq-llama'],
    cells: [
      {
        actor: 'gemini-flash',
        target: 'groq-llama',
        total: 4,
        positive: 1,
        rate: 0.25,
        ci_lo: 0.05,
        ci_hi: 0.7,
        by_family: { trade: { total: 4, positive: 1, rate: 0.25 } },
        receipts: [
          {
            seq: 42,
            tick: 12,
            kind: 'trade_declined',
            family: 'trade',
            positive: false,
            actor_id: 'a',
            target_id: 'b',
            text: 'Ada declines Bo the broker a trade offer.',
            routed_via: null,
          },
          {
            seq: 40,
            tick: 10,
            kind: 'trade_settled',
            family: 'trade',
            positive: true,
            actor_id: 'a',
            target_id: 'b',
            text: 'Ada and Bo settle a trade.',
            routed_via: 'gemini-2.0-flash',
          },
        ],
      },
      {
        actor: 'groq-llama',
        target: 'gemini-flash',
        total: 2,
        positive: 2,
        rate: 1.0,
        ci_lo: 0.34,
        ci_hi: 1.0,
        by_family: { teach: { total: 2, positive: 2, rate: 1.0 } },
        receipts: [],
      },
    ],
    totals: { outcomes: 6, positive: 3, cells: 2, receipts_capped: false },
  };
}

beforeEach(() => {
  babelMock.mockReset();
});

describe('BabelMatrix (EM-314)', () => {
  it('the frontend flag defaults OFF (deferred sign-off — mirror ROAD_MESH_ENABLED)', () => {
    expect(BABEL_MATRIX_ENABLED).toBe(false);
  });

  it('renders the N×N grid with model axes and per-cell rates', async () => {
    babelMock.mockResolvedValue(sampleMatrix());
    render(<BabelMatrix runId={7} profiles={PROFILES} />);

    // Header stats.
    expect(await screen.findByText(/dyads/)).toBeInTheDocument();
    // Both models appear as axis labels (row header + column header each).
    expect(screen.getAllByText('gemini-flash').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('groq-llama').length).toBeGreaterThanOrEqual(2);
    // The 25% cell rate is rendered.
    expect(screen.getByText('25%')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    // Scoped to the passed run.
    expect(babelMock).toHaveBeenCalledWith(7, { family: undefined });
  });

  it('clicking a cell reveals its feed receipts (click-through evidence)', async () => {
    babelMock.mockResolvedValue(sampleMatrix());
    render(<BabelMatrix runId={7} profiles={PROFILES} />);

    // The gemini→llama cell: labeled by its title (1/4 positive).
    const cell = await screen.findByRole('cell', {
      name: /gemini-flash → groq-llama: 1\/4 positive/,
    });
    await userEvent.click(cell);

    // Receipts drawer shows the exact event text, both polarities.
    expect(await screen.findByText('Ada and Bo settle a trade.')).toBeInTheDocument();
    expect(screen.getByText('Ada declines Bo the broker a trade offer.')).toBeInTheDocument();
    // Ground-truth routed_via annotation surfaces on the settle receipt.
    expect(screen.getByText(/via gemini-2\.0-flash/)).toBeInTheDocument();
  });

  it('the family filter re-queries the backend with the family param', async () => {
    babelMock.mockResolvedValue(sampleMatrix());
    render(<BabelMatrix runId={7} profiles={PROFILES} />);

    const tradeTab = await screen.findByRole('button', { name: 'trade' });
    await userEvent.click(tradeTab);

    await waitFor(() =>
      expect(babelMock).toHaveBeenCalledWith(7, { family: 'trade' }),
    );
  });

  it('shows a labeled disabled/unreachable state when the endpoint returns null', async () => {
    babelMock.mockResolvedValue(null);
    render(<BabelMatrix runId={null} profiles={PROFILES} />);
    expect(await screen.findByText(/babel_matrix\.enabled/)).toBeInTheDocument();
    // Active run → run_id omitted.
    expect(babelMock).toHaveBeenCalledWith(undefined, { family: undefined });
  });

  it('shows a labeled empty state when no dyads have known models on both ends', async () => {
    babelMock.mockResolvedValue({
      version: '1.0.0',
      family: null,
      families: [],
      models: [],
      cells: [],
      totals: { outcomes: 0, positive: 0, cells: 0, receipts_capped: false },
    } satisfies BabelMatrixData);
    render(<BabelMatrix runId={1} profiles={PROFILES} />);
    expect(
      await screen.findByText(/No dyadic outcomes with known models/),
    ).toBeInTheDocument();
  });

  it('empty cells render an inert placeholder, not a clickable button', async () => {
    babelMock.mockResolvedValue(sampleMatrix());
    render(<BabelMatrix runId={7} profiles={PROFILES} />);
    // The gemini→gemini diagonal has no data → non-button "no outcomes" cell.
    const inert = await screen.findByRole('cell', {
      name: /gemini-flash to gemini-flash: no outcomes/,
    });
    expect(inert.tagName).not.toBe('BUTTON');
  });
});
