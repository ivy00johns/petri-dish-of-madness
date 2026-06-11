/**
 * Building tests — the Wave D1.6 landmark-label legibility law.
 *
 * Root cause of the D1.5 regression: place labels were gated by the EM-102
 * proximity hook (PLACE_LABEL_DIST = 32) while the retuned default camera
 * framing sits ~89u out — so at city framing every landmark collapsed to a
 * MiniMarker dot and the world lost its names. The fix: landmark labels are
 * ALWAYS on, distance-SCALED (readable at the default framing) and
 * distance-FADED toward the zoom-out limit. The scale/fade law is the pure
 * function under test here; agent-built Structure labels keep the tight gate.
 */

import { describe, expect, it, vi } from 'vitest';

// Building.tsx imports the GLB pipeline — keep jsdom out of loader land.
vi.mock('./assets/Model', () => ({
  Model: () => null,
  useToonGLTF: () => ({ scene: null, animations: [] }),
}));

import {
  landmarkLabelTransform,
  LANDMARK_LABEL_REF_DIST,
  LANDMARK_LABEL_MAX_SCALE,
  LANDMARK_FADE_START,
  LANDMARK_FADE_END,
  LANDMARK_MIN_OPACITY,
} from './Building';

/** The default CozyWorld framing: camera (54, 46, 54) → target ≈ origin. */
const DEFAULT_FRAMING_DIST = Math.hypot(54, 44.5, 54); // ≈ 88.6

describe('landmarkLabelTransform (Wave D1.6 legibility law)', () => {
  it('renders at natural scale and full ink when the camera is close', () => {
    for (const d of [5, 14, LANDMARK_LABEL_REF_DIST]) {
      const { scale, fade } = landmarkLabelTransform(d);
      expect(scale, `d=${d}`).toBe(1);
      expect(fade, `d=${d}`).toBe(1);
    }
  });

  it('is readable at the DEFAULT camera framing (~89u): max scale, full ink', () => {
    const { scale, fade } = landmarkLabelTransform(DEFAULT_FRAMING_DIST);
    expect(scale).toBeCloseTo(LANDMARK_LABEL_MAX_SCALE, 2);
    expect(scale).toBeGreaterThan(2); // genuinely enlarged, not a token bump
    expect(fade).toBeGreaterThan(0.9); // fade must not undercut the default view
  });

  it('scales monotonically with distance up to the cap', () => {
    let prev = 0;
    for (const d of [10, 30, 40, 60, 90, 130, 200]) {
      const { scale } = landmarkLabelTransform(d);
      expect(scale, `d=${d}`).toBeGreaterThanOrEqual(prev);
      expect(scale, `d=${d}`).toBeLessThanOrEqual(LANDMARK_LABEL_MAX_SCALE);
      prev = scale;
    }
  });

  it('fades with distance past the fade window, never below the floor', () => {
    const near = landmarkLabelTransform(LANDMARK_FADE_START).fade;
    const mid = landmarkLabelTransform((LANDMARK_FADE_START + LANDMARK_FADE_END) / 2).fade;
    const far = landmarkLabelTransform(LANDMARK_FADE_END + 100).fade;
    expect(near).toBe(1);
    expect(mid).toBeLessThan(near);
    expect(mid).toBeGreaterThan(far - 1e-9);
    expect(far).toBe(LANDMARK_MIN_OPACITY);
    expect(far).toBeGreaterThan(0); // distance-faded, never gone — it's a landmark
  });

  it('the zoom-out LIMIT (maxDistance 130) still shows legible labels', () => {
    const { scale, fade } = landmarkLabelTransform(130);
    expect(scale).toBe(LANDMARK_LABEL_MAX_SCALE);
    expect(fade).toBeGreaterThanOrEqual(LANDMARK_MIN_OPACITY);
  });
});
