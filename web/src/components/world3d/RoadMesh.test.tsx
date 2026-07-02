/**
 * RoadMesh smoke tests (EM-247 S5a) — the jsdom render harness mirrors
 * CityScape.test.tsx: react-dom mounts the R3F tags as unknown elements (no
 * reconciler), so we get a structural smoke test (one <instancedMesh> per
 * non-empty bucket) without a GL context. The visual quality (atlas / lane
 * markings / LOD) is the spec's deferred human sign-off, not asserted here.
 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import type { CityGraph } from '../../types';
import { buildRoadMesh } from './roadMeshData';
import { RoadMesh, roadMeshBuckets, roadGraphSig } from './RoadMesh';

afterEach(cleanup);

function graphOf(
  nodes: Array<[string, number, number]>,
  edges: Array<[string, string, string]>,
): CityGraph {
  return {
    version: 1, seed: 1337, car_policy: 'cars',
    nodes: nodes.map(([id, x, z]) => ({ id, x, z, kind: 'junction' as const })),
    edges: edges.map(([id, a, b]) => ({
      id, a, b, road_class: 'street' as const, car_policy: 'inherit' as const,
    })),
  };
}

// A 3-node / 3-edge triangle ⇒ 3 ribbons + 3 intersections ⇒ 2 non-empty buckets.
const TRI = graphOf(
  [['a', 0, 0], ['b', 10, 0], ['c', 5, 9]],
  [['e1', 'a', 'b'], ['e2', 'b', 'c'], ['e3', 'c', 'a']],
);

function renderRoads(graph: CityGraph | null, seed = 1337) {
  // react-dom renders the R3F tags as unknown elements; silence the warnings.
  const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  try {
    return render(<RoadMesh graph={graph} seed={seed} />);
  } finally {
    errSpy.mockRestore();
    warnSpy.mockRestore();
  }
}

describe('RoadMesh (R3F smoke)', () => {
  it('roadMeshBuckets mirrors buildRoadMesh non-empty bucket counts', () => {
    const m = buildRoadMesh(TRI, 1337);
    const buckets = roadMeshBuckets(TRI, 1337);
    const byKey = Object.fromEntries(buckets.map((b) => [b.key, b.count]));
    expect(byKey.ribbons).toBe(m.ribbons.length);
    expect(byKey.intersections).toBe(m.intersections.length);
    expect(byKey.ribbons).toBe(3);
    expect(byKey.intersections).toBe(3);
    // only the non-empty buckets are reported (roundabouts/plazas drop out)
    expect(buckets).toHaveLength(2);
    expect(buckets.every((b) => b.count > 0)).toBe(true);
  });

  it('mounts a 3-edge graph without throwing — one instancedMesh per non-empty bucket', () => {
    const { container } = renderRoads(TRI);
    const meshes = container.querySelectorAll('instancedMesh');
    expect(meshes.length).toBe(roadMeshBuckets(TRI, 1337).length);
    expect(meshes.length).toBe(2);
  });

  it('an absent / edgeless graph mounts to nothing (no throw, no buckets)', () => {
    const { container } = renderRoads(null);
    expect(container.querySelectorAll('instancedMesh').length).toBe(0);
    expect(roadMeshBuckets(null, 1337)).toEqual([]);
  });
});

describe('roadGraphSig (content-keyed rebuild dep — the 4th recurrence of the content-key class)', () => {
  it('equal-count graphs with DIFFERENT edges produce different signatures', () => {
    // demolish+build inside one snapshot poll: node/edge COUNTS are identical
    // but the edge SET changed — a count-only fold renders the mutation stale.
    const before = graphOf(
      [['a', 0, 0], ['b', 10, 0], ['c', 5, 9]],
      [['e:a->b', 'a', 'b'], ['e:b->c', 'b', 'c']],
    );
    const after = graphOf(
      [['a', 0, 0], ['b', 10, 0], ['c', 5, 9]],
      [['e:a->b', 'a', 'b'], ['e:c->a', 'c', 'a']],
    );
    expect(roadGraphSig(after)).not.toBe(roadGraphSig(before));
  });

  it('edge ORDER never churns the sig; identical content (fresh objects) is stable', () => {
    const a = graphOf(
      [['a', 0, 0], ['b', 10, 0]],
      [['e1', 'a', 'b'], ['e2', 'b', 'a']],
    );
    const reordered = graphOf(
      [['a', 0, 0], ['b', 10, 0]],
      [['e2', 'b', 'a'], ['e1', 'a', 'b']],
    );
    expect(roadGraphSig(reordered)).toBe(roadGraphSig(a));
    expect(roadGraphSig(graphOf(
      [['a', 0, 0], ['b', 10, 0]],
      [['e1', 'a', 'b'], ['e2', 'b', 'a']],
    ))).toBe(roadGraphSig(a));
  });

  it('car_policy still participates; an absent graph is the stable empty sig', () => {
    const cars = { ...TRI, car_policy: 'cars' as const };
    const ped = { ...TRI, car_policy: 'pedestrian' as const };
    expect(roadGraphSig(ped)).not.toBe(roadGraphSig(cars));
    expect(roadGraphSig(null)).toBe('');
    expect(roadGraphSig(undefined)).toBe('');
  });
});
