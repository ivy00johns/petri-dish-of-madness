/**
 * Structure.em192.test.tsx — EM-192 frontend follow-ups.
 *
 *   (a) `town_name?: string | null` is typed on WorldState (additive) so reads
 *       stop using a defensive cast — a compile-level + structural assertion.
 *   (b) The building/structure LABEL inks reference the sanctioned toon.ts
 *       LABEL_INK / LABEL_OUTLINE constants, NOT raw hex literals — proven by
 *       capturing the rendered <Text> props.
 *   (c) The proximity-gated label FADES rather than hard-cuts: the pure
 *       distance→opacity law `structureLabelFade` maps in-range → 1 and ramps
 *       linearly to 0 across the fade band past PLACE_LABEL_DIST.
 *
 * jsdom harness mirrors Structure.skin/fund.test.tsx: <Model>, the R3F frame
 * loop, proximity and cursor are mocked so nothing touches WebGL. <Text> is
 * mocked to a prop-recording stub so the label inks are inspectable.
 */

import type { ReactNode } from 'react';
import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import type { Building, WorldState } from '../../types';
import {
  structureLabelFade,
  PLACE_LABEL_DIST,
  STRUCTURE_LABEL_FADE_BAND,
} from './useProximity';
import { LABEL_INK, LABEL_OUTLINE } from './toon';

// ── (c) fade law — a pure function, no harness needed ────────────────────────

describe('EM-192(c) — structureLabelFade: far labels fade rather than hard-cut', () => {
  it('is fully solid (1) at and inside PLACE_LABEL_DIST', () => {
    expect(structureLabelFade(0)).toBe(1);
    expect(structureLabelFade(PLACE_LABEL_DIST - 5)).toBe(1);
    expect(structureLabelFade(PLACE_LABEL_DIST)).toBe(1);
  });

  it('ramps LINEARLY from 1 → 0 across the fade band past the cutoff', () => {
    // halfway through the band ⇒ exactly half opacity.
    const mid = PLACE_LABEL_DIST + STRUCTURE_LABEL_FADE_BAND / 2;
    expect(structureLabelFade(mid)).toBeCloseTo(0.5, 6);
    // a quarter in ⇒ 0.75.
    const quarter = PLACE_LABEL_DIST + STRUCTURE_LABEL_FADE_BAND / 4;
    expect(structureLabelFade(quarter)).toBeCloseTo(0.75, 6);
  });

  it('decreases monotonically across the fade band (a real fade, not a step)', () => {
    let prev = Infinity;
    for (let d = PLACE_LABEL_DIST; d <= PLACE_LABEL_DIST + STRUCTURE_LABEL_FADE_BAND; d += 1) {
      const f = structureLabelFade(d);
      expect(f).toBeLessThanOrEqual(prev + 1e-9);
      prev = f;
    }
  });

  it('reaches 0 at the end of the band and clamps to 0 well past it', () => {
    expect(structureLabelFade(PLACE_LABEL_DIST + STRUCTURE_LABEL_FADE_BAND)).toBeCloseTo(0, 6);
    expect(structureLabelFade(PLACE_LABEL_DIST + STRUCTURE_LABEL_FADE_BAND + 100)).toBe(0);
  });

  it('stays clamped in [0,1] for every distance', () => {
    for (const d of [-50, 0, 10, 33, 50, 1000]) {
      const f = structureLabelFade(d);
      expect(f).toBeGreaterThanOrEqual(0);
      expect(f).toBeLessThanOrEqual(1);
    }
  });

  it('honors explicit dist/band overrides (the law is parameterized)', () => {
    expect(structureLabelFade(40, 40, 10)).toBe(1);
    expect(structureLabelFade(45, 40, 10)).toBeCloseTo(0.5, 6);
    expect(structureLabelFade(50, 40, 10)).toBeCloseTo(0, 6);
    // a zero/negative band degenerates to a hard cut at the cutoff.
    expect(structureLabelFade(41, 40, 0)).toBe(0);
  });
});

// ── (a) town_name typed on WorldState (additive) ─────────────────────────────

