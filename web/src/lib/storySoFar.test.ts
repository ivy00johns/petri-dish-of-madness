/**
 * storySoFar digest (W11a EM-094) — the always-on ZERO-LLM "story so far"
 * selector. Pure-logic tests over a synthetic newest-first history + a
 * world_state projection: roster with death ticks, active-rule count + newest
 * rule text, project statuses, the drama heuristic's newest-first precedence,
 * and the narrator_summary channel pickup (contract frontend-inspector.md §9 /
 * event-log.md v1.2.0 note 1).
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { projectReadout, storySoFar } from './storySoFar';
import { agent, building, ev, resetSeq, world } from '../test-utils/fixtures';
import type { Rule, WorldEvent } from '../types';

beforeEach(() => resetSeq());

/** Newest-first, the useSimulation.history order the selector documents. */
function newestFirst(events: WorldEvent[]): WorldEvent[] {
  return [...events].sort((a, b) => b.seq - a.seq);
}

function rule(partial: Partial<Rule> & { id: string }): Rule {
  return {
    effect: 'ubi',
    text: `rule ${partial.id}`,
    proposer_id: 'a1',
    status: 'active',
    votes: {},
    created_tick: 0,
    ...partial,
  };
}

describe('storySoFar — labeled-empty shape', () => {
  it('returns an empty-but-shaped digest with no history and no world', () => {
    const d = storySoFar([], null);
    expect(d.aliveCount).toBe(0);
    expect(d.totalCount).toBe(0);
    expect(d.alive).toEqual([]);
    expect(d.dead).toEqual([]);
    expect(d.activeRuleCount).toBe(0);
    expect(d.newestRuleText).toBeNull();
    expect(d.ruleVoteInProgress).toBe(false);
    expect(d.projects).toEqual([]);
    expect(d.drama).toBeNull();
    expect(d.narratorLatest).toBeNull();
    expect(d.narratorCount).toBe(0);
  });
});

describe('storySoFar — roster + death ticks', () => {
  it('splits alive/dead and recovers death ticks from agent_died events', () => {
    const w = world({
      agents: [
        agent({ id: 'a1', name: 'Ada' }),
        agent({ id: 'a2', name: 'Bram', alive: false }),
        agent({ id: 'a3', name: 'Cleo', alive: false }),
      ],
    });
    const history = newestFirst([
      ev({ kind: 'agent_died', actor_id: 'a3', tick: 12 }),
      ev({ kind: 'agent_died', actor_id: 'a2', tick: 30 }),
    ]);

    const d = storySoFar(history, w);
    expect(d.aliveCount).toBe(1);
    expect(d.totalCount).toBe(3);
    expect(d.alive).toEqual([{ id: 'a1', name: 'Ada' }]);
    // Dead roster reads chronologically by death tick.
    expect(d.dead).toEqual([
      { id: 'a3', name: 'Cleo', deathTick: 12 },
      { id: 'a2', name: 'Bram', deathTick: 30 },
    ]);
  });

  it('labels deaths older than the window with a null tick, sorted last', () => {
    const w = world({
      agents: [
        agent({ id: 'a1', name: 'Ada', alive: false }), // death fell out of window
        agent({ id: 'a2', name: 'Bram', alive: false }),
      ],
    });
    const history = newestFirst([ev({ kind: 'agent_died', actor_id: 'a2', tick: 5 })]);

    const d = storySoFar(history, w);
    expect(d.dead).toEqual([
      { id: 'a2', name: 'Bram', deathTick: 5 },
      { id: 'a1', name: 'Ada', deathTick: null }, // labeled-unknown, never a hole
    ]);
  });
});

describe('storySoFar — rules', () => {
  it('counts active rules and surfaces the newest active rule text', () => {
    const w = world({
      rules: [
        rule({ id: 'r1', created_tick: 2, text: 'no stealing' }),
        rule({ id: 'r2', created_tick: 9, text: 'basic income for all' }),
        rule({ id: 'r3', created_tick: 5, status: 'rejected', text: 'rejected idea' }),
      ],
    });
    const d = storySoFar([], w);
    expect(d.activeRuleCount).toBe(2);
    expect(d.newestRuleText).toBe('basic income for all'); // newest by created_tick
    expect(d.ruleVoteInProgress).toBe(false);
  });

  it('flags a vote in progress while any rule sits proposed', () => {
    const w = world({ rules: [rule({ id: 'r1', status: 'proposed' })] });
    const d = storySoFar([], w);
    expect(d.ruleVoteInProgress).toBe(true);
    expect(d.activeRuleCount).toBe(0);
    expect(d.newestRuleText).toBeNull();
  });
});

describe('storySoFar — projects', () => {
  it('maps buildings into project entries with status and progress', () => {
    const w = world({
      buildings: [
        building({ id: 'b1', name: 'Clocktower', status: 'under_construction', progress: 40 }),
        building({ id: 'b2', name: 'Garden', status: 'operational', progress: 100 }),
      ],
    });
    expect(storySoFar([], w).projects).toEqual([
      { id: 'b1', name: 'Clocktower', status: 'under_construction', progress: 40 },
      { id: 'b2', name: 'Garden', status: 'operational', progress: 100 },
    ]);
  });
});

