/**
 * socialGraph (EM-058) — edge-endpoint integrity (EM-141).
 *
 * Conflict/economy events can carry a BUILDING as target_id (arson, project
 * funding). Folding those into the relationship web produced edges whose
 * endpoint is not a graph node, and react-force-graph's d3 layout throws
 * "node not found: bld_…" — which killed the whole Inspector panel on
 * building-heavy archived runs (run 189: 43 conflicts + 57 economy events
 * targeting buildings). Edges must only ever connect agent nodes.
 */
import { describe, expect, it } from 'vitest';
import { socialGraph } from './selectors';
import { agent, ev, resetSeq } from '../test-utils/fixtures';

const AGENTS = [agent({ id: 'agent_ada' }), agent({ id: 'agent_bram' })];

function endpointIds(edges: Array<{ source: string; target: string }>): string[] {
  return edges.flatMap((e) => [e.source, e.target]);
}

describe('socialGraph — edges only between agent nodes (EM-141)', () => {
  it('drops conflict edges whose target is a building', () => {
    resetSeq();
    const events = [
      ev({ kind: 'conflict', tick: 5, actor_id: 'agent_ada', target_id: 'bld_5eab1c3b' }),
      ev({ kind: 'conflict', tick: 6, actor_id: 'agent_ada', target_id: 'agent_bram' }),
    ];
    const g = socialGraph(events, AGENTS, 10);
    expect(endpointIds(g.edges)).not.toContain('bld_5eab1c3b');
    // The agent↔agent conflict still lands.
    expect(g.edges).toHaveLength(1);
  });

  it('drops economy (gift) edges whose target is a building', () => {
    resetSeq();
    const events = [
      ev({
        kind: 'economy', tick: 3, actor_id: 'agent_ada', target_id: 'bld_market_stall',
        text: 'Ada gives 5 credits toward the stall', payload: { action: 'give' },
      }),
    ];
    const g = socialGraph(events, AGENTS, 10);
    expect(g.edges).toHaveLength(0);
  });

  it('drops self-edges and unknown-agent endpoints', () => {
    resetSeq();
    const events = [
      ev({ kind: 'conflict', tick: 1, actor_id: 'agent_ada', target_id: 'agent_ada' }),
      ev({ kind: 'relationship', tick: 2, actor_id: 'agent_ghost', target_id: 'agent_bram' }),
    ];
    const g = socialGraph(events, AGENTS, 10);
    expect(g.edges).toHaveLength(0);
  });

  it('ignores seeded relationship-map entries pointing at non-nodes', () => {
    resetSeq();
    const withRel = agent({
      id: 'agent_ada',
      relationships: {
        bld_5eab1c3b: { type: 'rival', trust: -30, interactions: 4 },
        agent_bram: { type: 'ally', trust: 20, interactions: 2 },
      },
    });
    const g = socialGraph([], [withRel, agent({ id: 'agent_bram' })], 10);
    expect(endpointIds(g.edges)).not.toContain('bld_5eab1c3b');
    expect(g.edges).toHaveLength(1);
  });
});
