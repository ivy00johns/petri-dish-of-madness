/**
 * EM-286 — Traffic memo keys on graph CONTENT, not identity (offline review
 * 2026-07-01).
 *
 * Snapshot polling swaps world.city_graph by reference every world_state
 * message, so the deterministic-fleet useMemo — with the raw graph object in its
 * deps — missed on 100% of updates and re-ran computeTraffic every poll. The fix
 * keys the memo on trafficGraphSig(graph), a CONTENT signature. computeTraffic
 * reads the graph ONLY through pedestrianStreetIds, whose inputs are the node
 * count, the (sorted) edge set, the city car_policy, and per-edge car_policy
 * overrides — so the signature must fold exactly those, and nothing that merely
 * changes object identity. This mirrors the sibling roadGraphSig pins (RoadMesh).
 */
import { describe, expect, it } from 'vitest';
import { trafficGraphSig } from './Traffic';
import type { CityGraph } from '../../types';

type EdgePolicy = 'inherit' | 'cars' | 'pedestrian' | 'mixed';

function graphOf(
  nodes: Array<[string, number, number]>,
  edges: Array<[string, string, string, EdgePolicy?]>,
  car_policy: CityGraph['car_policy'] = 'cars',
): CityGraph {
  return {
    version: 1,
    seed: 1337,
    car_policy,
    nodes: nodes.map(([id, x, z]) => ({ id, x, z, kind: 'junction' as const })),
    edges: edges.map(([id, a, b, cp]) => ({
      id,
      a,
      b,
      road_class: 'street' as const,
      car_policy: cp ?? 'inherit',
    })),
  };
}

const BASE = graphOf(
  [['a', 0, 0], ['b', 10, 0], ['c', 5, 9]],
  [['e1', 'a', 'b'], ['e2', 'b', 'c']],
);

describe('trafficGraphSig — content key for the deterministic fleet (EM-286)', () => {
  it('fresh graph objects with identical content produce the SAME sig (memo hits across polls)', () => {
    const poll1 = graphOf([['a', 0, 0], ['b', 10, 0], ['c', 5, 9]], [['e1', 'a', 'b'], ['e2', 'b', 'c']]);
    const poll2 = graphOf([['a', 0, 0], ['b', 10, 0], ['c', 5, 9]], [['e1', 'a', 'b'], ['e2', 'b', 'c']]);
    expect(poll1).not.toBe(poll2); // distinct references, as snapshot polling produces each tick
    expect(trafficGraphSig(poll2)).toBe(trafficGraphSig(poll1));
  });

  it('edge ORDER never churns the sig', () => {
    const reordered = graphOf([['a', 0, 0], ['b', 10, 0], ['c', 5, 9]], [['e2', 'b', 'c'], ['e1', 'a', 'b']]);
    expect(trafficGraphSig(reordered)).toBe(trafficGraphSig(BASE));
  });

  it('an equal-count edge SET change flips the sig (demolish + build within one poll)', () => {
    const after = graphOf([['a', 0, 0], ['b', 10, 0], ['c', 5, 9]], [['e1', 'a', 'b'], ['e3', 'c', 'a']]);
    expect(trafficGraphSig(after)).not.toBe(trafficGraphSig(BASE));
  });

  it('the city car_policy participates (the headline car ban re-computes the fleet)', () => {
    const ped = graphOf([['a', 0, 0], ['b', 10, 0], ['c', 5, 9]], [['e1', 'a', 'b'], ['e2', 'b', 'c']], 'pedestrian');
    expect(trafficGraphSig(ped)).not.toBe(trafficGraphSig(BASE));
  });

  it('a per-edge car_policy override flips the sig at CONSTANT edge set (set_car_policy on one street)', () => {
    const oneBanned = graphOf(
      [['a', 0, 0], ['b', 10, 0], ['c', 5, 9]],
      [['e1', 'a', 'b', 'pedestrian'], ['e2', 'b', 'c']],
    );
    expect(trafficGraphSig(oneBanned)).not.toBe(trafficGraphSig(BASE));
  });

  it('an absent graph is the stable empty sig', () => {
    expect(trafficGraphSig(null)).toBe('');
    expect(trafficGraphSig(undefined)).toBe('');
  });
});
