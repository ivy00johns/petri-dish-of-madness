/**
 * Wave E selectors (contracts/wave-e.md B6 items 4/7):
 *   • socialGraph folds relationship_changed — payload.to_type/trust are the
 *     ABSOLUTE post-transition state (set, never accumulated);
 *   • the EM-141 agent-endpoint filter still drops non-agent endpoints;
 *   • factionMembership folds faction_formed/joined/left/dissolved at a tick,
 *     and socialGraph nodes carry factionId/factionName.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { socialGraph, factionMembership } from './selectors';
import { agent, ev, resetSeq } from '../test-utils/fixtures';

const AGENTS = [
  agent({ id: 'agent_ada' }),
  agent({ id: 'agent_bram' }),
  agent({ id: 'agent_cleo' }),
];

beforeEach(() => resetSeq());

describe('socialGraph — relationship_changed fold (EM-113/B6)', () => {
  it('sets the edge type and ABSOLUTE trust from the payload', () => {
    const events = [
      ev({
        kind: 'relationship_changed',
        tick: 5,
        actor_id: 'agent_ada',
        target_id: 'agent_bram',
        text: 'Ada and Bram are now friends',
        payload: { from_type: 'neutral', to_type: 'friend', trust: 30, since_tick: 5 },
      }),
    ];
    const g = socialGraph(events, AGENTS, 10);
    expect(g.edges).toHaveLength(1);
    expect(g.edges[0]).toMatchObject({ type: 'friend', trust: 30 });
  });

  it('a later transition overwrites — trust is never accumulated', () => {
    const events = [
      ev({
        kind: 'relationship_changed', tick: 5,
        actor_id: 'agent_ada', target_id: 'agent_bram',
        payload: { from_type: 'neutral', to_type: 'friend', trust: 30, since_tick: 5 },
      }),
      ev({
        kind: 'relationship_changed', tick: 9,
        actor_id: 'agent_ada', target_id: 'agent_bram',
        payload: { from_type: 'friend', to_type: 'partner', trust: 45, since_tick: 9 },
      }),
    ];
    const g = socialGraph(events, AGENTS, 10);
    expect(g.edges).toHaveLength(1);
    expect(g.edges[0]).toMatchObject({ type: 'partner', trust: 45 });
  });

  it('respects the scrub tick (a transition after atTick is invisible)', () => {
    const events = [
      ev({
        kind: 'relationship_changed', tick: 20,
        actor_id: 'agent_ada', target_id: 'agent_bram',
        payload: { from_type: 'rival', to_type: 'feud', trust: -44, since_tick: 20 },
      }),
    ];
    const g = socialGraph(events, AGENTS, 10);
    expect(g.edges).toHaveLength(0);
  });

  it('EM-141: drops relationship_changed rows with a non-agent endpoint', () => {
    const events = [
      ev({
        kind: 'relationship_changed', tick: 3,
        actor_id: 'agent_ada', target_id: 'bld_5eab1c3b',
        payload: { from_type: 'neutral', to_type: 'feud', trust: -50, since_tick: 3 },
      }),
      ev({
        kind: 'conflict', tick: 5, actor_id: 'agent_ada', target_id: 'bld_5eab1c3b',
      }),
    ];
    const g = socialGraph(events, AGENTS, 10);
    expect(g.edges).toHaveLength(0);
  });

  it('a malformed payload falls back instead of crashing (type kept, trust kept)', () => {
    const events = [
      ev({
        kind: 'relationship_changed', tick: 2,
        actor_id: 'agent_ada', target_id: 'agent_bram',
        payload: {},
      }),
    ];
    const g = socialGraph(events, AGENTS, 10);
    expect(g.edges).toHaveLength(1);
    expect(g.edges[0]).toMatchObject({ type: 'neutral', trust: 0 });
  });
});

describe('factionMembership — the faction_* event fold (EM-120/B6)', () => {
  const FORMED = () => ev({
    kind: 'faction_formed', tick: 10, actor_id: 'agent_ada',
    payload: {
      faction_id: 'fct_aa11bb22', name: "Ada's circle",
      members: ['agent_ada', 'agent_bram', 'agent_cleo'],
    },
  });

  it('faction_formed maps every member to the faction', () => {
    const m = factionMembership([FORMED()], 20);
    expect(m.get('agent_ada')).toEqual({ id: 'fct_aa11bb22', name: "Ada's circle" });
    expect(m.get('agent_bram')).toEqual({ id: 'fct_aa11bb22', name: "Ada's circle" });
    expect(m.get('agent_cleo')).toEqual({ id: 'fct_aa11bb22', name: "Ada's circle" });
  });

  it('faction_joined adds the actor; faction_left removes them', () => {
    const events = [
      FORMED(),
      ev({
        kind: 'faction_joined', tick: 12, actor_id: 'agent_dot',
        payload: { faction_id: 'fct_aa11bb22', name: "Ada's circle" },
      }),
      ev({
        kind: 'faction_left', tick: 14, actor_id: 'agent_bram',
        payload: { faction_id: 'fct_aa11bb22', name: "Ada's circle" },
      }),
    ];
    const m = factionMembership(events, 20);
    expect(m.get('agent_dot')?.id).toBe('fct_aa11bb22');
    expect(m.has('agent_bram')).toBe(false);
    expect(m.get('agent_ada')?.id).toBe('fct_aa11bb22');
  });

  it('faction_dissolved clears every member of that faction', () => {
    const events = [
      FORMED(),
      ev({
        kind: 'faction_dissolved', tick: 16, actor_id: 'agent_ada',
        payload: {
          faction_id: 'fct_aa11bb22', name: "Ada's circle",
          members: ['agent_ada', 'agent_bram', 'agent_cleo'],
        },
      }),
    ];
    expect(factionMembership(events, 20).size).toBe(0);
  });

  it('is scrub-consistent: before the formed tick there is no membership', () => {
    expect(factionMembership([FORMED()], 9).size).toBe(0);
  });

  it('socialGraph nodes carry factionId/factionName at the scrub tick', () => {
    const g = socialGraph([FORMED()], AGENTS, 20);
    const ada = g.nodes.find((n) => n.id === 'agent_ada');
    expect(ada).toMatchObject({ factionId: 'fct_aa11bb22', factionName: "Ada's circle" });
    const rewound = socialGraph([FORMED()], AGENTS, 5);
    expect(rewound.nodes.find((n) => n.id === 'agent_ada')).toMatchObject({ factionId: null });
  });
});
