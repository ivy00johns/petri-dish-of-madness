/**
 * ModelBoundary.test.tsx — the EM-150 fallback invariant, failure half.
 * jsdom only (the boundary is generic React; no canvas needed): a child that
 * throws during render — exactly what drei's useGLTF does when a GLB 404s —
 * must pin the procedural fallback instead of unmounting the tree, and a
 * suspending child must show the fallback while "streaming".
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { ModelBoundary } from './ModelBoundary';

afterEach(cleanup);

function GlbThatFailed(): never {
  throw new Error('Could not load /models/nope.glb: Failed to fetch');
}

describe('ModelBoundary', () => {
  it('renders the child when nothing goes wrong', () => {
    render(
      <ModelBoundary fallback={<span>procedural</span>}>
        <span>glb</span>
      </ModelBoundary>,
    );
    expect(screen.getByText('glb')).toBeTruthy();
    expect(screen.queryByText('procedural')).toBeNull();
  });

  it('pins the procedural fallback when the child throws (404/network)', () => {
    // React logs caught boundary errors in dev; keep the test output clean.
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      render(
        <ModelBoundary fallback={<span>procedural</span>}>
          <GlbThatFailed />
        </ModelBoundary>,
      );
      // The tree did NOT unmount: the fallback stands in.
      expect(screen.getByText('procedural')).toBeTruthy();
      // …and the failure was reported once.
      expect(warnSpy).toHaveBeenCalled();
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    }
  });

  it('shows the fallback while the child suspends (GLB streaming)', () => {
    const never = new Promise(() => {});
    function GlbStillStreaming(): never {
      throw never; // suspend forever — the fallback must be visible
    }
    render(
      <ModelBoundary fallback={<span>procedural</span>}>
        <GlbStillStreaming />
      </ModelBoundary>,
    );
    expect(screen.getByText('procedural')).toBeTruthy();
  });
});
