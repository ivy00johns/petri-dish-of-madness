/**
 * TwinLens (EM-310 / Chimera Twins) — the twin-lens surface: pairs a linked
 * same-persona/different-model pair into a dual-strand thread + auto-pins the
 * first divergence-point card. Pure helpers (pairing, answer stream, first
 * divergence) are unit-tested alongside the render contract:
 *   - NO linked pair ⇒ renders nothing (golden-safe zero chrome).
 *   - A linked pair ⇒ the divergence card quotes both twins with model chips.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import {
  TwinLens,
  findTwinPair,
  twinActions,
  firstDivergence,
} from './TwinLens';
import { agent, ev, resetSeq, world } from '../../test-utils/fixtures';
import type { Agent } from '../../types';

function twinA(): Agent {
  return agent({
    id: 'vesper_a', name: 'Vesper', profile: 'gemini-flash',
    profile_color: '#4f8cff', twin: { group: 'Vesper', of: 'vesper_b', model: 'gemini-flash' },
  });
}
function twinB(): Agent {
  return agent({
    id: 'vesper_b', name: 'Vesper II', profile: 'groq-llama',
    profile_color: '#c8ff00', twin: { group: 'Vesper', of: 'vesper_a', model: 'groq-llama' },
  });
}

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the panel persists its collapse preference
});

describe('findTwinPair (pure)', () => {
  it('pairs two mutually-linked twins', () => {
    const pair = findTwinPair([twinA(), twinB(), agent({ id: 'solo' })]);
    expect(pair).not.toBeNull();
    expect(pair!.group).toBe('Vesper');
    expect(new Set([pair!.a.id, pair!.b.id])).toEqual(new Set(['vesper_a', 'vesper_b']));
  });

  it('ignores a one-sided / dangling link (peer must point back)', () => {
    const a = agent({ id: 'a', twin: { group: 'X', of: 'b', model: 'm' } });
    const b = agent({ id: 'b' }); // no twin back-pointer
    expect(findTwinPair([a, b])).toBeNull();
  });

  it('returns null when no agent carries a twin link', () => {
    expect(findTwinPair([agent({ id: 'x' }), agent({ id: 'y' })])).toBeNull();
    expect(findTwinPair(undefined)).toBeNull();
  });
});

describe('twinActions (pure)', () => {
  it('extracts an agents ordered answer stream (action verbs + speech)', () => {
    const history = [
      ev({ kind: 'agent_action', tick: 2, seq: 5, actor_id: 'vesper_a', text: 'takes the trade', payload: { action: 'trade' } }),
      ev({ kind: 'agent_speech', tick: 1, seq: 1, actor_id: 'vesper_a', text: 'hello' }),
      ev({ kind: 'agent_action', tick: 1, seq: 2, actor_id: 'other', text: 'noise', payload: { action: 'work' } }),
    ];
    const stream = twinActions(history, 'vesper_a');
    expect(stream.map((s) => s.verb)).toEqual(['say', 'trade']); // ordered by (tick, seq)
  });
});

describe('firstDivergence (pure)', () => {
  it('finds the earliest index where the answer verbs differ', () => {
    const a = [
      { tick: 1, seq: 1, verb: 'say', text: 'hi' },
      { tick: 2, seq: 2, verb: 'trade', text: 'took it' },
    ];
    const b = [
      { tick: 1, seq: 3, verb: 'say', text: 'hi' },
      { tick: 2, seq: 4, verb: 'report_crime', text: 'told the constable' },
    ];
    const d = firstDivergence(a, b);
    expect(d).not.toBeNull();
    expect(d!.index).toBe(1);
    expect(d!.a.verb).toBe('trade');
    expect(d!.b.verb).toBe('report_crime');
  });

  it('returns null while the streams stay in lockstep', () => {
    const a = [{ tick: 1, seq: 1, verb: 'say', text: 'x' }];
    const b = [{ tick: 1, seq: 2, verb: 'say', text: 'y' }];
    expect(firstDivergence(a, b)).toBeNull();
  });
});

describe('TwinLens (render)', () => {
  it('renders nothing when there is no linked twin pair', () => {
    const { container } = render(
      <TwinLens world={world({ agents: [agent({ id: 'solo' })] })} history={[]} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('pins a divergence card quoting both twins with model chips', () => {
    const history = [
      ev({ kind: 'agent_action', tick: 5, seq: 1, actor_id: 'vesper_a', text: 'takes the shady trade', payload: { action: 'trade' } }),
      ev({ kind: 'agent_action', tick: 5, seq: 2, actor_id: 'vesper_b', text: 'reports it to the constable', payload: { action: 'report_crime' } }),
    ];
    render(<TwinLens world={world({ agents: [twinA(), twinB()] })} history={history} />);

    // The auto-pinned divergence card is present.
    expect(screen.getByLabelText('Divergence point')).toBeTruthy();
    expect(screen.getByText(/divergence point/i)).toBeTruthy();
    // Both twins are quoted with their model chips (name + profile).
    expect(screen.getAllByTitle('Vesper — gemini-flash').length).toBeGreaterThan(0);
    expect(screen.getAllByTitle('Vesper II — groq-llama').length).toBeGreaterThan(0);
    // The diverging answers are quoted (in the card AND the strand row below).
    expect(screen.getAllByText(/takes the shady trade/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/reports it to the constable/).length).toBeGreaterThan(0);
  });

  it('shows the strands but no divergence card while twins stay in lockstep', () => {
    const history = [
      ev({ kind: 'agent_action', tick: 1, seq: 1, actor_id: 'vesper_a', text: 'works', payload: { action: 'work' } }),
      ev({ kind: 'agent_action', tick: 1, seq: 2, actor_id: 'vesper_b', text: 'works', payload: { action: 'work' } }),
    ];
    render(<TwinLens world={world({ agents: [twinA(), twinB()] })} history={history} />);
    expect(screen.queryByLabelText('Divergence point')).toBeNull();
    // The lens itself still renders (the twin header).
    expect(screen.getByText(/TWIN · Vesper/)).toBeTruthy();
  });
});
