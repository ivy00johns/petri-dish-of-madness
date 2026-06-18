/**
 * Wave H4 (EM-209) — RosterStrip bond indicator.
 *
 * Covers:
 *  • When animal.owner_id resolves to a living agent, the critter card shows
 *    a "🔗 {owner}'s pet" line (the grief-capstone adoption bond UI).
 *  • When owner_id is absent/null, no bond line is shown (absent-safe).
 *  • When owner_id references a dead agent, no bond line is shown (bond
 *    indicator tracks living owners only — the pet outlived its owner).
 *  • Existing critter card content (name, mood, location) is preserved.
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RosterStrip } from './RosterStrip';
import { agent, animal, world } from '../../test-utils/fixtures';

function renderStrip(
  animals: ReturnType<typeof animal>[],
  agents: ReturnType<typeof agent>[] = [],
) {
  render(
    <RosterStrip
      world={world({ animals, agents })}
      history={[]}
      animalModels={new Map()}
      selected={null}
      onSelect={() => {}}
    />,
  );
}

describe('RosterStrip — bond indicator (Wave H4 EM-209)', () => {
  it("shows \"🔗 {owner}'s pet\" when the animal is owned by a living agent", () => {
    renderStrip(
      [animal({ id: 'whisker', name: 'Whisker', owner_id: 'vesper' })],
      [agent({ id: 'vesper', name: 'Vesper', alive: true })],
    );
    expect(screen.getByTitle("Adopted by Vesper")).toBeInTheDocument();
    expect(screen.getByText(/Vesper.*pet/)).toBeInTheDocument();
  });

  it('shows no bond indicator when owner_id is absent', () => {
    renderStrip(
      [animal({ id: 'stray', name: 'Stray' })],
      [agent({ id: 'vesper', name: 'Vesper', alive: true })],
    );
    expect(screen.queryByTitle(/Adopted by/)).not.toBeInTheDocument();
    expect(screen.queryByText(/pet/)).not.toBeInTheDocument();
  });

  it('shows no bond indicator when owner_id is null', () => {
    renderStrip(
      [animal({ id: 'feral', name: 'Feral', owner_id: null })],
      [agent({ id: 'vesper', name: 'Vesper', alive: true })],
    );
    expect(screen.queryByTitle(/Adopted by/)).not.toBeInTheDocument();
  });

  it('shows no bond indicator when the owner is dead (bond dies with the owner)', () => {
    renderStrip(
      [animal({ id: 'whisker', name: 'Whisker', owner_id: 'vesper' })],
      [agent({ id: 'vesper', name: 'Vesper', alive: false })],
    );
    expect(screen.queryByTitle(/Adopted by Vesper/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Vesper.*pet/)).not.toBeInTheDocument();
  });

  it('shows no bond indicator when owner_id references a missing agent', () => {
    renderStrip(
      [animal({ id: 'whisker', name: 'Whisker', owner_id: 'ghost-agent' })],
      // ghost-agent is not in the agents list
      [agent({ id: 'vesper', name: 'Vesper', alive: true })],
    );
    expect(screen.queryByTitle(/Adopted by/)).not.toBeInTheDocument();
  });

  it('preserves existing critter card content alongside the bond line', () => {
    renderStrip(
      [animal({ id: 'whisker', name: 'Whisker', owner_id: 'vesper', mood: 'content' })],
      [agent({ id: 'vesper', name: 'Vesper', alive: true })],
    );
    // The animal's own name and mood are still rendered.
    expect(screen.getByText('Whisker')).toBeInTheDocument();
    expect(screen.getByText(/content/)).toBeInTheDocument();
    // And the bond line.
    expect(screen.getByTitle('Adopted by Vesper')).toBeInTheDocument();
  });
});
