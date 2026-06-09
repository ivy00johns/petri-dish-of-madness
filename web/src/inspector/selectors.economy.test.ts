/**
 * agentEconomyAt (EM-043 / EM-075) — scrubbed energy/credits re-projection.
 * Anchor = latest turn_start sample; the agent's OWN action_resolved
 * state_deltas fold on top. No sample → absent (caller shows "~" live value).
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { agentEconomyAt } from './selectors';
import { ev, resetSeq } from '../test-utils/fixtures';

beforeEach(resetSeq);

describe('agentEconomyAt', () => {
  it('folds a turn_start sample plus own state_deltas (90/10 + {-5,+2} = 85/12)', () => {
    const events = [
      ev({ kind: 'turn_start', tick: 1, actor_id: 'a1', payload: { energy: 90, credits: 10 } }),
      ev({
        kind: 'action_resolved',
        tick: 1,
        actor_id: 'a1',
        payload: { state_deltas: { energy: -5, credits: 2 } },
      }),
    ];
    expect(agentEconomyAt(events).get('a1')).toEqual({ energy: 85, credits: 12, sampled: true });
  });

  it('an agent with NO turn_start sample is absent from the map', () => {
    const events = [
      ev({ kind: 'turn_start', tick: 1, actor_id: 'a1', payload: { energy: 90, credits: 10 } }),
      // a2 resolved an action but never had a sampled turn_start in the window:
      // there is no anchor, so it must stay absent (not a fake 0/0).
      ev({
        kind: 'action_resolved',
        tick: 1,
        actor_id: 'a2',
        payload: { state_deltas: { energy: -10 } },
      }),
    ];
    const out = agentEconomyAt(events);
    expect(out.get('a2')).toBeUndefined();
    expect(out.has('a2')).toBe(false);
  });

  it('a later turn_start re-anchors (the LATEST sample wins)', () => {
    const events = [
      ev({ kind: 'turn_start', tick: 1, actor_id: 'a1', payload: { energy: 90, credits: 10 } }),
      ev({
        kind: 'action_resolved',
        tick: 1,
        actor_id: 'a1',
        payload: { state_deltas: { credits: 5 } },
      }),
      ev({ kind: 'turn_start', tick: 2, actor_id: 'a1', payload: { energy: 70, credits: 40 } }),
    ];
    expect(agentEconomyAt(events).get('a1')).toEqual({ energy: 70, credits: 40, sampled: true });
  });

  it('clamps energy to [0, 100]; credits are unclamped', () => {
    const events = [
      ev({ kind: 'turn_start', tick: 1, actor_id: 'a1', payload: { energy: 5, credits: 1 } }),
      ev({
        kind: 'action_resolved',
        tick: 1,
        actor_id: 'a1',
        payload: { state_deltas: { energy: -50, credits: -10 } },
      }),
    ];
    expect(agentEconomyAt(events).get('a1')).toEqual({ energy: 0, credits: -9, sampled: true });
  });

  it('returns an empty map for an empty window', () => {
    expect(agentEconomyAt([]).size).toBe(0);
  });
});
