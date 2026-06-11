/**
 * Wave D2 (EM-158/166) — the cadence-tier chip + reflex-streak readout.
 *
 * world_state agents now optionally carry `cadence_tier` and `reflex_streak`
 * (additive backend keys). The roster strip and the agent panel show a small
 * tier chip beside the model chip; background agents with an active reflex
 * streak surface it in the panel. Pre-D2 backends (no keys) render NO chip.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AgentPanels } from './AgentPanels';
import { RosterStrip } from './RosterStrip';
import { agent, world } from '../../test-utils/fixtures';

const noop = () => {};

function renderStrip(w: ReturnType<typeof world>) {
  return render(
    <RosterStrip
      world={w}
      history={[]}
      animalModels={new Map()}
      selected={null}
      onSelect={noop}
    />,
  );
}

describe('RosterStrip — cadence tier chip (EM-166)', () => {
  it('shows PRO / SUP / BG chips per tier', () => {
    const w = world({
      agents: [
        agent({ id: 'a1', name: 'Ada', cadence_tier: 'protagonist' }),
        agent({ id: 'a2', name: 'Bo', cadence_tier: 'supporting' }),
        agent({ id: 'a3', name: 'Cy', cadence_tier: 'background' }),
      ],
    });
    renderStrip(w);
    expect(screen.getByText('PRO')).toBeInTheDocument();
    expect(screen.getByText('SUP')).toBeInTheDocument();
    expect(screen.getByText('BG')).toBeInTheDocument();
  });

  it('renders no chip when the backend predates Wave D2 (no cadence_tier)', () => {
    const w = world({ agents: [agent({ id: 'a1', name: 'Ada' })] });
    renderStrip(w);
    expect(screen.queryByText('PRO')).not.toBeInTheDocument();
    expect(screen.queryByText('BG')).not.toBeInTheDocument();
  });

  it('folds an active reflex streak into the chip tooltip', () => {
    const w = world({
      agents: [
        agent({ id: 'a1', name: 'Cy', cadence_tier: 'background', reflex_streak: 4 }),
      ],
    });
    renderStrip(w);
    expect(screen.getByText('BG')).toHaveAttribute(
      'title',
      expect.stringContaining('reflex ×4'),
    );
  });
});

describe('AgentPanels — tier chip + reflex streak (EM-166)', () => {
  it('shows the tier chip beside the model badge', () => {
    const w = world({
      agents: [agent({ id: 'a1', name: 'Ada', cadence_tier: 'supporting' })],
    });
    render(<AgentPanels world={w} />);
    expect(screen.getByText('SUP')).toBeInTheDocument();
  });

  it('surfaces the reflex streak for background agents', () => {
    const w = world({
      agents: [
        agent({ id: 'a1', name: 'Cy', cadence_tier: 'background', reflex_streak: 6 }),
      ],
    });
    render(<AgentPanels world={w} />);
    expect(screen.getByText('REFLEX STREAK')).toBeInTheDocument();
    expect(screen.getByText('×6')).toBeInTheDocument();
  });

  it('hides the streak readout at 0 and for non-background tiers', () => {
    const w = world({
      agents: [
        agent({ id: 'a1', name: 'Cy', cadence_tier: 'background', reflex_streak: 0 }),
        agent({ id: 'a2', name: 'Ada', cadence_tier: 'protagonist', reflex_streak: 3 }),
      ],
    });
    render(<AgentPanels world={w} />);
    expect(screen.queryByText('REFLEX STREAK')).not.toBeInTheDocument();
  });
});
