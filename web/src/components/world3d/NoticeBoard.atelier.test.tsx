/**
 * NoticeBoard atelier-texture tests (Wave I / EM-211, I1).
 *
 * The blank front paper-plane note becomes the NEWEST gallery image (textured)
 * when one exists, and stays the procedural flat-PAPER fallback otherwise — the
 * EM-148 invariant: the board is never a blank/erroring mesh.
 *
 * drei is WebGL/troika; mocked to plain stubs (Billboard/RoundedBox/Text pass
 * children through, useCursor is a no-op, useTexture returns a stub texture
 * carrying the requested url so we can assert WHICH url got textured). The
 * textured path renders a JSX <meshToonMaterial map={...}> (a `meshtoonmaterial`
 * DOM tag in jsdom); the procedural path passes the material as a PROP
 * (toonMaterial(...)) so no such tag appears — that asymmetry is the assertion.
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import type { ReactNode } from 'react';

// A set of urls useTexture should THROW on (simulating a 404 the way drei's
// useTexture/useGLTF cache re-throws during render). Tests mutate it to make a
// specific url fail, then supply a fresh url that loads — exercising the keyed
// ModelBoundary remount (the regression: the boundary must NOT stay latched).
const failingUrls = new Set<string>();

vi.mock('@react-three/drei', () => ({
  Billboard: ({ children }: { children?: ReactNode }) => <>{children}</>,
  RoundedBox: ({ children }: { children?: ReactNode }) => <>{children}</>,
  Text: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
  useCursor: () => {},
  // Return a queryable stub so the textured mesh records the url it loaded —
  // unless the url is marked failing, in which case THROW like a 404 does.
  useTexture: (url: string) => {
    if (failingUrls.has(url)) throw new Error(`Could not load ${url}: 404`);
    return { __stubUrl: url, isTexture: true };
  },
}));

// useProximity needs the R3F frame loop; pin it near so the full label renders.
vi.mock('./useProximity', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useProximity')>();
  return { ...actual, useProximity: () => true };
});

import { NoticeBoard, type NoticeBoardPost } from './NoticeBoard';

afterEach(() => {
  cleanup();
  failingUrls.clear();
});

const POST: NoticeBoardPost = { text: 'A note', author: 'Ada', god: false };

/** react-dom warns on R3F intrinsic tags in jsdom; silence for the smoke. */
function renderBoard(props: Parameters<typeof NoticeBoard>[0]) {
  const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
  const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  try {
    return render(<NoticeBoard {...props} />);
  } finally {
    errSpy.mockRestore();
    warnSpy.mockRestore();
  }
}

describe('NoticeBoard atelier texture (EM-211)', () => {
  it('textures the front note with the newest gallery image when one exists', () => {
    const { container } = renderBoard({
      x: 0,
      z: 0,
      newest: POST,
      imageUrl: '/assets/images/img_0000000001.png',
    });
    // The textured path renders a JSX <meshToonMaterial map={...}> tag.
    const mat = container.querySelector('meshToonMaterial');
    expect(mat).not.toBeNull();
  });

  it('falls back to the procedural PAPER note when there is no image', () => {
    const { container } = renderBoard({
      x: 0,
      z: 0,
      newest: POST,
      imageUrl: null,
    });
    // Procedural path: the material is a PROP (toonMaterial), not a JSX tag.
    expect(container.querySelector('meshToonMaterial')).toBeNull();
    // …but the note plane still renders (never a hole): planeGeometry present.
    expect(container.querySelector('planeGeometry')).not.toBeNull();
  });

  it('still renders (no crash) on a bare board with an image (no newest post)', () => {
    const { container } = renderBoard({
      x: 0,
      z: 0,
      newest: null,
      imageUrl: '/assets/images/img_000000000a.png',
    });
    expect(container.querySelector('meshToonMaterial')).not.toBeNull();
  });

  // FINDING 5 regression: ModelBoundary latches `failed=true` with no reset, so
  // ONE transient texture 404 used to permanently kill the artwork. The per-url
  // key={imageUrl} remounts a FRESH boundary when a NEW image arrives, so the
  // textured plane recovers instead of staying pinned to the prior failure.
  it('recovers the textured note after a 404 once a NEW image url arrives (keyed remount)', () => {
    const bad = '/assets/images/img_000000bad1.png';
    const good = '/assets/images/img_000000good.png';

    // 1) First image 404s → boundary catches, procedural fallback (no texture).
    failingUrls.add(bad);
    const { container, rerender } = renderBoard({ x: 0, z: 0, newest: POST, imageUrl: bad });
    expect(container.querySelector('meshToonMaterial')).toBeNull();
    expect(container.querySelector('planeGeometry')).not.toBeNull(); // never a hole

    // 2) A NEW (working) url arrives. With the per-url key, this mounts a fresh
    //    ModelBoundary not pinned to the prior failure → the texture renders.
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    try {
      rerender(<NoticeBoard x={0} z={0} newest={POST} imageUrl={good} />);
    } finally {
      errSpy.mockRestore();
      warnSpy.mockRestore();
    }
    expect(container.querySelector('meshToonMaterial')).not.toBeNull();
  });
});
