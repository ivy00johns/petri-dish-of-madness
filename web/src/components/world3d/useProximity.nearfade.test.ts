/**
 * nearLabelFade — the zoom-in label declutter law.
 *
 * Labels used to sit at full opacity all the way to the camera's closest zoom
 * (minDistance 14), so a deep zoom stacked a wall of world-space names over the
 * geometry. nearLabelFade fades them out on a deep zoom-in and is a no-op at the
 * default framing (~95u) and every zoom-out.
 */
import { describe, expect, it } from 'vitest';
import { nearLabelFade, NEAR_LABEL_FADE_GONE, NEAR_LABEL_FADE_FULL } from './useProximity';

describe('nearLabelFade — zoom-in declutter', () => {
  it('is 0 at/below the gone distance (labels cleared for a clean close-up)', () => {
    expect(nearLabelFade(NEAR_LABEL_FADE_GONE)).toBe(0);
    expect(nearLabelFade(14)).toBe(0); // camera minDistance — the deepest zoom clears labels
    expect(nearLabelFade(0)).toBe(0);
  });

  it('is 1 at/above the full distance (no near suppression at normal framing)', () => {
    expect(nearLabelFade(NEAR_LABEL_FADE_FULL)).toBe(1);
    expect(nearLabelFade(95)).toBe(1); // default framing — unaffected
    expect(nearLabelFade(130)).toBe(1); // camera maxDistance
  });

  it('ramps monotonically 0→1 across the near window', () => {
    const mid = (NEAR_LABEL_FADE_GONE + NEAR_LABEL_FADE_FULL) / 2;
    const v = nearLabelFade(mid);
    expect(v).toBeCloseTo(0.5, 5);
    expect(nearLabelFade(mid + 1)).toBeGreaterThan(v);
    expect(nearLabelFade(mid - 1)).toBeLessThan(v);
  });

  it('window sits inside the zoom range (clears by minDistance, full before default framing)', () => {
    expect(NEAR_LABEL_FADE_GONE).toBeGreaterThan(14); // ≥ minDistance ⇒ deepest zoom is fully cleared
    expect(NEAR_LABEL_FADE_FULL).toBeLessThan(95); // < default framing ⇒ normal view untouched
  });
});
