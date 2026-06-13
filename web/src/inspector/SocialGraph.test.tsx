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

const { pauseSpy, lastGraphProps } = vi.hoisted(() => ({
  pauseSpy: vi.fn(),
  lastGraphProps: { current: null as Record<string, unknown> | null },
}));

// Stub the heavy canvas/d3 graph lib with a ref-compatible shell that mirrors
// the real ref lifecycle (react-kapsule also uses useImperativeHandle, so the
// handle is detached at the same commit-phase moment as the real lib's).
// EM-196: the stub also mirrors the real lib's DOM — a <canvas> inside the
// wrapper — and records the props it was handed, so the mount test can assert
// the ready branch actually puts a canvas in the container and that the
// canvas-bound colors arrived resolved (never '').
vi.mock('react-force-graph-2d', () => ({
  default: forwardRef(function ForceGraphStub(props: Record<string, unknown>, ref) {
    lastGraphProps.current = props;
    useImperativeHandle(ref, () => ({
      pauseAnimation: pauseSpy,
      resumeAnimation: vi.fn(),
      d3ReheatSimulation: vi.fn(),
      zoomToFit: vi.fn(),
    }));
    return (
      <div data-testid="force-graph-stub">
        <canvas data-testid="force-graph-canvas" />
      </div>
    );
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
beforeEach(() => {
  pauseSpy.mockClear();
  lastGraphProps.current = null;
});

import SocialGraph, { resolveTokens } from './SocialGraph';

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

// ── EM-196: the white-box fix ─────────────────────────────────────────────────
// Root cause: `useResolvedTokens` read CSS vars via getComputedStyle; when a
// read returned '' (timing/route edge), backgroundColor='' was falsy, so
// force-graph's init guard (`if (state.backgroundColor)`) never painted the
// canvas background → transparent canvas over the OS-white page. The fix is a
// literal hex fallback on EVERY canvas-bound token read, mirroring the
// declared values in inspector-tokens.css / roster-tokens.css exactly.

describe('SocialGraph — canvas token fallbacks (EM-196)', () => {
  it('resolves to the literal token mirrors when getComputedStyle yields "" for every var', () => {
    const spy = vi
      .spyOn(window, 'getComputedStyle')
      .mockReturnValue({ getPropertyValue: () => '' } as unknown as CSSStyleDeclaration);
    try {
      expect(resolveTokens()).toEqual({
        bg: '#0a0a0b', //          --lab-bg                 (inspector-tokens.css)
        text: '#e8e8f0', //        --lab-text               (inspector-tokens.css)
        dim: '#3a3a50', //         --lab-dim                (inspector-tokens.css)
        acid: '#c8ff00', //        --lab-acid               (inspector-tokens.css)
        danger: '#ff3333', //      --marker-crime           (inspector-tokens.css)
        edgeFlat: '#5a5a72', //    --lab-muted              (inspector-tokens.css)
        nodeNeutral: '#5a5a72', // --inspector-node-neutral (inspector-tokens.css)
        relPartner: '#ff6fa5', //  --rel-partner            (roster-tokens.css)
        relFamily: '#ffb347', //   --rel-family             (roster-tokens.css)
        relMentor: '#4cc9f0', //   --rel-mentor             (roster-tokens.css)
        relFeud: '#a31621', //     --rel-feud               (roster-tokens.css)
        faction: '#2ee6a8', //     --faction-tint           (inspector-tokens.css)
      });
    } finally {
      spy.mockRestore();
    }
  });

  it('prefers the declared var when it DOES resolve (fallback is a backstop, not an override)', () => {
    const spy = vi
      .spyOn(window, 'getComputedStyle')
      .mockReturnValue({
        getPropertyValue: (name: string) => (name === '--lab-bg' ? ' #123456 ' : ''),
      } as unknown as CSSStyleDeclaration);
    try {
      const tokens = resolveTokens();
      expect(tokens.bg).toBe('#123456'); // trimmed, from the var
      expect(tokens.acid).toBe('#c8ff00'); // unresolved → literal mirror
    } finally {
      spy.mockRestore();
    }
  });

  it('mounts a canvas in the graph container after the ready transition, with a non-empty backgroundColor', () => {
    const { container } = render(<SocialGraph {...PROPS} />);
    // ready (size measured + ≥2 nodes) → the graph branch renders, and its
    // surface holds an actual <canvas> element.
    expect(screen.getByTestId('force-graph-stub')).toBeInTheDocument();
    expect(container.querySelector('canvas')).not.toBeNull();
    // The canvas-bound background prop must NEVER be '' (the white-box bug):
    // jsdom resolves no declared vars, so this also proves the fallback path.
    expect(lastGraphProps.current?.backgroundColor).toBe('#0a0a0b');
  });
});
