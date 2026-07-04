/**
 * EM-291 — RoadMesh roundabout RingGeometry is disposed, not leaked (offline
 * review 2026-07-01).
 *
 * useRoundaboutBucket builds its RingGeometry imperatively (new THREE.
 * RingGeometry) and hands it to the mesh via `args`, which is OUTSIDE R3F's
 * declarative auto-dispose (that only frees geometries mounted as JSX children).
 * Before the fix every graph rebuild allocated a fresh ring geometry and never
 * disposed the previous one → a GPU geometry leak. These pins assert the
 * previous geometry is disposed on rebuild and on unmount.
 *
 * jsdom render harness mirrors RoadMesh.test.tsx: react-dom mounts the R3F tags
 * as unknown elements (no reconciler), but the component's hooks/effects run, so
 * the dispose lifecycle is observable via a spy on RingGeometry.prototype.dispose.
 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import * as THREE from 'three';
import type { CityGraph } from '../../types';
import { RoadMesh } from './RoadMesh';

afterEach(cleanup);

/** A graph with one roundabout node (kind widened past the S1 'junction'
 *  literal, exactly as the S3 generator emits). car_policy varies the CONTENT
 *  signature so a rerender is a real graph rebuild (new rings ⇒ new geometry). */
function roundaboutGraph(carPolicy: CityGraph['car_policy']): CityGraph {
  return {
    version: 1,
    seed: 1337,
    car_policy: carPolicy,
    nodes: [
      { id: 'r1', x: 0, z: 0, kind: 'roundabout' },
      { id: 'j1', x: 10, z: 0, kind: 'junction' },
    ] as unknown as CityGraph['nodes'],
    edges: [{ id: 'e1', a: 'r1', b: 'j1', road_class: 'street', car_policy: 'inherit' }] as CityGraph['edges'],
  };
}

describe('RoadMesh roundabout geometry disposal (EM-291)', () => {
  it('disposes the previous RingGeometry on graph rebuild and on unmount', () => {
    const disposeSpy = vi.spyOn(THREE.RingGeometry.prototype, 'dispose');
    // react-dom renders R3F tags as unknown elements; silence the DOM warnings.
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      const { rerender, unmount } = render(<RoadMesh graph={roundaboutGraph('cars')} seed={1337} />);
      // The first geometry is live — nothing disposed yet.
      expect(disposeSpy).not.toHaveBeenCalled();

      // A graph rebuild (the car_policy flip changes the content sig) allocates a
      // NEW RingGeometry; the previous one must be disposed, not leaked.
      rerender(<RoadMesh graph={roundaboutGraph('pedestrian')} seed={1337} />);
      expect(disposeSpy).toHaveBeenCalledTimes(1);

      // Unmount disposes the last geometry too.
      unmount();
      expect(disposeSpy).toHaveBeenCalledTimes(2);
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
      disposeSpy.mockRestore();
    }
  });
});
