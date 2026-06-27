/**
 * Structure.fund.test.tsx — EM-180 funds-as-marker render-path gate.
 *
 * A "fund" (a shared treasury / commons pool — detected by
 * structureModel.isFundBuilding on a name/kind keyword) is an ACCOUNT, not a
 * structure. So when a W7 Building is a fund, Structure must render the small
 * on-lot treasury MARKER (the FundStructure chest), NOT the full operational
 * building shell — even though the same building, if it weren't a fund, would
 * stream a GLB. A non-fund building keeps the normal shell (and its GLB).
 *
 * The render-path tell is the GLB <Model> mount: the shell path mounts it (for
 * a kind with a registry GLB, e.g. 'house'); the marker path NEVER mounts it.
 * The marker also carries its own distinctive chest geometry (a RoundedBox lid
 * + a gold-pot box) that the shell path doesn't.
 *
 * jsdom harness mirrors Structure.skin.test.tsx: <Model> + R3F frame loop +
 * proximity/cursor are mocked so nothing touches WebGL.
 */

import type { ReactNode } from 'react';
import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import type { Building } from '../../types';
import { isFundBuilding } from './structureModel';

// Capture every <Model> mount so we can prove the shell path streams a GLB and
// the marker path does not.
const modelMounts: Array<{ url?: string }> = [];

vi.mock('./assets/Model', () => ({
  Model: (props: { spec?: { url: string } }) => {
    modelMounts.push({ url: props.spec?.url });
    return <modelStub />;
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
// outside a Canvas). The structure body / marker + <Model> mount regardless.
vi.mock('./useProximity', () => ({
  useProximity: () => false,
  PLACE_LABEL_DIST: 32,
}));
// drei components build real BufferGeometries and run useLayoutEffects against
// the (absent) R3F camera/renderer in jsdom: <Billboard> hits
// `h.current.center`, and <RoundedBox> builds an extrude geometry that calls
// `.center()` on its generated geometry. Stub them inert. <RoundedBox> still
// emits a real <boxGeometry args=[...]> intrinsic so the treasury chest
// dimensions (the thing this test asserts on) remain inspectable in the DOM —
// the rounding is cosmetic, the args carry the size.
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

function building(overrides: Partial<Building>): Building {
  return {
    id: 'b1',
    name: 'Test',
    // 'house' has a real GLB in MODEL_REGISTRY → the shell path WOULD stream a
    // Model. The fund path must suppress that even with this kind.
    kind: 'house',
    location: 'plaza',
    owner_id: 'ada',
    status: 'operational',
    health: 100,
    condition_label: 'pristine',
    progress: 100,
    funds_committed: 5,
    funds_required: 10,
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

/**
 * Find a boxGeometry whose args satisfy `pred`. Both RoundedBox (stubbed to a
 * <boxGeometry>) and raw <boxGeometry> meshes surface here; the treasury chest
 * body's args [1.3, 0.6, 0.9] are unique to FundStructure, so an exact-dim
 * predicate identifies the chest specifically.
 */
function hasBoxArgs(container: HTMLElement, pred: (args: number[]) => boolean): boolean {
  return Array.from(container.querySelectorAll('boxGeometry')).some((g) => {
    const raw = g.getAttribute('args');
    if (!raw) return false;
    // R3F serializes an array prop to its comma-joined scalars.
    const nums = raw.split(',').map(Number);
    return pred(nums);
  });
}

/**
 * Read the onClick handler React attached to an R3F jsdom element. R3F's jsdom
 * reconciler stores element props under a `__reactProps$<id>` key (there is no
 * `__r3f.handlers` surface here), so we pull onClick off that bag.
 */
function reactOnClick(el: Element): ((e: { stopPropagation: () => void }) => void) | undefined {
  const key = Object.keys(el).find((k) => k.startsWith('__reactProps$'));
  if (!key) return undefined;
  const props = (el as unknown as Record<string, { onClick?: (e: { stopPropagation: () => void }) => void }>)[key];
  return props?.onClick;
}

beforeEach(() => {
  modelMounts.length = 0;
});
afterEach(cleanup);

describe('EM-180 — funds render as a treasury MARKER, not a building shell', () => {
  it('a fund building takes the MARKER path: it mounts NO GLB Model', () => {
    // Sanity: this building IS a fund by the detector…
    const b = building({ name: 'Community Commons Fund', kind: 'commons' });
    expect(isFundBuilding(b)).toBe(true);

    renderStructure(b);

    // …so even though it's operational, no operational GLB streams — a
    // treasury is an account, rendered as the procedural chest marker.
    expect(modelMounts.find((m) => m.url)).toBeUndefined();
  });

  it('a fund building renders the distinctive treasury CHEST geometry', () => {
    const { container } = renderStructure(
      building({ name: 'Relief Treasury', kind: 'building' }),
    );
    // The FundStructure chest body is a RoundedBox of args [1.3, 0.6, 0.9] —
    // a low, wide coffer no operational shell uses.
    const hasChest = hasBoxArgs(
      container,
      ([w, h, d]) => w === 1.3 && h === 0.6 && d === 0.9,
    );
    expect(hasChest, 'expected the treasury chest RoundedBox').toBe(true);
  });

  it('a fund building keeps click-to-focus (onPick fires with its id)', () => {
    const onPick = vi.fn();
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    let container: HTMLElement;
    try {
      ({ container } = render(
        <Structure
          building={building({ id: 'fund-7', name: 'The Coffers', kind: 'building' })}
          x={0}
          z={0}
          onPick={onPick}
        />,
      ));
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    }
    // The marker path is the SAME outer <group> as the shell path — onClick is
    // wired on it, NOT pushed down into FundStructure — so click-to-focus is
    // preserved. R3F's jsdom reconciler keeps element handlers in React props;
    // read onClick off the outer group's fiber props and invoke it.
    const group = container.querySelector('group');
    expect(group).toBeTruthy();
    const onClick = reactOnClick(group!);
    expect(onClick, 'fund marker outer group must carry onClick').toBeTypeOf('function');
    onClick!({ stopPropagation: () => {} });
    expect(onPick).toHaveBeenCalledWith('fund-7');
  });
});

describe('EM-180 — non-fund buildings keep the normal building shell', () => {
  it('a normal operational building takes the SHELL path: it mounts its GLB', () => {
    const b = building({ name: "Ada's Cottage", kind: 'house', status: 'operational' });
    expect(isFundBuilding(b)).toBe(false);

    renderStructure(b);

    // The operational shell streams the registry GLB for 'house'.
    expect(modelMounts.find((m) => m.url), 'expected the operational GLB to mount').toBeTruthy();
  });

  it('a normal building does NOT render the treasury chest geometry', () => {
    const { container } = renderStructure(
      building({ name: 'Village Clock Tower', kind: 'clocktower' }),
    );
    const hasChest = hasBoxArgs(
      container,
      ([w, h, d]) => w === 1.3 && h === 0.6 && d === 0.9,
    );
    expect(hasChest).toBe(false);
  });
});
