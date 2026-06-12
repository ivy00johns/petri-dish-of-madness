/**
 * toon.ts — the shared warm-toon material system (EM-111, art Direction 1:
 * "Warm Toon, Golden Hour", docs/ui-redesign/3D-WORLD-ART-DIRECTION.md §1).
 *
 * Exports:
 *   • toonGradientMap(steps)  — a tiny banded DataTexture used as the
 *     MeshToonMaterial gradient ramp (NearestFilter, no mipmaps → hard cel
 *     bands). The ramp floor is deliberately > 0 so shaded faces stay WARM,
 *     never black (the art doc's "warm shadows" rule).
 *   • toonMaterial(color, opts) — a CACHED MeshToonMaterial factory keyed by
 *     the full param tuple: identical params return the IDENTICAL instance, so
 *     the village reuses a handful of materials instead of allocating one per
 *     mesh per render. Headless-safe: nothing here touches WebGL at
 *     construction time (DataTexture + material objects only), so vitest/jsdom
 *     can exercise it without a GL context.
 *   • GOLDEN_HOUR — the shared golden-hour scene palette (sun/sky/fog/ground)
 *     so CozyWorld/Ground (and wave-2 adopters: Structure, Foliage) agree on
 *     one set of hexes. WebGL material colors are explicitly OUTSIDE the CSS
 *     design-token system (established village convention; design-token-guard
 *     governs DOM/CSS only) — but they're centralized here, not sprinkled.
 *
 * Wave-2 agents (EM-118 foliage, EM-122 buildings) consume this module as-is.
 */

import * as THREE from 'three';

// ── Golden-hour palette (Direction 1) ────────────────────────────────────────

export const GOLDEN_HOUR = {
  /** Low-angle sun (directionalLight). */
  sun: '#ffcf99',
  /** Hemisphere fill: warm sky bounce / cool-green ground bounce. */
  hemiSky: '#ffe9c2',
  hemiGround: '#3a5a2a',
  /** Faint warm ambient so shadowed faces never go black. */
  ambient: '#ffe2bd',
  /** Fog + canvas backdrop — warm peach haze matching the sunset sky. */
  fog: '#f6d3a4',
  background: '#f6d3a4',
  /** Terrain range per the art doc: #8FB85A → #6E9A3E. */
  terrain: '#8fb85a',
  terrainEdge: '#6e9a3e',
  /** Dirt paths. */
  path: '#c9a36b',
  /** Warm light-glow accent (windows, lanterns, string lights). */
  glow: '#ffe08a',
} as const;

/**
 * Shared in-canvas label inks (EM-188): the warm cream text + dark outline
 * the village's Billboard labels already use (Building/Structure literals),
 * centralized here so new label surfaces (street names) import them instead
 * of sprinkling hex into TSX. WebGL colors — outside the CSS token system
 * by the established village convention (see the module header).
 */
export const LABEL_INK = '#fff3e0';
export const LABEL_OUTLINE = '#241b14';

// ── Gradient ramp ────────────────────────────────────────────────────────────

/** Default band count for the cel ramp (3–4 reads best on chunky low-poly). */
export const TOON_RAMP_STEPS = 4;

/**
 * Luminance floor of the ramp (0..1). Shaded bands bottom out here instead of
 * at 0 so the hemisphere/ambient warmth shows through — never black shadows.
 */
export const TOON_RAMP_FLOOR = 0.45;

const gradientMapCache = new Map<number, THREE.DataTexture>();

/**
 * Build (or fetch the cached) N-step grayscale ramp texture for
 * MeshToonMaterial.gradientMap. NearestFilter + no mipmaps keep the bands
 * razor-edged — the whole point of the cel look.
 */
export function toonGradientMap(steps: number = TOON_RAMP_STEPS): THREE.DataTexture {
  const cached = gradientMapCache.get(steps);
  if (cached) return cached;

  const data = new Uint8Array(steps * 4);
  for (let i = 0; i < steps; i++) {
    // Evenly spaced bands from the warm floor up to full brightness.
    const t = steps === 1 ? 1 : i / (steps - 1);
    const v = Math.round((TOON_RAMP_FLOOR + (1 - TOON_RAMP_FLOOR) * t) * 255);
    data[i * 4 + 0] = v;
    data[i * 4 + 1] = v;
    data[i * 4 + 2] = v;
    data[i * 4 + 3] = 255;
  }

  const tex = new THREE.DataTexture(data, steps, 1, THREE.RGBAFormat);
  tex.minFilter = THREE.NearestFilter;
  tex.magFilter = THREE.NearestFilter;
  tex.generateMipmaps = false;
  tex.needsUpdate = true;

  gradientMapCache.set(steps, tex);
  return tex;
}

// ── Cached material factory ──────────────────────────────────────────────────

export interface ToonMaterialOpts {
  /** Emissive glow color (windows, lanterns, flowers, chaos accents). */
  emissive?: string;
  emissiveIntensity?: number;
  transparent?: boolean;
  opacity?: number;
  /**
   * Coplanar transparent decals (e.g. the ground-zone tints) pass
   * `depthWrite:false` + `polygonOffset:true` so they blend OVER the terrain
   * without z-fighting it at grazing angles / distance — the "jittery grass"
   * shimmer at the edge of the view when zoomed out.
   */
  depthWrite?: boolean;
  polygonOffset?: boolean;
}

const materialCache = new Map<string, THREE.MeshToonMaterial>();

/** Normalize the param tuple into a stable cache key. */
function cacheKey(color: string, opts: ToonMaterialOpts): string {
  return [
    color.toLowerCase(),
    (opts.emissive ?? '#000000').toLowerCase(),
    opts.emissiveIntensity ?? 1,
    opts.transparent ? 1 : 0,
    opts.opacity ?? 1,
    opts.depthWrite === false ? 0 : 1,
    opts.polygonOffset ? 1 : 0,
  ].join('|');
}

/**
 * The shared warm-toon material. Identical (color, opts) → the IDENTICAL
 * MeshToonMaterial instance (cache hit); distinct params → distinct instance.
 * Never dispose the returned material — it's shared scene-wide (R3F does not
 * auto-dispose prop-assigned materials, so passing it via `material={...}` is
 * safe across unmounts).
 */
export function toonMaterial(
  color: string,
  opts: ToonMaterialOpts = {},
): THREE.MeshToonMaterial {
  const key = cacheKey(color, opts);
  const cached = materialCache.get(key);
  if (cached) return cached;

  const mat = new THREE.MeshToonMaterial({
    color: new THREE.Color(color),
    gradientMap: toonGradientMap(),
    emissive: new THREE.Color(opts.emissive ?? '#000000'),
    emissiveIntensity: opts.emissiveIntensity ?? 1,
    transparent: opts.transparent ?? false,
    opacity: opts.opacity ?? 1,
    depthWrite: opts.depthWrite ?? true,
    polygonOffset: opts.polygonOffset ?? false,
    polygonOffsetFactor: opts.polygonOffset ? -1 : 0,
    polygonOffsetUnits: opts.polygonOffset ? -1 : 0,
  });

  materialCache.set(key, mat);
  return mat;
}

/** How many distinct toon materials the scene has allocated (perf telemetry). */
export function toonMaterialCacheSize(): number {
  return materialCache.size;
}

/** Test hook: drop all cached materials/ramps (does NOT dispose GPU resources). */
export function clearToonCacheForTests(): void {
  materialCache.clear();
  gradientMapCache.clear();
}
