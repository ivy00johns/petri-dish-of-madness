/**
 * characterAnim.test.ts — the EM-124 pure helpers: movement hysteresis, clip
 * selection, facing math, and the species → GLB lookup (no canvas needed).
 */

import { describe, expect, it } from 'vitest';
import {
  clipFor,
  critterModelFor,
  nextMoving,
  stepYaw,
  wrapAngle,
  yawTowards,
  CRITTER_MOVE,
  VILLAGER_MOVE,
} from './characterAnim';
import { CHARACTER_MODELS } from './assets/models';

describe('nextMoving (hysteresis)', () => {
  const T = { start: 0.05, stop: 0.02 };

  it('starts walking only above the start threshold', () => {
    expect(nextMoving(false, 0.049, T)).toBe(false);
    expect(nextMoving(false, 0.05, T)).toBe(false); // strict >
    expect(nextMoving(false, 0.051, T)).toBe(true);
  });

  it('stops walking only below the stop threshold', () => {
    expect(nextMoving(true, 0.021, T)).toBe(true);
    expect(nextMoving(true, 0.02, T)).toBe(false);
    expect(nextMoving(true, 0.001, T)).toBe(false);
  });

  it('holds the previous state in the dead zone (no flicker at the boundary)', () => {
    // A distance hovering between stop and start never toggles the state.
    const hover = 0.035;
    expect(nextMoving(false, hover, T)).toBe(false);
    expect(nextMoving(true, hover, T)).toBe(true);
  });

  it('a decaying lerp tail walks then settles exactly once', () => {
    // Simulate the exponential approach: distance shrinks each frame.
    const dists = [0.6, 0.3, 0.12, 0.045, 0.03, 0.019, 0.012, 0.03, 0.04];
    let moving = false;
    const states = dists.map((d) => (moving = nextMoving(moving, d, T)));
    // Walks through the dead zone, stops at 0.019, and small jitter back into
    // the dead zone (0.03/0.04) does NOT restart the walk.
    expect(states).toEqual([true, true, true, true, true, false, false, false, false]);
  });

  it('villager and critter thresholds keep start > stop (hysteresis exists)', () => {
    expect(VILLAGER_MOVE.start).toBeGreaterThan(VILLAGER_MOVE.stop);
    expect(CRITTER_MOVE.start).toBeGreaterThan(CRITTER_MOVE.stop);
    // Start thresholds match the Wave B moving epsilons.
    expect(VILLAGER_MOVE.start).toBe(0.05);
    expect(CRITTER_MOVE.start).toBe(0.02);
  });
});

describe('clipFor', () => {
  const clips = { idle: 'Idle', walk: 'Walking_A' };

  it('picks idle at rest and walk in motion', () => {
    expect(clipFor(false, clips)).toBe('Idle');
    expect(clipFor(true, clips)).toBe('Walking_A');
  });

  it('falls back to idle when a spec has no walk clip', () => {
    expect(clipFor(true, { idle: 'Idle' })).toBe('Idle');
  });

  it('returns null when there are no usable clips', () => {
    expect(clipFor(false, undefined)).toBeNull();
    expect(clipFor(true, {})).toBeNull();
    expect(clipFor(false, { walk: 'Walk' })).toBeNull(); // idle missing at rest
  });

  it('matches the registry clip names for all three characters', () => {
    expect(clipFor(true, CHARACTER_MODELS.villager?.clips)).toBe('Walking_A');
    expect(clipFor(false, CHARACTER_MODELS.villager?.clips)).toBe('Idle');
    expect(clipFor(true, CHARACTER_MODELS.cat?.clips)).toBe('Walk');
    expect(clipFor(false, CHARACTER_MODELS.cat?.clips)).toBe('Idle');
    expect(clipFor(true, CHARACTER_MODELS.dog?.clips)).toBe('Walk');
    expect(clipFor(false, CHARACTER_MODELS.dog?.clips)).toBe('Idle');
  });
});

describe('yawTowards', () => {
  it('faces +Z movement at yaw 0 (three.js forward convention)', () => {
    expect(yawTowards(0, 1)).toBeCloseTo(0);
  });

  it('faces +X movement at +π/2 and -X at -π/2', () => {
    expect(yawTowards(1, 0)).toBeCloseTo(Math.PI / 2);
    expect(yawTowards(-1, 0)).toBeCloseTo(-Math.PI / 2);
  });

  it('faces -Z movement at π', () => {
    expect(Math.abs(yawTowards(0, -1))).toBeCloseTo(Math.PI);
  });
});

describe('wrapAngle', () => {
  it('passes through angles already in (-π, π]', () => {
    expect(wrapAngle(0)).toBe(0);
    expect(wrapAngle(1.5)).toBe(1.5);
    expect(wrapAngle(-3)).toBe(-3);
  });

  it('wraps over-rotations back into range', () => {
    expect(wrapAngle(Math.PI * 2)).toBeCloseTo(0);
    expect(wrapAngle(Math.PI + 0.1)).toBeCloseTo(-Math.PI + 0.1);
    expect(wrapAngle(-Math.PI - 0.1)).toBeCloseTo(Math.PI - 0.1);
    expect(wrapAngle(Math.PI * 7)).toBeCloseTo(Math.PI);
  });
});

describe('stepYaw', () => {
  it('moves part-way toward the target at small deltas', () => {
    // rate 8, delta 1/60 → 13.3% of the gap per frame.
    const next = stepYaw(0, 1, 1 / 60, 8);
    expect(next).toBeCloseTo(1 * (8 / 60));
    expect(next).toBeLessThan(1);
  });

  it('clamps to the target when delta*rate >= 1 (no overshoot)', () => {
    expect(stepYaw(0, 1, 0.5, 8)).toBeCloseTo(1);
    expect(stepYaw(2, -1, 1, 6)).toBeCloseTo(-1);
  });

  it('turns the short way across the ±π seam', () => {
    // From just below +π to just above -π: the short arc crosses the seam
    // (increasing yaw), not back through 0.
    const cur = Math.PI - 0.1;
    const target = -Math.PI + 0.1;
    const next = stepYaw(cur, target, 1 / 60, 8);
    expect(next).toBeGreaterThan(cur); // rotating forward through the seam
    // And converges: a full-strength step lands exactly on the target's arc.
    const landed = stepYaw(cur, target, 1, 8);
    expect(wrapAngle(landed - target)).toBeCloseTo(0);
  });

  it('is idempotent at the target', () => {
    expect(stepYaw(0.7, 0.7, 1 / 60, 8)).toBeCloseTo(0.7);
  });
});

describe('critterModelFor (species → GLB)', () => {
  it('maps all 7 species to their registry specs (EM-216b)', () => {
    expect(critterModelFor('cat')).toBe(CHARACTER_MODELS.cat);
    expect(critterModelFor('dog')).toBe(CHARACTER_MODELS.dog);
    expect(critterModelFor('squirrel')).toBe(CHARACTER_MODELS.squirrel);
    expect(critterModelFor('raccoon')).toBe(CHARACTER_MODELS.raccoon);
    expect(critterModelFor('goat')).toBe(CHARACTER_MODELS.goat);
    expect(critterModelFor('fox')).toBe(CHARACTER_MODELS.fox);
    expect(critterModelFor('crow')).toBe(CHARACTER_MODELS.crow);
  });

  it('returns null for unknown species (procedural fallback)', () => {
    expect(critterModelFor('')).toBeNull();
    expect(critterModelFor('CAT')).toBeNull(); // species ids are lowercase
    expect(critterModelFor('dragon')).toBeNull(); // a god-spawned exotic
  });
});
