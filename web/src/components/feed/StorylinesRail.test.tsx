/**
 * StorylinesRail (EM-312) — the feed's drama index. Empty renders NOTHING (a
 * quiet town / flag-off shape stays byte-identical). A promoted rivalry shows
 * its named badge + status chip; clicking it selects the thread and reveals the
 * verbatim "story so far" beats. The scoring itself is pinned in
 * lib/storylines.test.ts — these tests cover the rail's render + selection
 * wiring through the useStorylines hook (the same shape App mounts: the parent
 * owns the scored set, stores only the selected ID, and re-resolves the live
 * Storyline each render).
 */
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { StorylinesRail, useStorylines } from './StorylinesRail';
import { agent, ev, resetSeq, world } from '../../test-utils/fixtures';
import type { Storyline } from '../../lib/storylines';
import type { WorldEvent, WorldState } from '../../types';

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the rail persists its collapse preference
});

const W = world({
  agents: [agent({ id: 'a1', name: 'Ada' }), agent({ id: 'a2', name: 'Vesper II' })],
});

/** The rail as App mounts it: scored via useStorylines, selection by ID. */
function Rail({
  world: w,
  history,
  selectedId,
  onSelect,
}: {
  world: WorldState;
  history: WorldEvent[];
  selectedId: string | null;
  onSelect: (s: Storyline | null) => void;
}) {
  const storylines = useStorylines(history, w);
  return <StorylinesRail storylines={storylines} selectedId={selectedId} onSelect={onSelect} />;
}

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
      <Rail world={W} history={[]} selectedId={null} onSelect={() => {}} />,
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
      <Rail world={W} history={h} selectedId={null} onSelect={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('StorylinesRail — a promoted rivalry', () => {
  it('names the thread with its archetype badge + status', () => {
    render(<Rail world={W} history={rivalryHistory()} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByText('Ada v. Vesper II')).toBeInTheDocument();
    expect(screen.getByText('RIVALRY')).toBeInTheDocument();
    expect(screen.getByText('TENSION')).toBeInTheDocument();
  });

  it('selects the thread on click (parent gets the Storyline)', () => {
    const onSelect = vi.fn();
    render(<Rail world={W} history={rivalryHistory()} selectedId={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText('Ada v. Vesper II'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    const arg = onSelect.mock.calls[0][0];
    expect(arg.id).toBe('dyad:a1~a2');
    expect(arg.principals).toEqual(['a1', 'a2']);
  });

  it('reveals the VERBATIM story-so-far beats only when selected', () => {
    const { rerender } = render(
      <Rail world={W} history={rivalryHistory()} selectedId={null} onSelect={() => {}} />,
    );
    expect(screen.queryByText('a scuffle in the plaza')).not.toBeInTheDocument();
    rerender(
      <Rail world={W} history={rivalryHistory()} selectedId="dyad:a1~a2" onSelect={() => {}} />,
    );
    // Newest-first, verbatim from the log.
    expect(screen.getByText('a scuffle in the plaza')).toBeInTheDocument();
    expect(screen.getByText('Ada insults Vesper II')).toBeInTheDocument();
  });

  it('offers a CLEAR affordance when a thread is selected', () => {
    const onSelect = vi.fn();
    render(
      <Rail world={W} history={rivalryHistory()} selectedId="dyad:a1~a2" onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByTitle('Clear the storyline filter'));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});

describe('StorylinesRail — the selection follows an EVOLVING thread (C17)', () => {
  const W3 = world({
    agents: [
      agent({ id: 'a1', name: 'Ada' }),
      agent({ id: 'a2', name: 'Vesper II' }),
      agent({ id: 'a3', name: 'Bram' }),
    ],
  });

  /** App's exact wiring: only the ID is stored; the live Storyline is
   *  re-resolved from the current scored set each render, and its LIVE
   *  principals feed the thread filter (probed below). */
  function AppLikeHarness({ history }: { history: WorldEvent[] }) {
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const storylines = useStorylines(history, W3);
    const selected = selectedId
      ? storylines.find((s) => s.id === selectedId) ?? null
      : null;
    return (
      <>
        <StorylinesRail
          storylines={storylines}
          selectedId={selectedId}
          onSelect={(s) => setSelectedId(s?.id ?? null)}
        />
        <div data-testid="filter-principals">{selected ? selected.principals.join(',') : ''}</div>
      </>
    );
  }

  it('a selected power grab that recruits a new ally grows the filter principals', () => {
    // Ada consolidates: three recruits of Vesper II promote grab:a1.
    const base = [
      ev({ kind: 'recruited', actor_id: 'a1', target_id: 'a2', tick: 1, text: 'Ada recruits Vesper II' }),
      ev({ kind: 'recruited', actor_id: 'a1', target_id: 'a2', tick: 2, text: 'Ada tightens her grip' }),
      ev({ kind: 'recruited', actor_id: 'a1', target_id: 'a2', tick: 3, text: 'Ada consolidates' }),
    ];
    const { rerender } = render(<AppLikeHarness history={base} />);

    fireEvent.click(screen.getByText("Ada's Power Grab"));
    expect(screen.getByTestId('filter-principals')).toHaveTextContent('a1,a2');

    // The thread persists but EVOLVES: a new ally joins. The click-time object
    // is never cached — the filter's principals must follow the live set.
    rerender(
      <AppLikeHarness
        history={[
          ...base,
          ev({ kind: 'recruited', actor_id: 'a1', target_id: 'a3', tick: 4, text: 'Ada recruits Bram' }),
        ]}
      />,
    );
    expect(screen.getByTestId('filter-principals')).toHaveTextContent('a1,a2,a3');
  });
});