describe('EM-192(a) — town_name is typed on WorldState', () => {
  it('accepts a string town_name without a cast', () => {
    const ws: WorldState = {
      type: 'world_state',
      seq: 1,
      tick: 0,
      day: 0,
      running: false,
      tick_interval_seconds: 1,
      places: [],
      agents: [],
      rules: [],
      profiles: [],
      town_name: 'Madfield',
    };
    // Read it straight off the typed field — no `as { town_name }` cast.
    expect(ws.town_name).toBe('Madfield');
  });

  it('stays additive: null and absent town_name are both valid', () => {
    const nulled: WorldState = {
      type: 'world_state',
      seq: 1,
      tick: 0,
      day: 0,
      running: false,
      tick_interval_seconds: 1,
      places: [],
      agents: [],
      rules: [],
      profiles: [],
      town_name: null,
    };
    const absent: WorldState = {
      type: 'world_state',
      seq: 1,
      tick: 0,
      day: 0,
      running: false,
      tick_interval_seconds: 1,
      places: [],
      agents: [],
      rules: [],
      profiles: [],
    };
    expect(nulled.town_name).toBeNull();
    expect(absent.town_name).toBeUndefined();
  });
});

// ── (b) label inks reference the toon constants, not raw hex ──────────────────
//
// Capture every <Text> mount's color/outlineColor so we can prove the label
// renders with LABEL_INK / LABEL_OUTLINE rather than a sprinkled '#fff3e0' /
// '#241b14'.

const textMounts: Array<{ color?: string; outlineColor?: string; child?: ReactNode }> = [];

vi.mock('./assets/Model', () => ({
  Model: () => <modelStub />,
  useToonGLTF: () => ({ scene: null, animations: [] }),
}));
vi.mock('@react-three/fiber', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('@react-three/fiber');
  return { ...actual, useFrame: () => {} };
});
// Camera is NEAR so the full <StructureLabel> renders (not the MiniMarker).
vi.mock('./useProximity', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('./useProximity');
  return { ...actual, useProximity: () => true };
});
vi.mock('@react-three/drei', () => ({
  useCursor: () => {},
  Billboard: ({ children }: { children?: ReactNode }) => <group>{children}</group>,
  Text: (props: { color?: string; outlineColor?: string; children?: ReactNode }) => {
    textMounts.push({ color: props.color, outlineColor: props.outlineColor, child: props.children });
    // Reuse the whitelisted modelStub intrinsic (jsx-stubs.d.ts) so tsc -b
    // accepts the placeholder tag without a new test-infra declaration.
    return <modelStub>{props.children}</modelStub>;
  },
  RoundedBox: ({ children, ...rest }: { children?: ReactNode; [k: string]: unknown }) => (
    <mesh {...rest}>{children}</mesh>
  ),
}));

import { Structure } from './Structure';

function building(overrides: Partial<Building>): Building {
  return {
    id: 'b1',
    name: 'Town Library',
    kind: 'library',
    location: 'plaza',
    owner_id: 'ada',
    status: 'operational',
    health: 100,
    condition_label: 'pristine',
    progress: 100,
    funds_committed: 0,
    funds_required: 0,
    contributors: [],
    function: '+lore',
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
  textMounts.length = 0;
});
afterEach(cleanup);

describe('EM-192(b) — structure label inks use the toon LABEL constants', () => {
  it('the title Text renders with LABEL_INK color and LABEL_OUTLINE outline', () => {
    renderStructure(building({ name: 'Town Library' }));
    const title = textMounts.find((t) => t.child === 'Town Library');
    expect(title, 'title Text should have mounted').toBeTruthy();
    expect(title!.color).toBe(LABEL_INK);
    expect(title!.outlineColor).toBe(LABEL_OUTLINE);
  });

  it('every label Text outline uses LABEL_OUTLINE (no raw #241b14 sprinkled)', () => {
    renderStructure(building({ name: 'Town Library' }));
    expect(textMounts.length).toBeGreaterThanOrEqual(2); // title + subtitle
    for (const t of textMounts) {
      expect(t.outlineColor).toBe(LABEL_OUTLINE);
    }
    // the constants carry the sanctioned values (so the migration is a true
    // alias of the previous raw hex, not a silent color change).
    expect(LABEL_OUTLINE).toBe('#241b14');
    expect(LABEL_INK).toBe('#fff3e0');
  });
});
