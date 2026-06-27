/**
 * EM-202 — A/B persona-across-models, the roster surface.
 *
 * A/B variants share a base name; the backend names each `${base}·${tag}`. The
 * roster correlates them by base: a base with ≥2 `·`-tagged variants is an A/B
 * group, so each variant wears an "A/B" chip, renders the base distinctly from
 * its `·tag`, and is correlated by the existing model chip.
 *
 * Covers:
 *  • two variants sharing a base ⇒ both cards carry the A/B chip + the group
 *    title naming the shared base;
 *  • a lone agent whose name merely contains `·` (no sibling) is NOT a group —
 *    no A/B chip;
 *  • a plain agent (no `·`) renders unchanged;
 *  • the parseAbName / abGroupCounts helpers behave at the unit level.
 */
import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { RosterStrip, parseAbName, abGroupCounts } from './RosterStrip';
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

describe('parseAbName / abGroupCounts (EM-202)', () => {
  it('parses a `base·tag` name', () => {
    expect(parseAbName('Vesper·mistral')).toEqual({ base: 'Vesper', tag: 'mistral' });
  });
  it('returns null for a plain name (no separator)', () => {
    expect(parseAbName('Vesper')).toBeNull();
  });
  it('returns null when the `·` has an empty side', () => {
    expect(parseAbName('·tag')).toBeNull();
    expect(parseAbName('base·')).toBeNull();
  });
  it('counts variants per base (≥2 ⇒ a group)', () => {
    const counts = abGroupCounts([
      agent({ id: 'a', name: 'Vesper·mistral' }),
      agent({ id: 'b', name: 'Vesper·groq' }),
      agent({ id: 'c', name: 'Solo·only' }),
      agent({ id: 'd', name: 'Plain' }),
    ]);
    expect(counts.get('Vesper')).toBe(2);
    expect(counts.get('Solo')).toBe(1);
    expect(counts.has('Plain')).toBe(false);
  });
});

describe('RosterStrip — A/B group surfacing (EM-202)', () => {
  it('marks both variants of a shared base as an A/B group', () => {
    renderStrip([
      agent({ id: 'a', name: 'Vesper·mistral', profile: 'mistral-small' }),
      agent({ id: 'b', name: 'Vesper·groq', profile: 'groq-llama' }),
    ]);

    // Both variant cards carry the A/B group chip naming the shared base.
    const chips = screen.getAllByTitle(/A\/B group "Vesper"/);
    expect(chips).toHaveLength(2);

    // Each card shows the base + the `·tag` distinction and its model chip.
    const cardA = screen.getByTitle(/A\/B variant of "Vesper" — running mistral-small/);
    expect(within(cardA).getByText('·mistral')).toBeInTheDocument();
    const cardB = screen.getByTitle(/A\/B variant of "Vesper" — running groq-llama/);
    expect(within(cardB).getByText('·groq')).toBeInTheDocument();
  });

  it('does NOT mark a lone `·` name (no sibling) as a group', () => {
    renderStrip([
      agent({ id: 'a', name: 'Solo·only', profile: 'mistral-small' }),
    ]);
    expect(screen.queryByText('A/B')).not.toBeInTheDocument();
    // The full name renders as-is (not split into base + tag chips).
    expect(screen.getByText('Solo·only')).toBeInTheDocument();
  });

  it('renders a plain agent (no `·`) unchanged', () => {
    renderStrip([agent({ id: 'a', name: 'Bram' })]);
    expect(screen.queryByText('A/B')).not.toBeInTheDocument();
    expect(screen.getByText('Bram')).toBeInTheDocument();
  });
});
