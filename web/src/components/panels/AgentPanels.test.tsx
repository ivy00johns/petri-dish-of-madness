/**
 * AgentPanels smoke (EM-043 / EM-070) — the DYING countdown badge renders
 * exactly when the W9 backend says so: alive, energy 0, and a numeric
 * turns_until_death. Absent on older backends / healthy agents.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AgentPanels } from './AgentPanels';
import { agent, world } from '../../test-utils/fixtures';

describe('AgentPanels — dying badge (EM-070)', () => {
  it('renders the countdown when energy is 0 and turns_until_death is present', () => {
    const w = world({
      agents: [agent({ id: 'a1', name: 'Ada', energy: 0, turns_until_death: 3 })],
    });
    render(<AgentPanels world={w} />);
    expect(screen.getByText(/DYING — 3 TURNS LEFT/)).toBeInTheDocument();
  });

  it('singularizes at 1 turn left', () => {
    const w = world({
      agents: [agent({ id: 'a1', name: 'Ada', energy: 0, turns_until_death: 1 })],
    });
    render(<AgentPanels world={w} />);
    expect(screen.getByText(/DYING — 1 TURN LEFT/)).toBeInTheDocument();
  });

  it('is absent without turns_until_death (pre-W9 backend / mock), even at 0 energy', () => {
    const w = world({ agents: [agent({ id: 'a1', name: 'Ada', energy: 0 })] });
    render(<AgentPanels world={w} />);
    expect(screen.queryByText(/DYING/)).not.toBeInTheDocument();
  });

  it('is absent for healthy and dead agents (dead get the DEAD chip instead)', () => {
    const w = world({
      agents: [
        agent({ id: 'a1', name: 'Ada', energy: 80, turns_until_death: null }),
        agent({ id: 'a2', name: 'Bo', energy: 0, alive: false, turns_until_death: 0 }),
      ],
    });
    render(<AgentPanels world={w} />);
    expect(screen.queryByText(/DYING/)).not.toBeInTheDocument();
    expect(screen.getByText('DEAD')).toBeInTheDocument();
  });
});
