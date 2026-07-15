import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RecommenderPanel } from './Recommender';
import type { Recommendation } from '../../types';

const REC: Recommendation = {
  verdict: 'free_at_risk',
  banner: '≈6000 → known risk: free lanes may truncate.',
  safe: ['mistral-small'],
  risky: ['kimi'],
  castPinRisks: [{ agent: 'Mox', lane: 'kimi', reason: 'reasoning lane — truncates' }],
};

describe('RecommenderPanel', () => {
  it('shows the verdict banner', () => {
    render(<RecommenderPanel rec={REC} />);
    expect(screen.getByText(/known risk/i)).toBeInTheDocument();
  });
  it('lists safe and risky lanes and cast-pin risks', () => {
    render(<RecommenderPanel rec={REC} />);
    expect(screen.getByText('mistral-small')).toBeInTheDocument();
    expect(screen.getByText(/Mox.*kimi/)).toBeInTheDocument();
  });
});
