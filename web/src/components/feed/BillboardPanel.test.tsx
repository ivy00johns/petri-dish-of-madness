/**
 * BillboardPanel (W11b EM-091c) — the notice board panel: posts come from
 * world.billboard (newest-first), degrade to deriving from billboard_posted
 * history on pre-W11b backends, god posts read in GOD INK with the ✦ GOD
 * chip, and the empty board is a labeled state (§7), never a blank.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { BillboardPanel, billboardPosts } from './BillboardPanel';
import { agent, ev, resetSeq, world } from '../../test-utils/fixtures';
import type { BillboardPost } from '../../types';

function post(partial: Partial<BillboardPost> & { text: string }): BillboardPost {
  return { tick: 0, actor_id: 'a1', actor_type: 'human_agent', ...partial };
}

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the panel persists its collapse preference
});

describe('billboardPosts (pure)', () => {
  it('serves world.billboard newest-first', () => {
    const w = world({
      billboard: [
        post({ text: 'oldest', tick: 1 }),
        post({ text: 'middle', tick: 5 }),
        post({ text: 'newest', tick: 9 }),
      ],
    });
    expect(billboardPosts(w, []).map((p) => p.text)).toEqual([
      'newest',
      'middle',
      'oldest',
    ]);
  });

  it('falls back to deriving from billboard_posted events when state has none', () => {
    const history = [
      ev({
        kind: 'billboard_posted',
        tick: 9,
        actor_id: 'god',
        actor_type: 'god',
        payload: { place: 'plaza', text: 'behave' },
      }),
      ev({
        kind: 'billboard_posted',
        tick: 3,
        actor_id: 'a1',
        text: '📌 Ada pins a note',
        payload: { place: 'plaza', text: 'meet at the mill' },
      }),
      // Not billboard traffic — ignored.
      ev({ kind: 'agent_speech', tick: 4, actor_id: 'a1', text: 'hi' }),
      // No actor_id — dropped defensively.
      ev({ kind: 'billboard_posted', tick: 5, payload: { text: 'ghost post' } }),
    ];
    const posts = billboardPosts(null, history);
    expect(posts).toEqual([
      { tick: 9, actor_id: 'god', actor_type: 'god', text: 'behave' },
      { tick: 3, actor_id: 'a1', actor_type: 'human_agent', text: 'meet at the mill' },
    ]);
    // An empty world.billboard array also falls back (not just null world).
    expect(billboardPosts(world({ billboard: [] }), history)).toHaveLength(2);
  });

  it('mirrors the engine cap when deriving: at most 20 posts', () => {
    const history = Array.from({ length: 30 }, (_, i) =>
      ev({
        kind: 'billboard_posted',
        tick: 30 - i, // newest-first, like the rolling history
        actor_id: 'a1',
        payload: { text: `note ${30 - i}` },
      }),
    );
    expect(billboardPosts(null, history)).toHaveLength(20);
  });
});

describe('BillboardPanel', () => {
  it('labels the empty board (§7) instead of rendering a blank', () => {
    render(<BillboardPanel world={world()} history={[]} />);
    expect(screen.getByText(/The notice board is bare/)).toBeInTheDocument();
    expect(screen.getByText(/post_billboard/)).toBeInTheDocument();
  });

  it('renders posts newest-first with author name + model chip', () => {
    const w = world({
      agents: [agent({ id: 'a1', name: 'Ada', profile: 'model-a', profile_color: '#00ff00' })],
      billboard: [
        post({ text: 'first note', tick: 1, actor_id: 'a1' }),
        post({ text: 'second note', tick: 8, actor_id: 'a1' }),
      ],
    });
    render(<BillboardPanel world={w} history={[]} />);

    const items = screen.getAllByRole('listitem');
    expect(within(items[0]).getByText('“second note”')).toBeInTheDocument();
    expect(within(items[1]).getByText('“first note”')).toBeInTheDocument();
    expect(within(items[0]).getByText('Ada')).toBeInTheDocument();
    expect(within(items[0]).getByText('model-a')).toBeInTheDocument();
    expect(screen.getByText('2 posts')).toBeInTheDocument();
  });

  it('god posts read in god ink with the ✦ god chip, never an agent identity', () => {
    const w = world({
      agents: [agent({ id: 'a1', name: 'Ada' })],
      billboard: [
        post({ text: 'behave yourselves', tick: 9, actor_id: 'god', actor_type: 'god' }),
        post({ text: 'a humble note', tick: 1, actor_id: 'a1' }),
      ],
    });
    render(<BillboardPanel world={w} history={[]} />);

    const items = screen.getAllByRole('listitem');
    const godRow = items[0];
    // The ✦ chip IS the god attribution (no agent name / model chip renders).
    expect(within(godRow).getByText('✦ god')).toBeInTheDocument();
    expect(within(godRow).queryByText('god', { exact: true })).not.toBeInTheDocument();
    // God ink: the violet register, never an agent color.
    expect(within(godRow).getByText('“behave yourselves”')).toHaveStyle({
      color: 'var(--lab-god-bright)',
    });
    // The agent row is NOT god-inked and has no chip.
    expect(within(items[1]).queryByText('✦ god')).not.toBeInTheDocument();
    expect(within(items[1]).getByText('Ada')).toBeInTheDocument();
  });

  it('derives from history when the snapshot predates world.billboard', () => {
    const history = [
      ev({
        kind: 'billboard_posted',
        tick: 2,
        actor_id: 'a1',
        payload: { text: 'from the event log' },
      }),
    ];
    render(<BillboardPanel world={world()} history={history} />);
    expect(screen.getByText('“from the event log”')).toBeInTheDocument();
  });
});
