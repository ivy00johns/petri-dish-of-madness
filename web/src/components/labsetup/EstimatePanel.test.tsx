// web/src/components/labsetup/EstimatePanel.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EstimatePanel } from './EstimatePanel';
import type { EstimateResult } from '../../types';

describe('EstimatePanel', () => {
  it('shows the total and per-flag breakdown', () => {
    const est: EstimateResult = {
      ok: true, total_input_tokens: 3940, output_budget: 1024, tokenizer: 'cl100k_base',
      breakdown: [{ key: 'base', tokens: 2600 }, { key: 'comm', tokens: 340 }],
    };
    render(<EstimatePanel estimate={est} loading={false} />);
    expect(screen.getByText(/3,?940/)).toBeInTheDocument();
    expect(screen.getByText('comm')).toBeInTheDocument();
  });
  it('surfaces an error instead of a fake number', () => {
    const est: EstimateResult = { ok: false, error: 'boom' };
    render(<EstimatePanel estimate={est} loading={false} />);
    expect(screen.getByText(/couldn.t estimate/i)).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });
});
