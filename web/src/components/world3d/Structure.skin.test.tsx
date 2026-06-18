/**
 * Structure.skin.test.tsx — Wave K (EM-220) building-skin override gate, plus
 * EM-182 (a building renders at building.location, not the agent's).
 *
 * The skin logic in Structure.tsx is: the OPERATIONAL body color becomes
 * skinPalette(building.skin) ?? buildingStyle(kind).body, with healthTint
 * composed ON TOP (soot still shows). On the GLB path that resolves to the
 * <Model tint> the structure mounts — which this test captures via a mocked
 * <Model> — and the kind-palette body still stands when the skin is unknown.
 *
 * jsdom harness: the GLB <Model> and the R3F frame/proximity/cursor hooks are
 * mocked so nothing touches WebGL (the Building.test.tsx idiom).
 */

import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import type { Building } from '../../types';
import { skinPalette, healthTint, buildingStyle } from './worldSpace';
import { structureModelTint } from './structureModel';

// Capture every <Model> mount's props so we can assert the operational tint.
const modelMounts: Array<{ tint?: string; health?: number; url?: string }> = [];

vi.mock('./assets/Model', () => ({
  Model: (props: { spec?: { url: string }; tint?: string; health?: number }) => {
    modelMounts.push({ tint: props.tint, health: props.health, url: props.spec?.url });
    return <modelStub data-tint={props.tint ?? ''} />;
  },
  useToonGLTF: () => ({ scene: null, animations: [] }),
}));

// R3F frame loop + proximity/cursor are no-ops in jsdom.
vi.mock('@react-three/fiber', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('@react-three/fiber');
  return { ...actual, useFrame: () => {} };
});
// Keep the camera FAR so Structure renders the MiniMarker (a plain mesh)
// instead of the drei <Billboard> label (whose internal useFrame can't run
// outside a Canvas). The operational body + <Model> mount regardless of this.
vi.mock('./useProximity', () => ({
  useProximity: () => false,
  PLACE_LABEL_DIST: 32,
}));
vi.mock('@react-three/drei', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('@react-three/drei');
  return { ...actual, useCursor: () => {} };
});

import { Structure } from './Structure';

function building(overrides: Partial<Building>): Building {
  return {
    id: 'b1',
    name: 'Test',
    kind: 'house', // 'house' has a real GLB in MODEL_REGISTRY → the Model path runs
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

describe('Structure skin override (EM-220)', () => {
  it('a NAMED skin tints the operational GLB with that skin color', () => {
    renderStructure(building({ skin: 'sky', health: 100 }));
    const mount = modelMounts.find((m) => m.url); // the operational Model
    expect(mount, 'no operational Model mounted').toBeTruthy();
    expect(mount!.tint).toBe(skinPalette('sky'));
    expect(mount!.tint).toBe('#9bc7e8');
  });

  it('an UNKNOWN skin is ignored — the GLB falls back to the offline-dim idiom', () => {
    // Unknown skin → skinPalette null → tint is the (non-offline) undefined,
    // i.e. exactly what an un-skinned operational building gets.
    renderStructure(building({ skin: 'chartreuse', status: 'operational' }));
    const mount = modelMounts.find((m) => m.url);
    expect(mount!.tint).toBe(structureModelTint(false)); // undefined → untouched
  });

  it('health soot STILL composes on top of a skin (passed via the Model health prop)', () => {
    // EM-220 invariant: a re-skinned building still reads scorched at low health.
    renderStructure(building({ skin: 'rose', health: 30 }));
    const mount = modelMounts.find((m) => m.url);
    expect(mount!.tint).toBe(skinPalette('rose')); // skin sets the base tint…
    expect(mount!.health).toBe(30);                // …and Model composes soot via health
    // <Model> internally lerps tint toward soot by health (effectiveTint):
    // a re-skinned, half-burned building is NOT the pristine skin color.
    expect(healthTint(skinPalette('rose')!, 30)).not.toBe(skinPalette('rose'));
  });

  it('no skin keeps the kind palette body (skin override is purely additive)', () => {
    renderStructure(building({ skin: null, status: 'operational' }));
    const mount = modelMounts.find((m) => m.url);
    // un-skinned operational building → no body override on the GLB tint.
    expect(mount!.tint).toBeUndefined();
    // the kind palette body is the house body (unchanged by the absent skin).
    expect(buildingStyle('house').body).toBe('#f2cc8f');
  });
});

describe('EM-182 — Structure renders at its assigned lot (x,z), not an agent spot', () => {
  it('the outer group sits at exactly the (x,z) passed by the caller', () => {
    // CozyWorld derives (x,z) from building.location via assignBuildingLots
    // (the authoritative EM-182 keying test lives in cityLayout.test.ts). The
    // renderer must HONOR that lot — never re-derive it from an agent — so a
    // building proposed for a district it isn't standing in lands in that
    // district. Here we pass an explicit lot and assert the group adopts it.
    const lotX = 7.25;
    const lotZ = -3.5;
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    let container: HTMLElement;
    try {
      ({ container } = render(
        <Structure building={building({ location: 'market' })} x={lotX} z={lotZ} />,
      ));
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    }
    const groups = Array.from(container.querySelectorAll('group'));
    const placed = groups.some((g) => {
      const pos = g.getAttribute('position');
      if (!pos) return false;
      const [x, , z] = pos.split(',').map(Number);
      return Math.abs(x - lotX) < 1e-9 && Math.abs(z - lotZ) < 1e-9;
    });
    expect(placed).toBe(true);
  });
});
