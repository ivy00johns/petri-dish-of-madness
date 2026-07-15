/**
 * Structure.recipe.test.tsx — EM-299 (Wave Q) recipe render gate.
 *
 * The rule in Structure.tsx: an OPERATIONAL/OFFLINE building with a `recipe`
 * renders the procedural RecipeStructure (computeBuildingMesh) INSTEAD of the
 * catalog GLB / EM-122 silhouette; with NO recipe the render is byte-for-byte
 * the pre-EM-299 path (the GLB <Model> still mounts). A recipe never affects the
 * planned/under-construction/ruin states.
 *
 * jsdom harness mirrors Structure.skin.test.tsx: the GLB <Model> and the R3F
 * frame/proximity/cursor hooks are mocked so nothing touches WebGL.
 */

import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, cleanup } from '@testing-library/react';
import type { Building, BuildingRecipe } from '../../types';

const modelMounts: Array<{ url?: string }> = [];

vi.mock('./assets/Model', () => ({
  Model: (props: { spec?: { url: string } }) => {
    modelMounts.push({ url: props.spec?.url });
    return <modelStub />;
  },
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
// drei components run useLayoutEffects against the (absent) R3F renderer in
// jsdom (<Billboard>/<RoundedBox> both hit `.center()`). Stub them inert; the
// RoundedBox still emits a real <boxGeometry> so the body mesh is inspectable
// (the same idiom as Structure.fund.test.tsx).
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
  }) => (
    <mesh {...rest}>
      <boxGeometry args={args} />
      {children}
    </mesh>
  ),
}));

import { Structure } from './Structure';

const RECIPE: BuildingRecipe = {
  footprint: 'grand', floors: 4, roof: 'dome', material: 'marble',
  palette: 'warm', window_density: 'dense', trim: 'gilded',
};

function building(overrides: Partial<Building>): Building {
  return {
    id: 'b1',
    name: 'Test',
    kind: 'house', // 'house' has a real GLB → the Model path runs when no recipe
    location: 'plaza',
    owner_id: 'ada',
    status: 'operational',
    health: 100,
    condition_label: 'pristine',
    progress: 100,
    funds_committed: 0,
    funds_required: 0,
    contributors: [],
    function: '+energy',
    ...overrides,
  };
}

function renderStructure(b: Building) {
  const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  try {
    return render(<Structure building={b} x={0} z={0} />);
  } finally {
    errSpy.mockRestore();
    warnSpy.mockRestore();
  }
}

beforeEach(() => {
  modelMounts.length = 0;
});
afterEach(cleanup);

describe('Structure recipe render (EM-299)', () => {
  it('no recipe ⇒ the pre-EM-299 GLB path runs (Model mounts)', () => {
    renderStructure(building({ recipe: null }));
    expect(modelMounts.some((m) => m.url), 'the house GLB should still mount').toBe(true);
  });

  it('a recipe REPLACES the catalog path — no GLB Model mounts', () => {
    renderStructure(building({ recipe: RECIPE }));
    expect(modelMounts.some((m) => m.url), 'recipe should suppress the GLB').toBe(false);
  });

  it('a recipe building renders procedural geometry (meshes in the tree)', () => {
    const { container } = renderStructure(building({ recipe: RECIPE }));
    // RecipeStructure emits a RoundedBox body + roof + windows → many meshes.
    const meshes = container.querySelectorAll('mesh');
    expect(meshes.length).toBeGreaterThan(3);
  });

  it('an undefined recipe (pre-EM-299 backend) is safe — GLB path runs', () => {
    const b = building({});
    delete (b as { recipe?: unknown }).recipe;
    renderStructure(b);
    expect(modelMounts.some((m) => m.url)).toBe(true);
  });

  it('a recipe does NOT alter the planned state (no GLB, no crash)', () => {
    // planned buildings show the surveyor stake regardless of a recipe; the
    // recipe only governs the operational/offline silhouette.
    const { container } = renderStructure(building({ status: 'planned', recipe: RECIPE }));
    expect(modelMounts.some((m) => m.url)).toBe(false);
    expect(container.querySelectorAll('mesh').length).toBeGreaterThan(0);
  });
});
