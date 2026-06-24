/**
 * traffic.ts — EM-169 ambient vehicle traffic (pure, deterministic math).
 *
 * The city is a frozen 5×5 grid of road centerlines (cityLayout.computeStreets):
 * each CityStreet runs along one axis ('ns' ⇒ constant x = `at`, varying z;
 * 'ew' ⇒ constant z = `at`, varying x). This module assigns a small, seeded set
 * of cars to the INTERIOR (main) streets and gives a pure `carOffset(car, span,
 * t)` that sweeps each car along its street and wraps at the city edge.
 *
 * Determinism: the car SET is a pure function of (seed, streets) — same inputs,
 * same fleet (so it survives reload/fork like the rest of the city, EM-155). The
 * per-frame motion is clock-driven and PURELY VISUAL (ambient eye-candy, never
 * fed back into sim state), so it is not part of the replay surface.
 *
 * Why interior-only + modest count: the outer ring road stays empty (matches the
 * sparse-label law) and the fleet is ≤ the main-street count, so traffic reads as
 * "a few cars about town", not a freeway — and the render stays cheap.
 */

import { hashUnit } from './worldSpace';
import type { CityStreet } from './cityLayout';

/** Master switch (EM-176 re-entry point — flip to false for the pre-W17 look). */
export const TRAFFIC_ENABLED = true;

const HALF_PI = Math.PI / 2;
/** Lateral nudge off the centerline so a car doesn't straddle the middle line. */
const LANE = 0.62;
/** Travel a little past the grid before wrapping, so cars enter/exit off-screen. */
const MARGIN = 4;
/** Fraction of main streets that stay empty (some quiet lanes). */
const EMPTY_ABOVE = 0.85;

export const CAR_KINDS = ['car_a', 'car_b', 'car_c'] as const;
export type CarKind = (typeof CAR_KINDS)[number];

export interface TrafficCar {
  /** Stable id (`car:<streetId>`). */
  id: string;
  axis: 'ns' | 'ew';
  /** Constant cross-axis coordinate the car drives along (centerline ± lane). */
  at: number;
  /** Travel direction along the varying axis (+1 / −1). */
  dir: 1 | -1;
  /** World units per second (gentle). */
  speed: number;
  /** Initial progress along the sweep, [0, 1). */
  phase: number;
  kind: CarKind;
  /** Heading (Y rotation, radians) — the car GLB long axis is local Z. */
  rotY: number;
}

/** Half the sweep length: max |centerline| over the streets, plus a margin. */
export function trafficSpan(streets: readonly CityStreet[]): number {
  let m = 0;
  for (const s of streets) m = Math.max(m, Math.abs(s.at));
  return m + MARGIN;
}

/** Deterministic car fleet for a seed + the city's streets (interior only). */
export function computeTraffic(
  seed: number,
  streets: readonly CityStreet[],
): TrafficCar[] {
  const out: TrafficCar[] = [];
  for (const s of streets) {
    if (!s.main) continue; // ring road stays empty
    const hh = (p: string) => hashUnit(`traffic:${seed}:${s.id}:${p}`);
    if (hh('spawn') > EMPTY_ABOVE) continue;
    const dir: 1 | -1 = hh('dir') < 0.5 ? 1 : -1;
    const kind = CAR_KINDS[Math.floor(hh('kind') * CAR_KINDS.length) % CAR_KINDS.length];
    const speed = 1.4 + hh('speed') * 1.6; // 1.4–3.0 u/s
    const phase = hh('phase');
    const rotY =
      s.axis === 'ns' ? (dir === 1 ? 0 : Math.PI) : dir === 1 ? HALF_PI : -HALF_PI;
    out.push({ id: `car:${s.id}`, axis: s.axis, at: s.at + dir * LANE, dir, speed, phase, kind, rotY });
  }
  return out;
}

/** Pure world position of a car at time `t` (seconds); sweeps + wraps the span. */
export function carOffset(
  car: TrafficCar,
  span: number,
  t: number,
): { x: number; z: number } {
  const L = 2 * span;
  const u = (((car.phase + (car.speed * t) / L) % 1) + 1) % 1;
  const base = -span + u * L; // -span .. +span
  const along = car.dir === 1 ? base : -base;
  return car.axis === 'ns' ? { x: car.at, z: along } : { x: along, z: car.at };
}
