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

const PREFERS_REDUCED_MOTION =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

interface TrafficProps {
  seed: number;
  streets: readonly CityStreet[];
}

/** The whole ambient fleet. */
export function Traffic({ seed, streets }: TrafficProps) {
  const cars = useMemo(() => computeTraffic(seed, streets), [seed, streets]);
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
