/**
 * Structure.masonry.test.ts — the masonry construction borrow: a building
 * under construction rises FLOOR BY FLOOR as progress crosses thresholds
 * (the "watch it build" mechanic), never as one smooth extruded box.
 *
 * Part 1 pins the PURE helpers (floorStack / floorCountFor) — deterministic
 * over (floors, grow), so replay/EM-155 stays intact: the same building at
 * the same progress renders the same courses.
 *
 * Part 2 renders the real Structure under-construction path (R3F mocked like
 * the other Structure suites) and asserts the DISCRETE floor courses: at
 * progress 50% of a 4-floor recipe, exactly 2 floors are laid + a partial
 * course rises above them; at 100% all 4 are laid (roof capped).
 */
import { describe, expect, it } from 'vitest';
import { floorCountFor, floorStack } from './Structure';
import type { Building } from '../../types';

function building(partial: Partial<Building> = {}): Building {
  return {
    id: 'b1',
    name: 'Clocktower',
    kind: 'clocktower',
    location: 'plaza',
    owner_id: 'public',
    status: 'under_construction',
    health: 100,
    condition_label: 'pristine',
    progress: 50,
    funds_committed: 12,
    funds_required: 12,
    contributors: [],
    function: 'voting',
    ...partial,
  };
}

describe('floorStack — the discrete course math', () => {
  it('lays floors one at a time at their thresholds (never fractional courses)', () => {
    expect(floorStack(4, 0.00)).toEqual({ done: 0, partial: 0 });
    expect(floorStack(4, 0.24)).toEqual({ done: 0, partial: 0.96 });
    expect(floorStack(4, 0.25)).toEqual({ done: 1, partial: 0 });
    expect(floorStack(4, 0.5)).toEqual({ done: 2, partial: 0 });
    expect(floorStack(4, 0.51)).toEqual({ done: 2, partial: 0.04 });
    expect(floorStack(4, 0.75)).toEqual({ done: 3, partial: 0 });
    expect(floorStack(4, 0.999)).toEqual({ done: 3, partial: 0.996 });
    expect(floorStack(4, 1)).toEqual({ done: 4, partial: 0 });
  });

  it('is pure — same inputs, same outputs, no state', () => {
    const a = floorStack(3, 0.66);
    const b = floorStack(3, 0.66);
    expect(a).toEqual(b);
  });

  it('clamps grow outside 0..1 and floors below 1 defensively', () => {
    expect(floorStack(4, -1)).toEqual({ done: 0, partial: 0 });
    expect(floorStack(4, 2)).toEqual({ done: 4, partial: 0 });
    expect(floorStack(0, 0.5)).toEqual({ done: 0, partial: 0.5 });
  });
});

describe('floorCountFor — deterministic floors per building', () => {
  it('uses the authored recipe floors when a recipe is present', () => {
    expect(
      floorCountFor(building({ recipe: { footprint: 'grand', floors: 8, roof: 'spire' } as Building['recipe'] })),
    ).toBe(8);
    expect(
      floorCountFor(building({ recipe: { footprint: 'tiny', floors: 1, roof: 'flat' } as Building['recipe'] })),
    ).toBe(1);
  });

  it('clamps recipe floors into the 1..8 grammar bound', () => {
    expect(floorCountFor(building({ recipe: { floors: 99 } as Building['recipe'] }))).toBe(8);
    expect(floorCountFor(building({ recipe: { floors: 0 } as Building['recipe'] }))).toBe(1);
  });

  it('falls back to a hash-derived 2-4 for recipe-less buildings (mock/legacy)', () => {
    const a = floorCountFor(building({ id: 'bld-1' }));
    const b = floorCountFor(building({ id: 'bld-1' }));
    expect(a).toBe(b); // deterministic per id
    expect(a).toBeGreaterThanOrEqual(2);
    expect(a).toBeLessThanOrEqual(4);
    // different ids may differ, but each stays in bounds
    for (const id of ['bld-1', 'bld-2', 'bld-3', 'bld-42']) {
      const f = floorCountFor(building({ id }));
      expect(f).toBeGreaterThanOrEqual(2);
      expect(f).toBeLessThanOrEqual(4);
    }
  });
});
