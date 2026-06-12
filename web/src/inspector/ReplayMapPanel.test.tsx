/**
 * Wave G (EM-197) — ReplayMapPanel: the structures readout is a wrapped
 * COMPACT CHIP GRID (name + status dot, status text on the title tooltip),
 * capped with internal scroll — the old 26-row vertical list is gone. The
 * mini-map canvas (with its tick badge aria surface) renders in the cell.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { ReplayMapPanel } from './ReplayScrubber';
import { agent, PLACES, profile, resetSeq } from '../test-utils/fixtures';
import type { ReplayBuildingState } from './types';
import type { BuildingStatus } from '../types';

beforeEach(() => resetSeq());
afterEach(() => vi.restoreAllMocks());

const STATUSES: BuildingStatus[] = [
  'planned',
  'under_construction',
  'operational',
  'damaged',
  'offline',
  'abandoned',
  'destroyed',
];

/** The user's screenshot case: 26 structures. */
function buildings26(): ReplayBuildingState[] {
  return Array.from({ length: 26 }, (_, i) => ({
    id: `b${i}`,
    name: `structure-${i}`,
    kind: 'garden',
    location: 'plaza',
    status: STATUSES[i % STATUSES.length],
    progress: (i * 4) % 101,
  }));
}

function renderPanel(buildings: ReplayBuildingState[]) {
  return render(
    <ReplayMapPanel
      events={[]}
      agents={[agent({ id: 'a1' })]}
      profiles={[profile({ name: 'model-a' })]}
      places={PLACES}
      buildings={buildings}
      currentTick={5}
      maxTick={10}
    />,
  );
}

describe('ReplayMapPanel — structures chip grid (wave G §G2.4)', () => {
  it('renders ALL 26 structures as chips with status dots + title tooltips', () => {
    renderPanel(buildings26());
    const grid = screen.getByTestId('structures-chips');
    const chips = within(grid).getAllByRole('listitem');
    expect(chips).toHaveLength(26);
    for (const [i, chip] of chips.entries()) {
      // Name in the chip, status (and in-flight progress) on the tooltip.
      expect(chip).toHaveTextContent(`structure-${i}`);
      const status = STATUSES[i % STATUSES.length];
      expect(chip.getAttribute('title')).toContain(status.replace(/_/g, ' '));
      // The status dot reads the shared building-status token.
      const dot = chip.querySelector('i');
      expect(dot).not.toBeNull();
      expect(dot!.style.backgroundColor).toBe(`var(--building-${status.replace(/_/g, '-')})`);
    }
    // The full count rides the readout label (tabular).
    expect(screen.getByText('Structures · 26')).toBeInTheDocument();
  });

  it('the chip grid WRAPS and is height-capped with internal scroll', () => {
    renderPanel(buildings26());
    const grid = screen.getByTestId('structures-chips');
    for (const cls of ['flex', 'flex-wrap', 'max-h-20', 'overflow-y-auto']) {
      expect(grid.classList.contains(cls), `chip grid missing ${cls}`).toBe(true);
    }
  });

  it('keeps the map surface + tick-aware aria label; zero structures = no readout', () => {
    renderPanel([]);
    expect(screen.getByLabelText('Agent positions at tick 5')).toBeInTheDocument();
    expect(screen.queryByTestId('structures-chips')).not.toBeInTheDocument();
  });
});
