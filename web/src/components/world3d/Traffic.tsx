/**
 * Traffic.tsx — EM-169 ambient moving vehicles (set dressing).
 *
 * Renders the deterministic car fleet from traffic.ts and animates each car
 * along its street with a clock-driven useFrame sweep. NON-INTERACTIVE (no
 * pointer handlers, like the rest of the city set dressing, EM-157) and
 * reduced-motion-safe: under `prefers-reduced-motion: reduce` the cars render
 * at their phase-0 position and never move.
 *
 * Each car reuses the Car Kit GLB via the same toon-converting <Model> wrapper
 * the buildings use (cached + toonified once per url). The fleet is small
 * (≤ interior-street count) so per-car <Clone> nodes are cheap — no instancing
 * needed at this scale.
 */

import { Suspense, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { Model } from './assets/Model';
import { CITY_MODEL_REGISTRY } from './assets/cityModels';
import {
  TRAFFIC_ENABLED,
  carOffset,
  computeTraffic,
  trafficSpan,
  type TrafficCar as TrafficCarT,
} from './trafficLayout';
import type { CityStreet } from './cityLayout';
import type { CityGraph } from '../../types';

const PREFERS_REDUCED_MOTION =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

interface TrafficProps {
  seed: number;
  streets: readonly CityStreet[];
  // EM-244 (S3a): the road graph carries per-edge + city car policy; a
  // 'pedestrian' street/city loses its cars. Optional/null so the pre-S3 +
  // no-graph paths render the byte-identical fleet.
  graph?: CityGraph | null;
}

/**
 * EM-286: key the deterministic fleet on the graph's CONTENT, not its object
 * identity. Snapshot polling swaps world.city_graph by reference every
 * world_state message (the EM-243/244/247 lesson — 4th recurrence of the
 * content-key class), so an identity dep MISSED on 100% of updates and re-ran
 * computeTraffic every poll. computeTraffic reads the graph ONLY through
 * pedestrianStreetIds, whose inputs are: node count/positions (structure),
 * the sorted edge set, the city car_policy, and per-edge car_policy overrides
 * (a set_car_policy vote flips one street to pedestrian at CONSTANT edge count
 * — bare counts would miss it). This signature folds exactly those. Cheap
 * string join at ≤ a few hundred edges, per poll, never serialized.
 */
export function trafficGraphSig(graph?: CityGraph | null): string {
  if (!graph) return '';
  const overrides = graph.edges
    .filter((e) => e.car_policy && e.car_policy !== 'inherit')
    .map((e) => `${e.id}=${e.car_policy}`)
    .sort()
    .join(',');
  return `${graph.nodes.length}:${graph.edges
    .map((e) => e.id)
    .sort()
    .join(',')}:${graph.car_policy ?? ''}:${overrides}`;
}

/** The whole ambient fleet. */
export function Traffic({ seed, streets, graph }: TrafficProps) {
  const graphSig = trafficGraphSig(graph);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: recompute
  // on graph CONTENT (graphSig), not object identity, to avoid per-poll churn.
  const cars = useMemo(() => computeTraffic(seed, streets, graph), [seed, streets, graphSig]);
  const span = useMemo(() => trafficSpan(streets), [streets]);
  if (!TRAFFIC_ENABLED || cars.length === 0) return null;
  return (
    <>
      {cars.map((car) => (
        <Car key={car.id} car={car} span={span} />
      ))}
    </>
  );
}

function Car({ car, span }: { car: TrafficCarT; span: number }) {
  const ref = useRef<THREE.Group>(null);
  const spec = CITY_MODEL_REGISTRY[car.kind];

  useFrame((state) => {
    if (!ref.current || PREFERS_REDUCED_MOTION) return;
    const { x, z } = carOffset(car, span, state.clock.elapsedTime);
    ref.current.position.x = x;
    ref.current.position.z = z;
  });

  if (!spec) return null;
  const start = carOffset(car, span, 0);
  return (
    <group ref={ref} position={[start.x, 0, start.z]} rotation-y={car.rotY}>
      <Suspense fallback={null}>
        <Model spec={spec} />
      </Suspense>
    </group>
  );
}
