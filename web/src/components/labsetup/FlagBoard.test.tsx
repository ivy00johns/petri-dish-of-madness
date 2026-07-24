import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { FlagBoard } from './FlagBoard';
import type { FlagsResponse } from '../../types';

const FLAGS: FlagsResponse = {
  baked: { comm: false, settlements: true, lane_failover: true },
  groups: { prompt_weight: ['comm', 'settlements'], routing_ops: ['lane_failover'] },
};

describe('FlagBoard', () => {
  it('renders both groups with their flags', () => {
    render(<FlagBoard flags={FLAGS} pending={FLAGS.baked} onToggle={() => {}} />);
    expect(screen.getByText(/prompt-weight/i)).toBeInTheDocument();
    expect(screen.getByText(/routing/i)).toBeInTheDocument();
    expect(screen.getByLabelText('comm')).toBeInTheDocument();
  });
  it('marks a flag changed when pending differs from baked', () => {
    render(<FlagBoard flags={FLAGS} pending={{ ...FLAGS.baked, comm: true }} onToggle={() => {}} />);
    expect(screen.getByTestId('flag-row-comm')).toHaveAttribute('data-changed', 'true');
  });
  it('calls onToggle with the flag name', () => {
    const onToggle = vi.fn();
    render(<FlagBoard flags={FLAGS} pending={FLAGS.baked} onToggle={onToggle} />);
    fireEvent.click(screen.getByLabelText('comm'));
    expect(onToggle).toHaveBeenCalledWith('comm');
  });
});
