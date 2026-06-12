/**
 * Wave E (EM-120, contracts/wave-e.md B6 item 5) — the roster card's REP
 * mini-stat reads the backend's additive `agent.reputation`, and is
 * ABSENT-SAFE: a pre-E backend (no field) renders no REP chip and no crash.
 * The four new relationship registers also resolve via REL_COLOR (token vars).
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RosterStrip } from './RosterStrip';
import { agent, world } from '../../test-utils/fixtures';

function renderStrip(agents: ReturnType<typeof agent>[]) {
  render(
    <RosterStrip
      world={world({ agents })}
      history={[]}
      animalModels={new Map()}
      selected={null}
      onSelect={() => {}}
    />,
  );
}

describe('RosterStrip — REP mini-stat (EM-120)', () => {
  it('renders REP with a signed value when reputation is present', () => {
    renderStrip([agent({ id: 'ada', name: 'Ada', reputation: 12 })]);
    expect(screen.getByText('REP +12')).toBeInTheDocument();
    expect(screen.getByTitle(/reputation 12/)).toBeInTheDocument();
  });

  it('renders a negative reputation without a plus sign', () => {
    renderStrip([agent({ id: 'mox', name: 'Mox', reputation: -7 })]);
    expect(screen.getByText('REP -7')).toBeInTheDocument();
  });

  it('renders REP 0 for a known-zero reputation', () => {
    renderStrip([agent({ id: 'kit', name: 'Kit', reputation: 0 })]);
    expect(screen.getByText('REP 0')).toBeInTheDocument();
  });

  it('is absent-safe: no reputation field ⇒ no REP chip, card still renders', () => {
    renderStrip([agent({ id: 'old', name: 'Old' })]);
    expect(screen.getByText('Old')).toBeInTheDocument();
    expect(screen.queryByText(/^REP /)).not.toBeInTheDocument();
  });
});

describe('RosterStrip — Wave-E relationship registers (EM-113)', () => {
  it('a partner chip wears the --rel-partner token (not the neutral fallback)', () => {
    renderStrip([
      agent({
        id: 'ada',
        name: 'Ada',
        relationships: { bram: { type: 'partner', trust: 45, interactions: 9 } },
      }),
      agent({ id: 'bram', name: 'Bram' }),
    ]);
    const chip = screen.getByTitle('Bram: partner (trust 45)');
    expect(chip).toHaveStyle({ color: 'var(--rel-partner)' });
  });

  it('a feud chip wears the --rel-feud token', () => {
    renderStrip([
      agent({
        id: 'mox',
        name: 'Mox',
        relationships: { ada: { type: 'feud', trust: -44, interactions: 12 } },
      }),
      agent({ id: 'ada', name: 'Ada' }),
    ]);
    const chip = screen.getByTitle('Ada: feud (trust -44)');
    expect(chip).toHaveStyle({ color: 'var(--rel-feud)' });
  });
});