describe('storySoFar — drama heuristic (newest-first precedence)', () => {
  it('picks the MOST RECENT drama event, not the most severe', () => {
    const history = newestFirst([
      ev({ kind: 'agent_died', actor_id: 'a1', tick: 3, text: 'Ada died' }),
      ev({ kind: 'conflict', actor_id: 'a2', tick: 8, text: 'Bram attacked Cleo' }),
      ev({ kind: 'agent_speech', actor_id: 'a3', tick: 9, text: 'chatter' }), // not drama
    ]);
    const d = storySoFar(history, world());
    expect(d.drama).toEqual({ label: 'CONFLICT', text: 'Bram attacked Cleo', tick: 8 });
  });

  it('labels each drama register and falls back to [kind] without text', () => {
    const cases: Array<[string, string]> = [
      ['world_extinct', 'EXTINCTION'],
      ['agent_starving', 'STARVATION'],
      ['agent_died', 'DEATH'],
      ['rule_proposed', 'RULE VOTE'],
      ['rule_vote', 'RULE VOTE'],
    ];
    for (const [kind, label] of cases) {
      resetSeq();
      const d = storySoFar([ev({ kind, tick: 1 })], world());
      expect(d.drama).toEqual({ label, text: `[${kind}]`, tick: 1 });
    }
  });

  it('reports no drama on a calm history', () => {
    const history = newestFirst([
      ev({ kind: 'agent_speech', tick: 1 }),
      ev({ kind: 'economy', tick: 2 }),
    ]);
    expect(storySoFar(history, world()).drama).toBeNull();
  });
});

describe('storySoFar — narrator channel', () => {
  it('counts narrator_summary events and keeps the newest as latest', () => {
    const older = ev({
      kind: 'narrator_summary', tick: 50, text: 'A quiet stretch.',
      payload: { from_tick: 0, to_tick: 50, profile: 'narrator' },
    });
    const newer = ev({
      kind: 'narrator_summary', tick: 100, text: 'Then everything burned.',
      payload: { from_tick: 50, to_tick: 100, profile: 'narrator' },
    });
    const d = storySoFar(newestFirst([older, newer]), world());
    expect(d.narratorCount).toBe(2);
    expect(d.narratorLatest).toBe(newer);
    // The narrator recap is informational, never the drama chip.
    expect(d.drama).toBeNull();
  });

  it('reports a labeled off-state (zero, null) when no narrator events exist', () => {
    const d = storySoFar(newestFirst([ev({ kind: 'agent_speech', tick: 1 })]), world());
    expect(d.narratorCount).toBe(0);
    expect(d.narratorLatest).toBeNull();
  });
});

describe('projectReadout (EM-139) — bounded digest line', () => {
  const p = (id: string, status: string, progress = 0, name = id) =>
    ({ id, name, status, progress });

  it('names live projects with progress and aggregates the settled tail to counts', () => {
    const line = projectReadout([
      p('b1', 'under_construction', 20, "Bram's Midnight Chatter Revival"),
      p('b2', 'operational', 100, 'Gossip Stage'),
      p('b3', 'operational', 100, 'Phoenix Pavilion'),
      ...Array.from({ length: 47 }, (_, i) => p(`d${i}`, 'destroyed', 100, `Ruin ${i}`)),
      p('a1', 'abandoned', 40, 'Old Fountain'),
    ]);
    expect(line).toBe(
      "Bram's Midnight Chatter Revival 20% building · 2 operational · 1 abandoned · 47 destroyed",
    );
    // The 47 ruins are NEVER enumerated by name.
    expect(line).not.toContain('Ruin');
  });

  it('caps named live projects and counts the overflow', () => {
    const line = projectReadout([
      p('b1', 'planned', 0, 'A'),
      p('b2', 'under_construction', 10, 'B'),
      p('b3', 'under_construction', 60, 'C'),
      p('b4', 'planned', 0, 'D'),
      p('b5', 'under_construction', 90, 'E'),
    ]);
    expect(line).toBe('A 0% planned · B 10% building · C 60% building · +2 more in progress');
  });

  it('stays bounded: 200 mixed projects produce a short line, not a wall', () => {
    const many = Array.from({ length: 200 }, (_, i) =>
      p(`x${i}`, i % 3 === 0 ? 'destroyed' : i % 3 === 1 ? 'operational' : 'damaged', 100, `Name ${i}`),
    );
    const line = projectReadout(many);
    expect(line.length).toBeLessThan(120);
    expect(line).toContain('operational');
    expect(line).toContain('destroyed');
    expect(line).toContain('damaged');
  });

  it('surfaces unknown future statuses as counts instead of dropping them', () => {
    expect(projectReadout([p('z', 'haunted', 100, 'Spooky Mill')])).toBe('1 haunted');
  });

  it('returns an empty string for no projects (component shows its labeled empty state)', () => {
    expect(projectReadout([])).toBe('');
  });
});
