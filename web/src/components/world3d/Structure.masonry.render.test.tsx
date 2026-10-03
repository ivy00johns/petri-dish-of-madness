/**
 * Structure.masonry.render.test.tsx — the under-construction render is
 * MASONRY: discrete floor courses (never one smooth extruded box). With a
 * 4-floor recipe at progress 50%, exactly 2 full floors are laid; at 62.5%
 * a partial course rises above them; at 100% all 4 are laid and the roof cap
 * appears. jsdom harness mirrors Structure.skin.test.tsx; the RoundedBox stub
 * CAPTURES its args so the course heights are inspectable.
 */
import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, cleanup } from '@testing-library/react';
import type { Building, BuildingRecipe } from '../../types';

// Every RoundedBox mount's args — the foundation slab + one per course.
const boxArgs: Array<[number, number, number]> = [];

vi.mock('./assets/Model', () => ({
  Model: () => <modelStub />,
  useToonGLTF: () => ({ scene: null, animations: [] }),
}));

vi.mock('@react-three/fiber', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('@react-three/fiber');
  return { ...actual, useFrame: () => {} };
});
vi.mock('./useProximity', () => ({
  useProximity: () => false,
  PLACE_LABEL_DIST: 32,
}));
vi.mock('@react-three/drei', () => ({
  useCursor: () => {},
  Billboard: ({ children }: { children?: ReactNode }) => <group>{children}</group>,
  Text: () => null,
  RoundedBox: ({
    args,
    children,
    ...rest
  }: {
    args?: [number, number, number];
    children?: ReactNode;
    [k: string]: unknown;
  }) => {
    if (args) boxArgs.push(args);
    return (
      <mesh {...rest}>
        <boxGeometry args={args} />
        {children}
      </mesh>
    );
  },
}));

import { Structure, floorCountFor } from './Structure';

const RECIPE: BuildingRecipe = {
  footprint: 'grand', floors: 4, roof: 'dome', material: 'marble',
  palette: 'warm', window_density: 'dense', trim: 'gilded',
};

function building(overrides: Partial<Building>): Building {
  return {
    id: 'b1',
    name: 'Clocktower',
    kind: 'house',
    location: 'plaza',
    owner_id: 'ada',
    status: 'under_construction',
    health: 100,
    condition_label: 'pristine',
    progress: 0,
    funds_committed: 12,
    funds_required: 12,
    contributors: [],
    function: 'voting',
    ...overrides,
  };
}

beforeEach(() => {
  boxArgs.length = 0;
});
afterEach(cleanup);

/** The foundation slab box (always 0.3 tall). */
const foundations = () =>
  boxArgs.filter(([, h]) => Math.abs(h - 0.3) < 1e-6).length;
/** Full course boxes for a given floor count: height exactly 3.2/floors. */
const fullCourses = (floors: number) => {
  const floorH = 3.2 / Math.max(1, floors);
  return boxArgs.filter(([, h]) => Math.abs(h - floorH) < 1e-6).length;
};
/** The partial course rising above the last laid floor (≥0.1, < floorH,
 *  distinct from the 0.3 foundation). */
const partialCourse = (floors: number) => {
  const floorH = 3.2 / Math.max(1, floors);
  return boxArgs.filter(([, h]) => h >= 0.1 && h < floorH - 1e-6 && Math.abs(h - 0.3) > 1e-6).length;
};
/** Roof cap cones mount in the tree near completion. */
const cones = (container: HTMLElement) => container.querySelectorAll('coneGeometry').length;

describe('Structure masonry under-construction render', () => {
  it('progress 50% of a 4-floor recipe lays exactly 2 full floors (no partial, no roof)', () => {
    render(<Structure building={building({ recipe: RECIPE, progress: 50 })} x={0} z={0} />);
    expect(foundations()).toBe(1);
    expect(fullCourses(4)).toBe(2); // discrete, not one 3.2-tall box
    expect(partialCourse(4)).toBe(0);
  });

  it('progress 62.5% lays 2 full floors + a partial course rising above them', () => {
    const { container } = render(
      <Structure building={building({ recipe: RECIPE, progress: 62.5 })} x={0} z={0} />,
    );
    expect(fullCourses(4)).toBe(2);
    expect(partialCourse(4)).toBe(1); // the in-progress 3rd floor
    expect(cones(container)).toBe(0); // not topped out yet
  });

  it('progress 100% lays all 4 floors and caps the roof', () => {
    const { container } = render(
      <Structure building={building({ recipe: RECIPE, progress: 100 })} x={0} z={0} />,
    );
    expect(fullCourses(4)).toBe(4);
    expect(partialCourse(4)).toBe(0);
    expect(cones(container)).toBe(1); // the roof cap
  });

  it('a recipe-less building still stacks (hash-derived 2-4 floors), never one box', () => {
    // The pure helper pins b1's exact floor count; the render must lay exactly
    // that many DISCRETE courses (and never a single smooth 3.2 extrusion).
    const floors = floorCountFor(building({}));
    render(<Structure building={building({ progress: 100 })} x={0} z={0} />);
    expect(foundations()).toBe(1);
    expect(fullCourses(floors)).toBe(floors);
    expect(partialCourse(floors)).toBe(0);
    expect(boxArgs.some(([, h]) => Math.abs(h - 3.2) < 1e-6)).toBe(false);
  });
});
