/**
 * characterAnim.ts — pure (canvas-free) helpers behind the EM-124 animated
 * characters: movement-state hysteresis, animation clip selection, walk-facing
 * yaw math, and the species → GLB model lookup.
 *
 * Everything here is plain math/lookup so vitest can exercise it without a
 * WebGL context (same convention as worldSpace.ts / toonify.ts). Villager.tsx
 * and Critter.tsx consume these from their useFrame loops.
 */

import { CHARACTER_MODELS, type ModelSpec } from './assets/models';

// ── Movement state (hysteresis) ───────────────────────────────────────────────

/**
 * Start/stop distance thresholds (world units) for the moving/idle decision.
 * `start` > `stop` gives hysteresis: a character begins walking only once its
 * distance-to-target exceeds `start`, and returns to idle only once it drops
 * below `stop` — so the exponential lerp's tail can't flicker the clip at a
 * single epsilon boundary.
 */
export interface MoveThresholds {
  start: number;
  stop: number;
}

/** Villager thresholds — `start` matches the Wave B moving epsilon (0.05). */
export const VILLAGER_MOVE: MoveThresholds = { start: 0.05, stop: 0.02 };

/** Critter thresholds — `start` matches the Wave B wander epsilon (0.02). */
export const CRITTER_MOVE: MoveThresholds = { start: 0.02, stop: 0.008 };

/**
 * Next moving state given the previous one and the current distance to the
 * lerp target. Pure hysteresis: between `stop` and `start` the previous state
 * holds, so the clip never flickers around a single boundary.
 */
export function nextMoving(
  prev: boolean,
  dist: number,
  t: MoveThresholds,
): boolean {
  return prev ? dist > t.stop : dist > t.start;
}

// ── Clip selection ────────────────────────────────────────────────────────────

/**
 * Pick the animation clip name for a movement state. Falls back to the idle
 * clip when a spec has no walk clip (and to null when it has no clips at all,
 * which callers treat as "don't drive the mixer").
 */
export function clipFor(
  moving: boolean,
  clips?: { idle?: string; walk?: string },
): string | null {
  if (!clips) return null;
  return (moving ? clips.walk ?? clips.idle : clips.idle) ?? null;
}

// ── Facing math ───────────────────────────────────────────────────────────────

/**
 * Yaw (Y rotation, radians) that faces a +Z-forward model along the movement
 * vector (dx, dz). Identical to the Wave B capsule's atan2 facing.
 */
export function yawTowards(dx: number, dz: number): number {
  return Math.atan2(dx, dz);
}

/** Normalize an angle into (-π, π] — the shortest signed rotation. */
export function wrapAngle(a: number): number {
  let r = a;
  while (r > Math.PI) r -= Math.PI * 2;
  while (r <= -Math.PI) r += Math.PI * 2;
  return r;
}

/**
 * One smoothing step of the current yaw toward a target yaw, always along the
 * shortest arc (wrap-aware). `rate` is the per-second catch-up factor; the
 * step is clamped so large deltas can't overshoot. Matches the Wave B
 * smoothing (villagers rate 8, critters rate 6).
 */
export function stepYaw(
  current: number,
  target: number,
  delta: number,
  rate: number,
): number {
  const diff = wrapAngle(target - current);
  return current + diff * Math.min(1, delta * rate);
}

// ── Species → model ───────────────────────────────────────────────────────────

/**
 * Resolve a critter species to its rigged GLB spec. Only cat/dog have models;
 * any other species (e.g. EM-143's god-spawned squirrels) returns null and the
 * Critter renders its procedural body instead.
 */
export function critterModelFor(species: string): ModelSpec | null {
  if (species === 'cat') return CHARACTER_MODELS.cat;
  if (species === 'dog') return CHARACTER_MODELS.dog;
  return null;
}
