/**
 * extinction lib (EM-043 / EM-071) — belt-and-suspenders detection
 * (world_extinct event OR zero-living fallback) + the end-of-run rollup.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { computeExtinction, computeRunSummary } from './extinction';
import { agent, ev, resetSeq, world } from '../test-utils/fixtures';

beforeEach(resetSeq);

describe('computeExtinction', () => {
  it('prefers the world_extinct event payload (tick + auto_paused)', () => {
    const w = world({ agents: [agent({ id: 'a1', alive: false })], running: true });
    const events = [
      ev({ kind: 'world_extinct', tick: 40, payload: { tick: 42, last_agent_id: 'a1', auto_paused: true } }),
    ];
    expect(computeExtinction(w, events)).toEqual({ extinct: true, tick: 42, autoPaused: true });
  });

  it('falls back to zero-living agents in a populated world (no event needed)', () => {
    const w = world({
      agents: [agent({ id: 'a1', alive: false }), agent({ id: 'a2', alive: false })],
      running: false,
      tick: 99,
    });
    const events = [
      ev({ kind: 'agent_died', tick: 10, actor_id: 'a1' }),
      ev({ kind: 'agent_died', tick: 25, actor_id: 'a2' }),
    ];
    // tick = the LAST death; autoPaused because the world is not running.
    expect(computeExtinction(w, events)).toEqual({ extinct: true, tick: 25, autoPaused: true });
  });

  it('returns null while anyone is alive and no event fired', () => {
    const w = world({ agents: [agent({ id: 'a1' }), agent({ id: 'a2', alive: false })] });
    expect(computeExtinction(w, [])).toBeNull();
  });

  it('returns null for an EMPTY world (no agents is not extinction)', () => {
    expect(computeExtinction(world(), [])).toBeNull();
    expect(computeExtinction(null, [])).toBeNull();
  });
});

describe('computeRunSummary', () => {
  it('lists deaths in order, counts rules/crimes, and finds the top credit holder', () => {
    const w = world({
      agents: [
        agent({ id: 'a1', name: 'Ada', credits: 30, alive: false }),
        agent({ id: 'a2', name: 'Bo', credits: 120, alive: false }),
        agent({ id: 'a3', name: 'Cy', credits: 5, alive: false }),
      ],
    });
    const events = [
      // Deliberately out of order: the summary must sort by tick, then seq.
      ev({ kind: 'agent_died', tick: 20, actor_id: 'a3', seq: 110 }),
      ev({ kind: 'agent_died', tick: 5, actor_id: 'a1', seq: 111 }),
      ev({ kind: 'agent_died', tick: 20, actor_id: 'a2', seq: 109 }),
      ev({ kind: 'rule_passed', tick: 2 }),
      ev({ kind: 'rule_passed', tick: 8 }),
      ev({ kind: 'rule_rejected', tick: 9 }),
      ev({ kind: 'conflict', tick: 3, actor_id: 'a1', target_id: 'a2' }),
    ];
    const summary = computeRunSummary(w, events, 20);
    expect(summary.ticksSurvived).toBe(20);
    expect(summary.deaths).toEqual([
      { name: 'Ada', tick: 5 },
      { name: 'Bo', tick: 20 }, // seq 109 < 110 at the same tick
      { name: 'Cy', tick: 20 },
    ]);
    expect(summary.rulesPassed).toBe(2);
    expect(summary.rulesRejected).toBe(1);
    expect(summary.crimes).toBe(1);
    expect(summary.topCreditHolder).toEqual({ name: 'Bo', credits: 120 });
  });

  it('degrades gracefully with no world and no events', () => {
    const summary = computeRunSummary(null, [], 0);
    expect(summary.deaths).toEqual([]);
    expect(summary.topCreditHolder).toBeNull();
  });
});
