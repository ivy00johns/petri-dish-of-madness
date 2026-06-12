/**
 * StreetLabels tests (EM-188) — the street-name label render law:
 *   • gate REUSE: STREET_LABEL_DIST is the existing EM-102 PLACE_LABEL_DIST
 *     (no new gating system), and the default camera framing (~89u) sits
 *     beyond it ⇒ zero street labels at default zoom
 *   • flat-on-road orientation (pure rotation law per axis) — painted street
 *     names can never collide with the floating Billboard labels
 *   • sparse wiring: only MAIN streets' mid-block anchors render (the outer
 *     ring road never gets a label), one label per anchor
 *   • proximity wiring: far from every anchor ⇒ nothing renders
 *
 * drei's <Text> is troika (WebGL) — mocked to a plain span; useProximity is
 * mocked to a switchable gate (its real per-frame math needs the R3F loop).
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import type { ReactNode } from 'react';

const gate = { near: true };

vi.mock('./useProximity', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./useProximity')>();
  return { ...actual, useProximity: () => gate.near };
});

vi.mock('@react-three/drei', () => ({
  Text: ({ children }: { children?: ReactNode }) => (
    <span data-testid="street-name">{children}</span>
  ),
}));

import {
  StreetLabels,
  STREET_LABEL_DIST,
  STREET_LABEL_Y,
  streetLabelRotation,
} from './StreetLabels';
import { computeStreets } from './cityLayout';
import { PLACE_LABEL_DIST } from './useProximity';

afterEach(() => {
  cleanup();
  gate.near = true;
});

/** The default CozyWorld framing: camera (54, 46, 54) → target ≈ origin. */
const DEFAULT_FRAMING_DIST = Math.hypot(54, 46, 54); // ≈ 89

describe('EM-188 — street-label gating law (pure parts)', () => {
  it('reuses the EM-102 place-label threshold — no new gating system', () => {
    expect(STREET_LABEL_DIST).toBe(PLACE_LABEL_DIST);
  });

  it('the default zoom sits beyond the gate ⇒ no street-label clutter', () => {
    expect(DEFAULT_FRAMING_DIST).toBeGreaterThan(STREET_LABEL_DIST);
  });

  it('labels lie flat on the road, below any floating billboard label', () => {
    // painted-on-road: a hair above the road tiles, nowhere near the ≥1.7u
    // billboard plates of Building/Structure labels — collision-free by plane
    expect(STREET_LABEL_Y).toBeGreaterThan(0);
    expect(STREET_LABEL_Y).toBeLessThan(0.5);
  });

  it('flat-on-ground rotation per axis (Rx lays it down; ns adds the in-plane quarter turn)', () => {
    expect(streetLabelRotation('ew')).toEqual([-Math.PI / 2, 0, 0]);
    expect(streetLabelRotation('ns')).toEqual([-Math.PI / 2, 0, Math.PI / 2]);
  });
});

describe('EM-188 — street-label rendering (sparse + gated)', () => {
  const streets = computeStreets(1337);
  const mains = streets.filter((s) => s.main);
  const ring = streets.filter((s) => !s.main);

  it('near ⇒ renders one label per MAIN-street anchor, with the seeded name', () => {
    gate.near = true;
    const { getAllByTestId, queryByText } = render(<StreetLabels streets={streets} />);
    const rendered = getAllByTestId('street-name');
    const expected = mains.reduce((n, s) => n + s.labels.length, 0);
    expect(expected).toBe(8 * 3); // 8 interior avenues × 3 mid-block anchors
    expect(rendered).toHaveLength(expected);
    for (const s of mains) {
      expect(
        rendered.filter((el) => el.textContent === s.name),
        s.id,
      ).toHaveLength(s.labels.length);
    }
    // the outer ring road is NEVER labeled (sparse law)
    for (const s of ring) {
      expect(queryByText(s.name), s.id).toBeNull();
    }
  });

  it('far from every anchor ⇒ renders nothing (default-zoom behavior)', () => {
    gate.near = false;
    const { queryAllByTestId } = render(<StreetLabels streets={streets} />);
    expect(queryAllByTestId('street-name')).toHaveLength(0);
  });
});
