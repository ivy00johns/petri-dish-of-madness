/**
 * toon.ts tests — EM-111 (warm toon golden hour). Headless: the gradient
 * builder and material factory construct THREE objects without ever touching
 * a WebGL context, so these run under plain jsdom.
 */

import { beforeEach, describe, expect, it } from 'vitest';
import * as THREE from 'three';
import {
  TOON_RAMP_FLOOR,
  TOON_RAMP_STEPS,
  clearToonCacheForTests,
  toonGradientMap,
  toonMaterial,
  toonMaterialCacheSize,
} from './toon';

beforeEach(() => {
  clearToonCacheForTests();
});

// ── Gradient ramp ────────────────────────────────────────────────────────────

describe('toonGradientMap', () => {
  it('builds a 1-row DataTexture with the default step count', () => {
    const tex = toonGradientMap();
    expect(tex).toBeInstanceOf(THREE.DataTexture);
    expect(tex.image.width).toBe(TOON_RAMP_STEPS);
    expect(tex.image.height).toBe(1);
  });

  it('honors an explicit step count (3-step ramp)', () => {
    const tex = toonGradientMap(3);
    expect(tex.image.width).toBe(3);
    expect((tex.image.data as Uint8Array).length).toBe(3 * 4);
  });

  it('uses NearestFilter for min+mag and no mipmaps (hard cel bands)', () => {
    const tex = toonGradientMap();
    expect(tex.minFilter).toBe(THREE.NearestFilter);
    expect(tex.magFilter).toBe(THREE.NearestFilter);
    expect(tex.generateMipmaps).toBe(false);
  });

  it('ramps monotonically from a warm floor (never black) to full white', () => {
    const data = toonGradientMap().image.data as Uint8Array;
    const levels: number[] = [];
    for (let i = 0; i < TOON_RAMP_STEPS; i++) levels.push(data[i * 4]);
    // floor band is warm, not black
    expect(levels[0]).toBeGreaterThanOrEqual(Math.floor(TOON_RAMP_FLOOR * 255));
    // strictly increasing bands, topping out at full brightness
    for (let i = 1; i < levels.length; i++) {
      expect(levels[i]).toBeGreaterThan(levels[i - 1]);
    }
    expect(levels[levels.length - 1]).toBe(255);
    // fully opaque alpha on every band
    for (let i = 0; i < TOON_RAMP_STEPS; i++) expect(data[i * 4 + 3]).toBe(255);
  });

  it('caches per step count (same steps → same texture instance)', () => {
    expect(toonGradientMap()).toBe(toonGradientMap());
    expect(toonGradientMap(3)).toBe(toonGradientMap(3));
    expect(toonGradientMap(3)).not.toBe(toonGradientMap(4));
  });
});

// ── Cached material factory ──────────────────────────────────────────────────

describe('toonMaterial cache identity', () => {
  it('returns the IDENTICAL instance for identical params', () => {
    expect(toonMaterial('#8fb85a')).toBe(toonMaterial('#8fb85a'));
    expect(
      toonMaterial('#ffd27f', { emissive: '#ffb347', emissiveIntensity: 0.8 }),
    ).toBe(toonMaterial('#ffd27f', { emissive: '#ffb347', emissiveIntensity: 0.8 }));
  });

  it('treats omitted opts and explicit defaults as the same tuple', () => {
    expect(toonMaterial('#c9a36b')).toBe(
      toonMaterial('#c9a36b', { emissiveIntensity: 1, transparent: false, opacity: 1 }),
    );
  });

  it('is case-insensitive on hex colors', () => {
    expect(toonMaterial('#8FB85A')).toBe(toonMaterial('#8fb85a'));
  });

  it('returns DISTINCT instances for distinct params', () => {
    const base = toonMaterial('#8fb85a');
    expect(toonMaterial('#6e9a3e')).not.toBe(base);
    expect(toonMaterial('#8fb85a', { emissive: '#ffb347' })).not.toBe(base);
    expect(toonMaterial('#8fb85a', { emissiveIntensity: 0.5 })).not.toBe(base);
    expect(toonMaterial('#8fb85a', { transparent: true, opacity: 0.4 })).not.toBe(base);
  });

  it('counts one cache entry per distinct tuple', () => {
    expect(toonMaterialCacheSize()).toBe(0);
    toonMaterial('#8fb85a');
    toonMaterial('#8fb85a'); // hit, not a new entry
    toonMaterial('#6e9a3e');
    expect(toonMaterialCacheSize()).toBe(2);
  });
});

describe('toonMaterial output', () => {
  it('returns a MeshToonMaterial wired to the shared gradient ramp', () => {
    const mat = toonMaterial('#8fb85a');
    expect(mat).toBeInstanceOf(THREE.MeshToonMaterial);
    expect(mat.gradientMap).toBe(toonGradientMap());
    expect(mat.color.getHexString()).toBe('8fb85a');
  });

  it('honors emissive params (glowing windows/lanterns keep their glow)', () => {
    const mat = toonMaterial('#ffd27f', { emissive: '#ffb347', emissiveIntensity: 0.8 });
    expect(mat.emissive.getHexString()).toBe('ffb347');
    expect(mat.emissiveIntensity).toBe(0.8);
  });

  it('defaults to no emissive glow', () => {
    const mat = toonMaterial('#7a5230');
    expect(mat.emissive.getHexString()).toBe('000000');
    expect(mat.emissiveIntensity).toBe(1);
  });

  it('honors transparency params (ghost villagers)', () => {
    const ghost = toonMaterial('#b0b0b0', { transparent: true, opacity: 0.4 });
    expect(ghost.transparent).toBe(true);
    expect(ghost.opacity).toBe(0.4);
    const solid = toonMaterial('#b0b0b0');
    expect(solid.transparent).toBe(false);
    expect(solid.opacity).toBe(1);
  });
});
