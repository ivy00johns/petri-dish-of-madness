/**
 * PlazaBanner tests (Wave I / EM-213, I4).
 *
 * The civic banner over the plaza textures the PROMOTED image when its url is
 * resolved (from world.plaza_banner_ref → gallery url), and shows the
 * procedural civic-canvas fallback when unset — never a blank/erroring mesh
 * (EM-148). A 404 also falls back via ModelBoundary (not exercised here; jsdom
 * never loads bytes — useTexture is stubbed).
 *
 * drei is mocked: Billboard/Text pass through, useTexture returns a stub
 * texture. The textured path renders a JSX <meshToonMaterial map={...}> tag;
 * the fallback path renders the blank canvas via a material PROP + a "PLAZA
 * BANNER" label, so no such tag appears.
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import type { ReactNode } from 'react';

// Urls useTexture should THROW on (simulating a 404 the way drei's cache
// re-throws during render). A test marks a url failing, then supplies a fresh
// url that loads — exercising the keyed ModelBoundary remount (the regression:
// the boundary must NOT stay latched after one transient failure).
const failingUrls = new Set<string>();

vi.mock('@react-three/drei', () => ({
  Billboard: ({ children }: { children?: ReactNode }) => <>{children}</>,
  Text: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
  useTexture: (url: string) => {
    if (failingUrls.has(url)) throw new Error(`Could not load ${url}: 404`);
    return { __stubUrl: url, isTexture: true };
  },
}));

import { PlazaBanner } from './PlazaBanner';

afterEach(() => {
  cleanup();
  failingUrls.clear();
});

function renderBanner(props: Parameters<typeof PlazaBanner>[0]) {
  const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  try {
    return render(<PlazaBanner {...props} />);
  } finally {
    errSpy.mockRestore();
    warnSpy.mockRestore();
  }
}

describe('PlazaBanner (EM-213)', () => {
  it('textures the banner from the resolved promoted-image url', () => {
    const { container } = renderBanner({
      x: 4,
      z: -2,
      url: '/assets/images/img_0000000001.png',
    });
    // The textured canvas renders a JSX <meshToonMaterial map={...}> tag.
    expect(container.querySelector('meshToonMaterial')).not.toBeNull();
  });

  it('shows the procedural civic-canvas fallback when no image is promoted', () => {
    const { container } = renderBanner({ x: 4, z: -2, url: null });
    // Fallback: material is a PROP (toonMaterial), so no JSX material tag…
    expect(container.querySelector('meshToonMaterial')).toBeNull();
    // …but the banner plane DID render (never a hole) + the carved label.
    expect(container.querySelector('planeGeometry')).not.toBeNull();
    expect(container.textContent).toContain('PLAZA BANNER');
  });

  it('always renders the support posts + frame regardless of image state', () => {
    for (const url of ['/assets/images/img_000000000b.png', null]) {
      const { container } = renderBanner({ x: 0, z: 0, url });
      // two posts (cylinders) + the frame bar (box) are part of the frame.
      expect(container.querySelectorAll('cylinderGeometry').length).toBe(2);
      expect(container.querySelector('boxGeometry')).not.toBeNull();
      cleanup();
    }
  });

  // FINDING 5 regression: ModelBoundary latches `failed=true` with no reset, so
  // ONE transient texture 404 used to permanently kill the banner artwork. The
  // per-url key={url} remounts a FRESH boundary when a NEW promoted image
  // arrives, so the textured banner recovers instead of staying pinned to the
  // prior failure.
  it('recovers the textured banner after a 404 once a NEW promoted url arrives (keyed remount)', () => {
    const bad = '/assets/images/img_000000bad1.png';
    const good = '/assets/images/img_000000good.png';

    // 1) First promoted image 404s → boundary catches, procedural fallback.
    failingUrls.add(bad);
    const { container, rerender } = renderBanner({ x: 4, z: -2, url: bad });
    expect(container.querySelector('meshToonMaterial')).toBeNull();
    expect(container.textContent).toContain('PLAZA BANNER'); // never a hole

    // 2) A NEW (working) url is promoted. With the per-url key, this mounts a
    //    fresh ModelBoundary not pinned to the prior failure → texture renders.
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      rerender(<PlazaBanner x={4} z={-2} url={good} />);
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    }
    expect(container.querySelector('meshToonMaterial')).not.toBeNull();
  });
});
