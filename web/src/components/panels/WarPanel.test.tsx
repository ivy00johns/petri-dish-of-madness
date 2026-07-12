/**
 * Wave O (EM-256–259) — WarPanel. Peacetime renders NOTHING (no wars, no
 * grievances ⇒ null, so the golden peacetime UI is unchanged). At war it names
 * both belligerent factions (aggressor marked ⚔), lists the grievance ledger
 * hottest-first, and shows aims + exhaustion. The parsing helpers are pinned
 * directly so the "src->dst" key contract can't drift.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { WarPanel, grievanceRows, sortedWars } from './WarPanel';
import { world } from '../../test-utils/fixtures';
import type { War } from '../../types';

beforeEach(() => {
  localStorage.clear(); // the panel persists its collapse preference
});

describe('WarPanel — peacetime is invisible', () => {
  it('renders nothing when there are no wars and no grievances', () => {
    const { container } = render(<WarPanel world={world()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for a null world', () => {
    const { container } = render(<WarPanel world={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('WarPanel — parsing helpers (contract pins)', () => {
  it('parses the "src->dst" grievance key and sorts hottest-first', () => {
    const rows = grievanceRows({ 'fct_a->fct_b': 20, 'fct_b->fct_a': 45 });
    expect(rows.map((r) => r.heat)).toEqual([45, 20]);
    expect(rows[0]).toEqual({ src: 'fct_b', dst: 'fct_a', heat: 45 });
  });

  it('drops a malformed grievance key (no separator) rather than half-parsing it', () => {
    expect(grievanceRows({ nonsense: 9 })).toEqual([]);
  });

  it('orders active wars ahead of settled ones', () => {
    const active: War = { id: 'w2', belligerents: ['x', 'y'], aggressor_id: 'x', start_tick: 5, aims: '', status: 'active' };
    const settled: War = { id: 'w1', belligerents: ['x', 'y'], aggressor_id: 'x', start_tick: 1, aims: '', status: 'settled' };
    expect(sortedWars({ w1: settled, w2: active }).map((w) => w.id)).toEqual(['w2', 'w1']);
  });
});

describe('WarPanel — belligerents + grievances at war', () => {
  const atWar = world({
    factions: {
      fct_aaa: { name: 'The Ashen Pact', founded_tick: 1, members: ['a1', 'a2'], war_band: ['a1'] },
      fct_bbb: { name: 'The Bram Collective', founded_tick: 2, members: ['b1'] },
    },
    wars: {
      war_1234abcd: {
        id: 'war_1234abcd',
        belligerents: ['fct_aaa', 'fct_bbb'],
        aggressor_id: 'fct_aaa',
        start_tick: 10,
        aims: 'seize the north well',
        status: 'active',
        exhaustion: { fct_aaa: 12, fct_bbb: 30 },
      },
    },
    grievances: { 'fct_bbb->fct_aaa': 45, 'fct_aaa->fct_bbb': 20 },
  });

  it('marks the aggressor faction with the ⚔ war badge', () => {
    render(<WarPanel world={atWar} />);
    const aggressorChip = screen.getByTitle('The aggressor — declared this war');
    expect(aggressorChip).toHaveTextContent('⚔');
    expect(aggressorChip).toHaveTextContent('The Ashen Pact');
  });

  it('names both belligerents and shows the war aims', () => {
    render(<WarPanel world={atWar} />);
    expect(screen.getAllByText('The Ashen Pact').length).toBeGreaterThan(0);
    expect(screen.getAllByText('The Bram Collective').length).toBeGreaterThan(0);
    expect(screen.getByText(/seize the north well/)).toBeInTheDocument();
  });

  it('lists the grievance heat hottest-first', () => {
    render(<WarPanel world={atWar} />);
    expect(screen.getByText('heat 45')).toBeInTheDocument();
    expect(screen.getByText('heat 20')).toBeInTheDocument();
  });

  it('surfaces exhaustion per belligerent', () => {
    render(<WarPanel world={atWar} />);
    expect(screen.getByText(/exhaustion 30/)).toBeInTheDocument();
  });

  it('falls back to a shortened id when a belligerent has no named faction', () => {
    const noName = world({
      wars: {
        war_x: { id: 'war_x', belligerents: ['fct_longunnamedid', 'fct_bbb'], aggressor_id: 'fct_longunnamedid', start_tick: 3, aims: '', status: 'active' },
      },
    });
    render(<WarPanel world={noName} />);
    // 'fct_longunnamedid' is > 10 chars ⇒ truncated with an ellipsis.
    expect(screen.getByText('fct_longun…')).toBeInTheDocument();
  });
});
