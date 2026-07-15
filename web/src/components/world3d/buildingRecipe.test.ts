/**
 * buildingRecipe.test.ts — EM-299 (Wave Q) parametric mesh derivation.
 *
 * computeBuildingMesh is a PURE function: the geometry/colors are a deterministic
 * function of (recipe, idHash). These tests pin determinism (EM-155), sane params
 * across every footprint × roof × density, valid hex colors, floor clamping, and
 * the defensive fallbacks (a garbage enum never yields NaN geometry / a hole).
 */

import { describe, expect, it } from 'vitest';
import {
  computeBuildingMesh, mixHex, PLINTH_H, type BuildingRecipe,
} from './buildingRecipe';
import type {
  Footprint, Roof, BuildingMaterial, BuildingPalette, WindowDensity, Trim,
} from '../../types';

const FOOTPRINTS: Footprint[] = ['tiny', 'small', 'medium', 'large', 'grand'];
const ROOFS: Roof[] = ['flat', 'shed', 'gable', 'hip', 'dome', 'spire'];
const MATERIALS: BuildingMaterial[] =
  ['wood', 'timber_frame', 'brick', 'stone', 'marble', 'plaster', 'mud_brick'];
const PALETTES: BuildingPalette[] =
  ['warm', 'cool', 'earthy', 'pastel', 'vivid', 'muted', 'monochrome'];
const DENSITIES: WindowDensity[] = ['none', 'sparse', 'regular', 'dense'];
const TRIMS: Trim[] = ['none', 'simple', 'ornate', 'gilded'];

function recipe(over: Partial<BuildingRecipe> = {}): BuildingRecipe {
  return {
    footprint: 'medium', floors: 2, roof: 'gable', material: 'wood',
    palette: 'earthy', window_density: 'regular', trim: 'simple', ...over,
  };
}

const HEX = /^#[0-9a-f]{6}$/;

function everyFinite(nums: number[]): boolean {
  return nums.every((n) => Number.isFinite(n));
}

describe('computeBuildingMesh — determinism (EM-155)', () => {
  it('same recipe + same idHash ⇒ deep-identical params', () => {
    const r = recipe({ footprint: 'grand', floors: 5, roof: 'dome' });
    expect(computeBuildingMesh(r, 0.42)).toEqual(computeBuildingMesh(r, 0.42));
  });

  it('idHash varies ONLY cosmetic depth — width/floors/roof are stable', () => {
    const r = recipe({ footprint: 'large', floors: 3, roof: 'hip' });
    const a = computeBuildingMesh(r, 0.1);
    const b = computeBuildingMesh(r, 0.9);
    expect(a.width).toBe(b.width);
    expect(a.floors).toBe(b.floors);
    expect(a.roof.kind).toBe(b.roof.kind);
    expect(a.depth).not.toBe(b.depth); // depth jitters within a bounded band
    expect(a.depth).toBeGreaterThan(a.width * 0.8);
    expect(a.depth).toBeLessThan(a.width);
  });
});

describe('computeBuildingMesh — sane params across the grammar', () => {
  it('footprint widths strictly increase tiny→grand', () => {
    const widths = FOOTPRINTS.map((f) => computeBuildingMesh(recipe({ footprint: f }), 0.5).width);
    for (let i = 1; i < widths.length; i++) expect(widths[i]).toBeGreaterThan(widths[i - 1]);
  });

  it('every footprint × roof yields finite, positive geometry', () => {
    for (const footprint of FOOTPRINTS) {
      for (const roof of ROOFS) {
        const m = computeBuildingMesh(recipe({ footprint, roof }), 0.33);
        expect(m.roof.kind).toBe(roof);
        expect(everyFinite([m.width, m.depth, m.bodyHeight, m.totalHeight,
          m.roof.height, m.roof.radius])).toBe(true);
        expect(m.width).toBeGreaterThan(0);
        expect(m.bodyHeight).toBeGreaterThan(0);
        expect(m.roof.height).toBeGreaterThan(0);
        // totalHeight clears body + roof + plinth
        expect(m.totalHeight).toBeGreaterThanOrEqual(m.bodyHeight + m.roof.height);
      }
    }
  });

  it('floors are clamped to [1,8] and drive bodyHeight monotonically', () => {
    expect(computeBuildingMesh(recipe({ floors: 0 }), 0.5).floors).toBe(1);
    expect(computeBuildingMesh(recipe({ floors: 99 }), 0.5).floors).toBe(8);
    expect(computeBuildingMesh(recipe({ floors: -3 }), 0.5).floors).toBe(1);
    const h1 = computeBuildingMesh(recipe({ floors: 1 }), 0.5).bodyHeight;
    const h8 = computeBuildingMesh(recipe({ floors: 8 }), 0.5).bodyHeight;
    expect(h8).toBeGreaterThan(h1);
  });
});

