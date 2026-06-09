/**
 * governanceTimeline + awiSummary (EM-043) — the audit-C6 regression lived
 * here: the AWI dashboard's per-model gov column credited a rule_passed to
 * the model whose agent happened to EMIT the resolution event, not to the
 * PROPOSER's model — numerator and denominator measured different things.
 * Also pins the W9-QA-1 space-exploration chain (payload.place first).
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { governanceTimeline, awiSummary } from './selectors';
import { agent, ev, profile, resetSeq } from '../test-utils/fixtures';

beforeEach(resetSeq);

describe('governanceTimeline', () => {
  it('tracks the proposed → voted → passed lifecycle per rule', () => {
    const events = [
      ev({
        kind: 'rule_proposed',
        tick: 1,
        actor_id: 'a1',
        turn_id: 't1',
        payload: { rule_id: 'r1', effect: 'ubi' },
        text: 'UBI for all',
      }),
      ev({ kind: 'rule_vote', tick: 2, actor_id: 'a2', payload: { rule_id: 'r1', choice: true } }),
      ev({ kind: 'rule_vote', tick: 2, actor_id: 'a3', payload: { rule_id: 'r1', choice: false } }),
      ev({ kind: 'rule_passed', tick: 3, payload: { rule_id: 'r1' } }),
    ];
    const [entry] = governanceTimeline(events);
    expect(entry).toMatchObject({
      ruleId: 'r1',
      effect: 'ubi',
      proposerId: 'a1',
      status: 'active',
      outcome: 'passed',
      createdTick: 1,
      resolvedTick: 3,
    });
    expect(entry.votes).toEqual([
      { voterId: 'a2', choice: true, tick: 2 },
      { voterId: 'a3', choice: false, tick: 2 },
    ]);
  });

  it('tracks a rejection', () => {
    const events = [
      ev({ kind: 'rule_proposed', tick: 1, actor_id: 'a1', payload: { rule_id: 'r2' } }),
      ev({ kind: 'rule_rejected', tick: 2, payload: { rule_id: 'r2' } }),
    ];
    const [entry] = governanceTimeline(events);
    expect(entry).toMatchObject({ ruleId: 'r2', status: 'rejected', outcome: 'rejected' });
  });

  it('attaches downstream consequences linked by turn_id after resolution', () => {
    const events = [
      ev({ kind: 'rule_proposed', tick: 1, actor_id: 'a1', turn_id: 't1', payload: { rule_id: 'r1' } }),
      ev({ kind: 'rule_passed', tick: 2, turn_id: 't1', payload: { rule_id: 'r1' } }),
      ev({ kind: 'economy', tick: 5, turn_id: 't1', text: 'UBI payout' }),
      // Before the causal window (resolved at tick 2) — must NOT attach.
      ev({ kind: 'economy', tick: 1, turn_id: 't1', text: 'too early' }),
    ];
    const [entry] = governanceTimeline(events);
    expect(entry.downstream).toHaveLength(1);
    expect(entry.downstream[0]).toMatchObject({ kind: 'economy', tick: 5, text: 'UBI payout' });
  });
});

describe('awiSummary — per-model governance attribution (audit C6)', () => {
  const profiles = [profile({ name: 'model-a' }), profile({ name: 'model-b' })];
  const agents = [
    agent({ id: 'a1', profile: 'model-a' }),
    agent({ id: 'a2', profile: 'model-b' }),
  ];

  it("credits passed/rejected to the PROPOSER's model, never the resolver's", () => {
    const events = [
      // model-a proposes r1; the resolution event carries model-b's profile
      // (the trap that produced the C6 bug) — model-a must still get the pass.
      ev({ kind: 'rule_proposed', tick: 1, actor_id: 'a1', profile: 'model-a', payload: { rule_id: 'r1' } }),
      ev({ kind: 'rule_passed', tick: 2, profile: 'model-b', payload: { rule_id: 'r1' } }),
      // model-a proposes r2, rejected (no profile on the resolution).
      ev({ kind: 'rule_proposed', tick: 3, actor_id: 'a1', profile: 'model-a', payload: { rule_id: 'r2' } }),
      ev({ kind: 'rule_rejected', tick: 4, payload: { rule_id: 'r2' } }),
      // model-b proposes r3; resolution mislabeled with model-a's profile.
      ev({ kind: 'rule_proposed', tick: 5, actor_id: 'a2', profile: 'model-b', payload: { rule_id: 'r3' } }),
      ev({ kind: 'rule_passed', tick: 6, profile: 'model-a', payload: { rule_id: 'r3' } }),
    ];
    const summary = awiSummary(events, {}, agents, profiles);

    // model-a: 2 proposals, 1 passed, 1 rejected → 1/(1+1) pass rate.
    expect(summary.byModel['model-a']).toMatchObject({ proposals: 2, passed: 1, rejected: 1 });
    // model-b: 1 proposal, 1 passed, 0 rejected → 1/(1+0).
    expect(summary.byModel['model-b']).toMatchObject({ proposals: 1, passed: 1, rejected: 0 });
    // The world-level tallies stay raw counts.
    expect(summary.governance).toMatchObject({ proposed: 3, passed: 2, rejected: 1 });
  });

  it('resolutions WITHOUT a rule_id fall back to the oldest open proposal', () => {
    const events = [
      ev({ kind: 'rule_proposed', tick: 1, actor_id: 'a1', profile: 'model-a', payload: { rule_id: 'r1' } }),
      ev({ kind: 'rule_proposed', tick: 2, actor_id: 'a2', profile: 'model-b', payload: { rule_id: 'r2' } }),
      ev({ kind: 'rule_passed', tick: 3 }), // no rule_id → resolves r1 (model-a)
      ev({ kind: 'rule_rejected', tick: 4 }), // → resolves r2 (model-b)
    ];
    const summary = awiSummary(events, {}, agents, profiles);
    expect(summary.byModel['model-a']).toMatchObject({ passed: 1, rejected: 0 });
    expect(summary.byModel['model-b']).toMatchObject({ passed: 0, rejected: 1 });
  });
});

describe('awiSummary — space exploration via the place-first chain (W9-QA-1)', () => {
  it('counts UNIQUE places per agent, reading payload.place before to/location', () => {
    const events = [
      ev({ kind: 'agent_moved', tick: 1, actor_id: 'a1', payload: { place: 'plaza' } }),
      ev({ kind: 'agent_moved', tick: 2, actor_id: 'a1', payload: { to: 'forest' } }),
      ev({ kind: 'agent_moved', tick: 3, actor_id: 'a1', payload: { location: 'home' } }),
      // place must win over `to` — if `to` were read, a 4th place would appear.
      ev({ kind: 'agent_moved', tick: 4, actor_id: 'a1', payload: { place: 'plaza', to: 'phantom-zone' } }),
      ev({ kind: 'agent_moved', tick: 5, actor_id: 'a2', payload: { place: 'forest' } }),
    ];
    const summary = awiSummary(events, {}, [agent({ id: 'a1' }), agent({ id: 'a2' })]);
    expect(summary.spaceExploration.byAgent).toEqual({ a1: 3, a2: 1 });
  });
});
