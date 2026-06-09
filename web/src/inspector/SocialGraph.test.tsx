/**
 * SocialGraph unmount smoke (EM-043 / audit C5) — the cleanup-captured-ref
 * bug: `fgRef.current` captured at effect SETUP is undefined (the graph
 * mounts after), so `pauseAnimation()` never ran. The W9 fix reads the ref
 * INSIDE the cleanup.
 *
 * ── W10-QA-1 (found by this test, pinned with `it.fails`) ────────────────────
 * The fix is STILL a no-op on unmount: React detaches forwarded refs
 * (useImperativeHandle clears `ref.current` to null) in the mutation phase,
 * BEFORE passive useEffect cleanups run — verified empirically against
 * react@18.3.1 (a parent cleanup reading a child's imperative handle sees
 * null). So `fgRef.current?.pauseAnimation()` in SocialGraph.tsx:136-143
 * reads null at teardown and never calls pauseAnimation.
 *
 * MITIGATION (why severity is low): react-kapsule invokes the kapsule's
 * `_destructor` on unmount, and force-graph's `_destructor` itself calls
 * `pauseAnimation()` (force-graph.mjs:1354) — so the rAF loop does stop and
 * the battery goal holds. The app-level safety net is just dead code giving
 * false confidence. `it.fails` = strict xfail: this flips loudly when the
 * component pauses via a mechanism that actually fires (e.g. keeping the
 * instance in a layout-effect-captured local, or pausing on `ready` → false).
 */
import { describe, expect, it, beforeAll, afterAll, beforeEach, vi } from 'vitest';
import { forwardRef, useImperativeHandle } from 'react';
import { render, screen } from '@testing-library/react';
import { agent, profile } from '../test-utils/fixtures';

const { pauseSpy } = vi.hoisted(() => ({ pauseSpy: vi.fn() }));

// Stub the heavy canvas/d3 graph lib with a ref-compatible shell that mirrors
// the real ref lifecycle (react-kapsule also uses useImperativeHandle, so the
// handle is detached at the same commit-phase moment as the real lib's).
vi.mock('react-force-graph-2d', () => ({
  default: forwardRef(function ForceGraphStub(_props: object, ref) {
    useImperativeHandle(ref, () => ({
      pauseAnimation: pauseSpy,
      resumeAnimation: vi.fn(),
      d3ReheatSimulation: vi.fn(),
      zoomToFit: vi.fn(),
    }));
    return <div data-testid="force-graph-stub" />;
  }),
}));

// `ready` needs a measurable container (jsdom layouts everything at 0×0).
let restoreSize: (() => void) | null = null;
beforeAll(() => {
  const wDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
  const hDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 640 });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 480 });
  restoreSize = () => {
    if (wDesc) Object.defineProperty(HTMLElement.prototype, 'clientWidth', wDesc);
    if (hDesc) Object.defineProperty(HTMLElement.prototype, 'clientHeight', hDesc);
  };
});
afterAll(() => restoreSize?.());
beforeEach(() => pauseSpy.mockClear());

import SocialGraph from './SocialGraph';

const PROPS = {
  events: [],
  agents: [agent({ id: 'a1' }), agent({ id: 'a2', profile: 'model-b' })],
  profiles: [profile({ name: 'model-a' }), profile({ name: 'model-b' })],
  currentTick: 0,
  maxTick: 0,
};

describe('SocialGraph — pause-on-unmount (audit C5)', () => {
  it('mounts the force graph once the container is measurable and ≥2 nodes exist', () => {
    render(<SocialGraph {...PROPS} />);
    expect(screen.getByTestId('force-graph-stub')).toBeInTheDocument();
  });

  // Strict xfail pin for W10-QA-1 (see the header comment): the desired
  // behavior — pauseAnimation called via the component's own cleanup — does
  // NOT happen, because React nulls the forwarded ref before the passive
  // cleanup runs. When someone fixes the cleanup mechanism, this test starts
  // passing, `it.fails` turns RED, and the pin should become a plain `it`.
  it.fails('calls pauseAnimation from its own cleanup at unmount (W10-QA-1 xfail pin)', () => {
    const { unmount } = render(<SocialGraph {...PROPS} />);
    expect(screen.getByTestId('force-graph-stub')).toBeInTheDocument();
    unmount();
    expect(pauseSpy).toHaveBeenCalledTimes(1);
  });
});
