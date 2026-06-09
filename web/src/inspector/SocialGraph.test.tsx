/**
 * SocialGraph unmount smoke (EM-043 / audit C5) — the cleanup-captured-ref
 * bug: `fgRef.current` captured at effect SETUP is undefined (the graph
 * mounts after), so `pauseAnimation()` never ran. The W9 fix reads the ref
 * INSIDE the cleanup.
 *
 * ── W10-QA-1 → FIXED in W11a (EM-097) ────────────────────────────────────────
 * History: the W9 read-inside-cleanup "fix" was a no-op — React detaches
 * forwarded refs (useImperativeHandle clears `ref.current` to null) in the
 * commit mutation phase, BEFORE passive useEffect cleanups run, so the
 * teardown read always saw null. That dead path was pinned here with a strict
 * `it.fails` xfail through W10.
 *
 * W11a's EM-097 fix is a CAPTURED-INSTANCE cleanup keyed on `ready`
 * (SocialGraph.tsx): when `ready` flips true the graph mounts in the same
 * commit and its ref is attached before passive effects fire, so the effect
 * captures the real instance into a closure-held local — which survives
 * React's ref detach — and the cleanup's `fg?.pauseAnimation()` actually
 * runs at unmount (and whenever `ready` drops). The xfail pin flipped RED on
 * that commit, exactly as designed, and is now a plain passing `it`.
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

  // W10-QA-1, fixed by W11a EM-097 (captured-instance cleanup keyed on
  // `ready` — see the header comment). Formerly a strict `it.fails` xfail pin;
  // it flipped RED when the fix landed and is now the real regression test:
  // the component's OWN cleanup must call pauseAnimation exactly once.
  it('calls pauseAnimation from its own cleanup at unmount (W10-QA-1, fixed by EM-097)', () => {
    const { unmount } = render(<SocialGraph {...PROPS} />);
    expect(screen.getByTestId('force-graph-stub')).toBeInTheDocument();
    unmount();
    expect(pauseSpy).toHaveBeenCalledTimes(1);
  });
});
