/**
 * replayStateAt (EM-043) — the selector where two audited bugs lived:
 *
 *   • audit C4: the fold boundary was inclusive-left, double-applying events
 *     at the snapshot tick (a snapshot at S is the state AFTER tick-S events,
 *     so the fold must be STRICT-LEFT: base.tick < e.tick <= T).
 *   • W9-QA-1: agent_moved destinations are emitted as payload.place; reading
 *     only to/location/target_id left every scrubbed position stale.
 *   • audit C7: scrubbed replay showed LIVE building status; building state at
 *     T must be a pure event fold (project_* / structure_state_changed).
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { replayStateAt, nearestSnapshot } from './selectors';
import type { ReplaySnapshot } from './selectors';
import { agent, building, ev, resetSeq, PLACES } from '../test-utils/fixtures';

const xy = (id: string) => PLACES.find((p) => p.id === id)!;
const agentIn = (frameAgents: ReturnType<typeof replayStateAt>['agents'], id: string) =>
  frameAgents.find((a) => a.id === id)!;

beforeEach(resetSeq);

describe('replayStateAt — strict-left fold boundary (audit C4)', () => {
  const agents = [agent({ id: 'a1', location: 'plaza' })];
  const snap5: ReplaySnapshot = {
    tick: 5,
    agents: [{ id: 'a1', location: 'plaza' }],
  };

  it('EXCLUDES an event AT the snapshot tick (already baked into the snapshot)', () => {
    // The snapshot at tick 5 is the state AFTER tick-5 events: a1 is at plaza
    // *because* the tick-5 move already happened in some pre-snapshot place
    // (here it would wrongly drag a1 to the forest if re-applied).
    const events = [ev({ kind: 'agent_moved', tick: 5, actor_id: 'a1', payload: { place: 'forest' } })];
    const frame = replayStateAt(events, [snap5], 5, agents, PLACES);
    expect(agentIn(frame.agents, 'a1')).toMatchObject({ x: xy('plaza').x, y: xy('plaza').y });
  });

  it('still excludes the snapshot-tick event when scrubbing past it', () => {
    const events = [ev({ kind: 'agent_moved', tick: 5, actor_id: 'a1', payload: { place: 'forest' } })];
    const frame = replayStateAt(events, [snap5], 7, agents, PLACES);
    expect(agentIn(frame.agents, 'a1')).toMatchObject({ x: xy('plaza').x, y: xy('plaza').y });
  });

  it('INCLUDES events at base.tick + 1', () => {
    const events = [ev({ kind: 'agent_moved', tick: 6, actor_id: 'a1', payload: { place: 'home' } })];
    const frame = replayStateAt(events, [snap5], 6, agents, PLACES);
    expect(agentIn(frame.agents, 'a1')).toMatchObject({ x: xy('home').x, y: xy('home').y });
  });

  it('with NO snapshot the base is -1, so tick-0 events apply', () => {
    const events = [ev({ kind: 'agent_moved', tick: 0, actor_id: 'a1', payload: { place: 'forest' } })];
    const frame = replayStateAt(events, [], 0, agents, PLACES);
    expect(agentIn(frame.agents, 'a1')).toMatchObject({ x: xy('forest').x, y: xy('forest').y });
  });
});

describe('replayStateAt — agent_moved destination chain (W9-QA-1)', () => {
  const agents = [agent({ id: 'a1', location: 'plaza' })];

  it('reads payload.place FIRST, even when payload.to disagrees', () => {
    const events = [
      ev({ kind: 'agent_moved', tick: 1, actor_id: 'a1', payload: { place: 'forest', to: 'plaza' } }),
    ];
    const frame = replayStateAt(events, [], 1, agents, PLACES);
    expect(agentIn(frame.agents, 'a1')).toMatchObject({ x: xy('forest').x, y: xy('forest').y });
  });

  it('falls back through to → location → target_id', () => {
    const agentsHere = [agent({ id: 'a1', location: 'plaza' })];
    const cases: Array<{ event: ReturnType<typeof ev>; dest: string }> = [
      { event: ev({ kind: 'agent_moved', tick: 1, actor_id: 'a1', payload: { to: 'home' } }), dest: 'home' },
      { event: ev({ kind: 'agent_moved', tick: 1, actor_id: 'a1', payload: { location: 'forest' } }), dest: 'forest' },
      { event: ev({ kind: 'agent_moved', tick: 1, actor_id: 'a1', target_id: 'home' }), dest: 'home' },
    ];
    for (const { event, dest } of cases) {
      const frame = replayStateAt([event], [], 1, agentsHere, PLACES);
      expect(agentIn(frame.agents, 'a1')).toMatchObject({ x: xy(dest).x, y: xy(dest).y });
    }
  });

  it('ignores destinations that are not known places', () => {
    const events = [ev({ kind: 'agent_moved', tick: 1, actor_id: 'a1', payload: { place: 'narnia' } })];
    const frame = replayStateAt(events, [], 1, agents, PLACES);
    expect(agentIn(frame.agents, 'a1')).toMatchObject({ x: xy('plaza').x, y: xy('plaza').y });
  });
});

describe('replayStateAt — deaths fold', () => {
  const agents = [agent({ id: 'a1' }), agent({ id: 'a2' })];

  it('an agent is alive before its death tick and dead from it onward', () => {
    const events = [ev({ kind: 'agent_died', tick: 3, actor_id: 'a1' })];
    expect(agentIn(replayStateAt(events, [], 2, agents, PLACES).agents, 'a1').alive).toBe(true);
    expect(agentIn(replayStateAt(events, [], 3, agents, PLACES).agents, 'a1').alive).toBe(false);
    expect(agentIn(replayStateAt(events, [], 3, agents, PLACES).agents, 'a2').alive).toBe(true);
  });
});

describe('replayStateAt — time-projected building state (audit C7)', () => {
  const agents = [agent({ id: 'a1' })];
  const lifecycle = () => [
    ev({
      kind: 'project_proposed',
      tick: 2,
      payload: { building_id: 'b1', name: 'Garden', kind: 'garden', location: 'plaza' },
    }),
    ev({
      kind: 'structure_state_changed',
      tick: 4,
      payload: { building_id: 'b1', from: 'planned', to: 'under_construction' },
    }),
    ev({ kind: 'project_built', tick: 5, payload: { building_id: 'b1', progress: 40 } }),
    ev({ kind: 'building_operational', tick: 6, payload: { building_id: 'b1' } }),
  ];

  it('project_proposed CREATES the building (absent the tick before)', () => {
    const events = lifecycle();
    expect(replayStateAt(events, [], 1, agents, PLACES).buildings).toHaveLength(0);
    const at2 = replayStateAt(events, [], 2, agents, PLACES).buildings;
    expect(at2).toHaveLength(1);
    expect(at2[0]).toMatchObject({ id: 'b1', name: 'Garden', status: 'planned', progress: 0 });
  });

  it('structure_state_changed / project_built / building_operational transition it', () => {
    const events = lifecycle();
    expect(replayStateAt(events, [], 4, agents, PLACES).buildings[0]).toMatchObject({
      status: 'under_construction',
      progress: 0,
    });
    expect(replayStateAt(events, [], 5, agents, PLACES).buildings[0]).toMatchObject({
      status: 'under_construction',
      progress: 40,
    });
    expect(replayStateAt(events, [], 6, agents, PLACES).buildings[0]).toMatchObject({
      status: 'operational',
      progress: 100,
    });
  });

  it('the LIVE roster never overrides folded status — only fills metadata', () => {
    const events = lifecycle();
    const live = [building({ id: 'b1', name: 'Community Garden', kind: 'garden', status: 'operational', progress: 100 })];
    const at4 = replayStateAt(events, [], 4, agents, PLACES, live).buildings[0];
    // Status stays the tick-4 projection, not the live 'operational'.
    expect(at4.status).toBe('under_construction');
    // Name was already set by project_proposed, so the live name must not win.
    expect(at4.name).toBe('Garden');
  });

  it('a live building born AFTER the scrub tick is dropped from the frame', () => {
    const events = [
      ev({ kind: 'project_proposed', tick: 8, payload: { building_id: 'b2', name: 'Library' } }),
    ];
    const live = [building({ id: 'b2', name: 'Library' })];
    const frame = replayStateAt(events, [], 3, agents, PLACES, live);
    expect(frame.buildings.find((b) => b.id === 'b2')).toBeUndefined();
  });

  it('a pre-window live building is backfilled by REWINDING through `from`', () => {
    // b3 has no events <= T; its earliest later transition says it was
    // under_construction BEFORE that change — so that's its state at T.
    const events = [
      ev({
        kind: 'structure_state_changed',
        tick: 9,
        payload: { building_id: 'b3', from: 'under_construction', to: 'operational' },
      }),
    ];
    const live = [building({ id: 'b3', status: 'operational', progress: 100 })];
    const frame = replayStateAt(events, [], 3, agents, PLACES, live);
    expect(frame.buildings.find((b) => b.id === 'b3')).toMatchObject({ status: 'under_construction' });
  });

  it('snapshot buildings seed the base state', () => {
    const snap: ReplaySnapshot = {
      tick: 5,
      buildings: [{ id: 'b1', name: 'Garden', location: 'plaza', status: 'damaged', progress: 60 }],
    };
    const frame = replayStateAt([], [snap], 5, agents, PLACES);
    expect(frame.buildings[0]).toMatchObject({ id: 'b1', status: 'damaged', progress: 60 });
  });
});

describe('nearestSnapshot', () => {
  it('returns the closest snapshot at tick <= T, or null', () => {
    const snaps: ReplaySnapshot[] = [{ tick: 0 }, { tick: 10 }, { tick: 20 }];
    expect(nearestSnapshot(snaps, 15)?.tick).toBe(10);
    expect(nearestSnapshot(snaps, 20)?.tick).toBe(20);
    expect(nearestSnapshot([{ tick: 10 }], 5)).toBeNull();
  });
});
