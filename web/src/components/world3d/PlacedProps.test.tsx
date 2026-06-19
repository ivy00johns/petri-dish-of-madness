/**
 * PlacedProps.test.tsx — Wave K (EM-218) prop render gate (jsdom; the <Model>
 * GLB wrapper is mocked exactly like the CityScape/structure render tests so no
 * GLB loads). Proves:
 *
 *   • each tracked Prop renders at placeToWorld(place) + (dx, dz);
 *   • a KNOWN kind streams its mapped GLB (via the mocked <Model>);
 *   • an UNKNOWN / off-menu kind renders the PROCEDURAL fallback — never a hole;
 *   • a prop whose place no longer exists is skipped (no free-floating render);
 *   • the mock generator seeds representative props (the FE demo substrate).
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import type { Place, Prop } from '../../types';
import { placeToWorld } from './worldSpace';
import { PROP_MODELS } from './assets/propModels';

// Replace the GLB <Model> with a queryable stub tag carrying the resolved url,
// so we can assert WHICH GLB a known prop kind mounts without loading bytes.
vi.mock('./assets/Model', () => ({
  Model: ({ spec }: { spec: { url: string } }) => (
    // R3F tag — react-dom renders it as an unknown element in jsdom.
    <propGlbStub data-url={spec.url} name={`prop-glb:${spec.url}`} />
  ),
}));

import { PlacedProps } from './PlacedProps';
import { buildInitialWorldState } from '../../mock/generator';

afterEach(cleanup);

const PLACES: Place[] = [
  { id: 'plaza', name: 'Central Plaza', x: 500, y: 500, kind: 'social', description: '' },
  { id: 'commons', name: 'The Commons', x: 500, y: 750, kind: 'wild', description: '' },
  { id: 'market', name: 'Market', x: 750, y: 400, kind: 'work', description: '' },
];

/** react-dom logs unknown-tag warnings for R3F elements; silence for the smoke. */
function renderProps(places: Place[], props: Prop[] | undefined) {
  const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  try {
    return render(<PlacedProps places={places} props={props} />);
  } finally {
    errSpy.mockRestore();
    warnSpy.mockRestore();
  }
}

describe('PlacedProps render (EM-218)', () => {
  it('mounts a known-kind prop as its mapped GLB', () => {
    const props: Prop[] = [
      { id: 'p1', kind: 'bench', place: 'plaza', dx: 1, dz: 0, owner_id: 'ada' },
    ];
    const { container } = renderProps(PLACES, props);
    const stub = container.querySelector('propGlbStub');
    expect(stub).not.toBeNull();
    expect(stub!.getAttribute('data-url')).toBe(PROP_MODELS.bench.url);
  });

  it('renders the PROCEDURAL fallback (never a hole) for an unknown kind', () => {
    const props: Prop[] = [
      { id: 'p1', kind: 'garden_gnome', place: 'plaza', dx: 0, dz: 0, owner_id: null },
    ];
    const { container } = renderProps(PLACES, props);
    // no GLB stub for the unknown kind…
    expect(container.querySelector('propGlbStub')).toBeNull();
    // …but a procedural marker DID render (cylinder base + sphere cap).
    expect(container.querySelector('cylinderGeometry')).not.toBeNull();
    expect(container.querySelector('sphereGeometry')).not.toBeNull();
  });

  it('positions each prop at placeToWorld(place) + (dx, dz)', () => {
    const props: Prop[] = [
      { id: 'p1', kind: 'lamp', place: 'commons', dx: 2.5, dz: -1.5, owner_id: null },
    ];
    const { container } = renderProps(PLACES, props);
    // The outer group of a placed prop carries the world position. react-dom
    // serializes the `position` array prop onto the <group> tag.
    const groups = Array.from(container.querySelectorAll('group'));
    const center = placeToWorld(PLACES[1]); // commons
    const wantX = center.x + 2.5;
    const wantZ = center.z - 1.5;
    const matched = groups.some((g) => {
      const pos = g.getAttribute('position');
      if (!pos) return false;
      const [x, , z] = pos.split(',').map(Number);
      return Math.abs(x - wantX) < 1e-6 && Math.abs(z - wantZ) < 1e-6;
    });
    expect(matched).toBe(true);
  });

  it('renders one node per prop and skips props whose place is missing', () => {
    const props: Prop[] = [
      { id: 'p1', kind: 'bench', place: 'plaza', dx: 0, dz: 0, owner_id: null },
      { id: 'p2', kind: 'tree', place: 'commons', dx: 0, dz: 0, owner_id: null },
      // place 'nowhere' is not in PLACES → skipped (no free-floating render).
      { id: 'p3', kind: 'fence', place: 'nowhere', dx: 0, dz: 0, owner_id: null },
    ];
    const { container } = renderProps(PLACES, props);
    const stubs = container.querySelectorAll('propGlbStub');
    expect(stubs.length).toBe(2); // p1 + p2; p3 skipped
  });

  it('renders nothing when there are no props (absent-safe)', () => {
    const { container: a } = renderProps(PLACES, undefined);
    expect(a.querySelector('propGlbStub')).toBeNull();
    const { container: b } = renderProps(PLACES, []);
    expect(b.querySelector('propGlbStub')).toBeNull();
  });
});

describe('mock generator seeds representative props (FE demo substrate)', () => {
  it('the initial world_state carries placeable props at known places', () => {
    const world = buildInitialWorldState();
    expect(Array.isArray(world.props)).toBe(true);
    expect(world.props!.length).toBeGreaterThan(0);
    // every seeded prop sits at an existing place and has numeric offsets
    const placeIds = new Set(world.places.map((p) => p.id));
    for (const prop of world.props!) {
      expect(typeof prop.id).toBe('string');
      expect(typeof prop.kind).toBe('string');
      expect(placeIds.has(prop.place), `prop ${prop.id} at unknown place ${prop.place}`).toBe(true);
      expect(Number.isFinite(prop.dx)).toBe(true);
      expect(Number.isFinite(prop.dz)).toBe(true);
    }
  });

  it('the seeded props render through PlacedProps (known kinds + a fallback)', () => {
    const world = buildInitialWorldState();
    const { container } = renderProps(world.places, world.props);
    // at least the known-kind props mount a GLB stub…
    expect(container.querySelectorAll('propGlbStub').length).toBeGreaterThan(0);
    // …and the seeded off-menu kind exercises the procedural fallback.
    expect(container.querySelector('cylinderGeometry')).not.toBeNull();
  });
});