describe('computeBuildingMesh — windows', () => {
  it("density 'none' ⇒ zero windows", () => {
    expect(computeBuildingMesh(recipe({ window_density: 'none' }), 0.5).windows).toHaveLength(0);
  });

  it('window counts grow none ≤ sparse ≤ regular ≤ dense', () => {
    const counts = DENSITIES.map(
      (d) => computeBuildingMesh(recipe({ window_density: d, floors: 4, footprint: 'grand' }), 0.5)
        .windows.length,
    );
    for (let i = 1; i < counts.length; i++) expect(counts[i]).toBeGreaterThanOrEqual(counts[i - 1]);
    expect(counts[DENSITIES.indexOf('dense')]).toBeGreaterThan(0);
  });

  it('every window sits inside the footprint with finite coords', () => {
    const m = computeBuildingMesh(recipe({ window_density: 'dense', floors: 3 }), 0.5);
    for (const wnd of m.windows) {
      expect(everyFinite([wnd.x, wnd.y, wnd.z, wnd.w, wnd.h])).toBe(true);
      expect(Math.abs(wnd.x)).toBeLessThanOrEqual(m.width / 2);
      expect(wnd.y).toBeGreaterThanOrEqual(PLINTH_H);
      expect(wnd.y).toBeLessThanOrEqual(m.bodyHeight + PLINTH_H);
      expect(wnd.w).toBeGreaterThan(0);
      expect(wnd.h).toBeGreaterThan(0);
    }
  });
});

describe('computeBuildingMesh — colors', () => {
  it('body / roof / window / trim accent are all valid #rrggbb', () => {
    for (const material of MATERIALS) {
      for (const palette of PALETTES) {
        for (const trim of TRIMS) {
          const m = computeBuildingMesh(recipe({ material, palette, trim }), 0.5);
          expect(m.body).toMatch(HEX);
          expect(m.roofColor).toMatch(HEX);
          expect(m.windowColor).toMatch(HEX);
          expect(m.trim.accent).toMatch(HEX);
        }
      }
    }
  });

  it('trim tiers escalate: none has no bands, gilded has plinth+cornice+quoins', () => {
    expect(computeBuildingMesh(recipe({ trim: 'none' }), 0.5).trim)
      .toMatchObject({ plinth: false, cornice: false, quoins: false });
    expect(computeBuildingMesh(recipe({ trim: 'simple' }), 0.5).trim)
      .toMatchObject({ plinth: true, cornice: false, quoins: false });
    expect(computeBuildingMesh(recipe({ trim: 'ornate' }), 0.5).trim)
      .toMatchObject({ plinth: true, cornice: true, quoins: false });
    expect(computeBuildingMesh(recipe({ trim: 'gilded' }), 0.5).trim)
      .toMatchObject({ plinth: true, cornice: true, quoins: true });
  });
});

describe('computeBuildingMesh — defensive fallbacks (never a hole)', () => {
  it('garbage enum values fall back to grammar defaults, not NaN', () => {
    const junk = {
      footprint: 'huge', floors: 3, roof: 'banana', material: 'adamantium',
      palette: 'octarine', window_density: 'everywhere', trim: 'diamond',
    } as unknown as BuildingRecipe;
    const m = computeBuildingMesh(junk, 0.5);
    // footprint 'huge' → 'medium' width
    expect(m.width).toBe(computeBuildingMesh(recipe({ footprint: 'medium' }), 0.5).width);
    // roof 'banana' → 'gable'
    expect(m.roof.kind).toBe('gable');
    expect(everyFinite([m.width, m.depth, m.bodyHeight, m.totalHeight])).toBe(true);
    expect(m.body).toMatch(HEX);
  });

  it('a non-finite idHash is treated as 0 (still deterministic)', () => {
    const r = recipe();
    expect(computeBuildingMesh(r, NaN)).toEqual(computeBuildingMesh(r, 0));
  });
});

describe('mixHex', () => {
  it('t=0 is a, t=1 is b, t=0.5 blends', () => {
    expect(mixHex('#000000', '#ffffff', 0)).toBe('#000000');
    expect(mixHex('#000000', '#ffffff', 1)).toBe('#ffffff');
    expect(mixHex('#000000', '#ffffff', 0.5)).toMatch(HEX);
  });
});
