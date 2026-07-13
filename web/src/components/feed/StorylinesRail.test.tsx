/**
 * StorylinesRail (EM-312) — the feed's drama index. Empty renders NOTHING (a
 * quiet town / flag-off shape stays byte-identical). A promoted rivalry shows
 * its named badge + status chip; clicking it selects the thread and reveals the
 * verbatim "story so far" beats. The scoring itself is pinned in
 * lib/storylines.test.ts — these tests cover the rail's render + selection wiring.
 */
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { StorylinesRail } from './StorylinesRail';
import { agent, ev, resetSeq, world } from '../../test-utils/fixtures';
import type { WorldEvent } from '../../types';

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the rail persists its collapse preference
});

const W = world({
  agents: [agent({ id: 'a1', name: 'Ada' }), agent({ id: 'a2', name: 'Vesper II' })],
});

/** A recurring hostile pair → a promoted RIVALRY. */
function rivalryHistory(): WorldEvent[] {
  return [
    ev({ kind: 'conflict', actor_id: 'a1', target_id: 'a2', tick: 1, text: 'Ada insults Vesper II' }),
    ev({ kind: 'conflict', actor_id: 'a1', target_id: 'a2', tick: 3, text: 'Vesper II retaliates' }),
    ev({ kind: 'conflict', actor_id: 'a1', target_id: 'a2', tick: 5, text: 'a scuffle in the plaza' }),
  ];
}

describe('StorylinesRail — empty is invisible', () => {
  it('renders nothing with no history', () => {
    const { container } = render(
      <StorylinesRail world={W} history={[]} selectedId={null} onSelect={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when nothing clears the promote bar', () => {
    // Two conflicts on one tick — fails the recurrence gate.
    const h = [
      ev({ kind: 'conflict', actor_id: 'a1', target_id: 'a2', tick: 1, text: 'x' }),
      ev({ kind: 'conflict', actor_id: 'a1', target_id: 'a2', tick: 1, text: 'y' }),
    ];
    const { container } = render(
      <StorylinesRail world={W} history={h} selectedId={null} onSelect={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('StorylinesRail — a promoted rivalry', () => {
  it('names the thread with its archetype badge + status', () => {
    render(<StorylinesRail world={W} history={rivalryHistory()} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByText('Ada v. Vesper II')).toBeInTheDocument();
    expect(screen.getByText('RIVALRY')).toBeInTheDocument();
    expect(screen.getByText('TENSION')).toBeInTheDocument();
  });

  it('selects the thread on click (parent gets the Storyline)', () => {
    const onSelect = vi.fn();
    render(<StorylinesRail world={W} history={rivalryHistory()} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('Ada v. Vesper II'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    const arg = onSelect.mock.calls[0][0];
    expect(arg.id).toBe('dyad:a1~a2');
    expect(arg.principals).toEqual(['a1', 'a2']);
  });

  it('reveals the VERBATIM story-so-far beats only when selected', () => {
    const { rerender } = render(
      <StorylinesRail world={W} history={rivalryHistory()} selectedId={null} onSelect={() => {}} />,
    );
    expect(screen.queryByText('a scuffle in the plaza')).not.toBeInTheDocument();
    rerender(
      <StorylinesRail world={W} history={rivalryHistory()} selectedId="dyad:a1~a2" onSelect={() => {}} />,
    );
    // Newest-first, verbatim from the log.
    expect(screen.getByText('a scuffle in the plaza')).toBeInTheDocument();
    expect(screen.getByText('Ada insults Vesper II')).toBeInTheDocument();
  });

  it('offers a CLEAR affordance when a thread is selected', () => {
    const onSelect = vi.fn();
    render(
      <StorylinesRail world={W} history={rivalryHistory()} selectedId="dyad:a1~a2" onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByTitle('Clear the storyline filter'));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});
