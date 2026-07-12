/**
 * SurfaceDecal component tests (EM-298 / EM-302b).
 *
 * The facade mural must render its textured plane at the MEASURED front face
 * of whichever GLB the Structure renderer resolved for the painted building —
 * not the old fixed z=1.06 — and shrink/lower on short models. drei is mocked
 * (useTexture returns a stub; jsdom never loads bytes), the PlazaBanner test
 * idiom: R3F tags render as plain DOM elements whose array props serialize,
 * so the mesh `position`/`scale` attributes are directly assertable.
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';

const failingUrls = new Set<string>();

vi.mock('@react-three/drei', () => ({
  useTexture: (url: string) => {
    if (failingUrls.has(url)) throw new Error(`Could not load ${url}: 404`);
    return { __stubUrl: url, isTexture: true };
  },
}));

import { SurfaceDecal } from './SurfaceDecal';
import { DECAL_BASE_Y, LEGACY_DECAL_Z, decalPlacement } from './decalLayout';

afterEach(() => {
  cleanup();
  failingUrls.clear();
});

const URL = '/assets/images/img_0000000001.png';

function renderDecal(props: Parameters<typeof SurfaceDecal>[0]) {
  const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  try {
    return render(<SurfaceDecal {...props} />);
  } finally {
    errSpy.mockRestore();
    warnSpy.mockRestore();
  }
}

function meshPosition(container: HTMLElement): [number, number, number] {
  const mesh = container.querySelector('mesh');
  expect(mesh).not.toBeNull();
  const pos = (mesh!.getAttribute('position') ?? '').split(',').map(Number);
  expect(pos).toHaveLength(3);
  return pos as [number, number, number];
}

describe('SurfaceDecal (EM-302b placement)', () => {
  it('places the textured plane at the measured GLB front for the building', () => {
    const building = { id: 'b1', kind: 'tavern', status: 'operational' as const };
    const want = decalPlacement(building);
    const { container } = renderDecal({ x: 4, z: -2, url: URL, building });
    expect(container.querySelector('meshToonMaterial')).not.toBeNull();
    const [px, py, pz] = meshPosition(container);
    expect(px).toBeCloseTo(want.x, 6);
    expect(py).toBeCloseTo(want.y, 6);
    expect(pz).toBeCloseTo(want.z, 6);
    // The defect: the old fixed plane sat at 1.06 INSIDE this deep facade.
    expect(pz).toBeGreaterThan(1.5);
    // The outer group carries the lot-spot world position.
    const group = container.querySelector('group');
    expect(group?.getAttribute('position')).toBe('4,0,-2');
  });

  it('offsets the plane to the measured facade x-center (x-offset GLB)', () => {
    const building = { id: 'd1', kind: 'dock', status: 'operational' as const };
    const want = decalPlacement(building);
    expect(Math.abs(want.x)).toBeGreaterThan(0.5); // sanity: dock IS x-offset
    const { container } = renderDecal({ x: 0, z: 0, url: URL, building });
    const [px] = meshPosition(container);
    expect(px).toBeCloseTo(want.x, 6);
  });

  it('shrinks the canvas on a short model (garden bed)', () => {
    const building = { id: 'g1', kind: 'garden', status: 'operational' as const };
    const want = decalPlacement(building);
    expect(want.scale).toBeLessThan(1); // sanity: garden IS the short case
    const { container } = renderDecal({ x: 0, z: 0, url: URL, building });
    const mesh = container.querySelector('mesh')!;
    const scale = (mesh.getAttribute('scale') ?? '').split(',').map(Number);
    expect(scale[0]).toBeCloseTo(want.scale, 6);
    expect(scale[1]).toBeCloseTo(want.scale, 6);
    expect(scale[2]).toBe(1);
    const [, py] = meshPosition(container);
    expect(py).toBeCloseTo(want.y, 6);
    expect(py).toBeLessThan(DECAL_BASE_Y);
  });

  it('keeps the legacy plane for a not-yet-built facade', () => {
    const building = { id: 'p1', kind: 'house', status: 'planned' as const };
    const { container } = renderDecal({ x: 0, z: 0, url: URL, building });
    const [, py, pz] = meshPosition(container);
    expect(py).toBeCloseTo(DECAL_BASE_Y, 6);
    expect(pz).toBeCloseTo(LEGACY_DECAL_Z, 6);
  });

  it('renders NOTHING (clean facade, no hole) when the texture 404s', () => {
    failingUrls.add(URL);
    const building = { id: 'b1', kind: 'tavern', status: 'operational' as const };
    const { container } = renderDecal({ x: 0, z: 0, url: URL, building });
    expect(container.querySelector('meshToonMaterial')).toBeNull();
    expect(container.querySelector('mesh')).toBeNull();
  });
});
