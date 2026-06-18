/**
 * Wave H4 (EM-209) — Critter follow/wander logic.
 *
 * The useFrame hot-path in Critter.tsx branches on `ownerPos` to either trail
 * the owner (owned pet) or orbit the place center (unowned/wild). The pure
 * helper `resolveFollowTarget` captures that decision and is tested here
 * without any R3F canvas setup (same pattern as Building.test.tsx /
 * characterAnim.test.ts).
 *
 * Covers:
 *  • When ownerPos is present, the follow target offsets slightly (+0.6 x/z)
 *    so the pet trails the owner without sitting exactly on top.
 *  • When ownerPos is absent (undefined) the helper returns null — the
 *    useFrame code takes the wander branch.
 *  • When ownerPos is null (owner gone, pre-H4 snapshot) it also returns null
 *    — no crash, no stuck-at-origin, graceful fallback.
 */

import { describe, expect, it } from 'vitest';
import { resolveFollowTarget } from './Critter';

describe('resolveFollowTarget (Wave H4 EM-209 follow/wander branch)', () => {
  it('returns an offset target when ownerPos is present', () => {
    const result = resolveFollowTarget({ x: 10, z: 5 });
    expect(result).not.toBeNull();
    expect(result!.x).toBeCloseTo(10.6, 5);
    expect(result!.z).toBeCloseTo(5.6, 5);
  });

  it('returns null when ownerPos is undefined (unowned / wander path)', () => {
    expect(resolveFollowTarget(undefined)).toBeNull();
  });

  it('returns null when ownerPos is null (owner gone — safe fallback, no crash)', () => {
    expect(resolveFollowTarget(null)).toBeNull();
  });

  it('owner at origin still produces a valid follow offset', () => {
    const result = resolveFollowTarget({ x: 0, z: 0 });
    expect(result).not.toBeNull();
    expect(result!.x).toBeCloseTo(0.6, 5);
    expect(result!.z).toBeCloseTo(0.6, 5);
  });

  it('tracks negative coordinates correctly (all quadrants)', () => {
    const result = resolveFollowTarget({ x: -8, z: -3 });
    expect(result!.x).toBeCloseTo(-7.4, 5);
    expect(result!.z).toBeCloseTo(-2.4, 5);
  });
});
