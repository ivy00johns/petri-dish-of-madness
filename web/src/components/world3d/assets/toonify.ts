/**
 * toonify.ts — pure (GL-free) helpers that convert a loaded GLB scene graph to
 * the village's warm-toon look (EM-148, Wave C contract rule 8: "no untouched
 * PBR materials in the frame").
 *
 * Everything here is headless-safe: we only construct THREE.MeshToonMaterial
 * instances and walk Object3D trees, so vitest/jsdom can exercise the module
 * without a WebGL context (same convention as ../toon.ts).
 *
 * Two layers, deliberately separate:
 *
 *   • toonifyScene(root) — IN-PLACE conversion of every mesh material in the
 *     tree to MeshToonMaterial (gradient ramp from toonGradientMap(), original
 *     .map/.color preserved). Conversion is cached per SOURCE material, so a
 *     GLB whose meshes share one atlas material allocates exactly one toon
 *     material — and calling toonifyScene twice (or on a <Clone> of an already
 *     converted tree) is a no-op. Also flips castShadow/receiveShadow on.
 *     Run this ONCE on the gltf.scene that drei caches; every <Clone> then
 *     shares the converted materials for free.
 *
 *   • applyTintToScene(root, tint) — per-INSTANCE color override (identity
 *     tints, EM-122 healthTint soot). Because <Clone> shares materials, this
 *     clones each material once per mesh before touching it (marked via
 *     userData so re-tinting updates in place instead of stacking clones).
 *     Only ever call this on a cloned instance tree, never on the cached
 *     gltf.scene.
 */

import * as THREE from 'three';
import { toonGradientMap } from '../toon';

/** Marker keys on material.userData (namespaced to avoid GLB extras clashes). */
const TINT_CLONE_FLAG = '__petriTintClone';
const TINT_BASE_COLOR = '__petriTintBase';

export interface ToonifyCaches {
  /** source material → converted toon material (shared across clones). */
  materials: WeakMap<THREE.Material, THREE.MeshToonMaterial>;
  /** roots already converted (makes repeat calls cheap no-ops). */
  scenes: WeakSet<THREE.Object3D>;
}

export function createToonifyCaches(): ToonifyCaches {
  return { materials: new WeakMap(), scenes: new WeakSet() };
}

/** Module-level default caches — one conversion per GLB per app lifetime. */
const DEFAULT_CACHES = createToonifyCaches();

/**
 * Convert ONE source material to the toon equivalent, preserving the visual
 * inputs that matter for low-poly kits: base color, texture map, transparency,
 * face sidedness and vertex colors. PBR-only params (rough/metal) are dropped
 * by design — the gradient ramp owns shading.
 */
export function toToonMaterial(src: THREE.Material): THREE.MeshToonMaterial {
  if (src instanceof THREE.MeshToonMaterial) return src;
  const anySrc = src as THREE.Material & {
    color?: THREE.Color;
    map?: THREE.Texture | null;
  };
  const toon = new THREE.MeshToonMaterial({
    color: anySrc.color ? anySrc.color.clone() : new THREE.Color('#ffffff'),
    map: anySrc.map ?? null,
    gradientMap: toonGradientMap(),
    transparent: src.transparent,
    opacity: src.opacity,
    side: src.side,
    alphaTest: src.alphaTest,
    vertexColors: src.vertexColors,
  });
  toon.name = src.name;
  return toon;
}

function isMesh(obj: THREE.Object3D): obj is THREE.Mesh {
  return (obj as THREE.Mesh).isMesh === true;
}

/**
 * Convert every mesh material under `root` to MeshToonMaterial, in place.
 * Returns the number of mesh material slots rewritten (0 on a cached repeat
 * call). Shared source materials convert to the IDENTICAL toon instance.
 */
export function toonifyScene(
  root: THREE.Object3D,
  caches: ToonifyCaches = DEFAULT_CACHES,
): number {
  if (caches.scenes.has(root)) return 0;
  caches.scenes.add(root);

  let rewritten = 0;
  const convert = (mat: THREE.Material): THREE.MeshToonMaterial => {
    const cached = caches.materials.get(mat);
    if (cached) return cached;
    const toon = toToonMaterial(mat);
    caches.materials.set(mat, toon);
    // Self-map so already-toon trees stay stable across cache lookups.
    caches.materials.set(toon, toon);
    return toon;
  };

  root.traverse((obj) => {
    if (!isMesh(obj)) return;
    obj.castShadow = true;
    obj.receiveShadow = true;
    if (Array.isArray(obj.material)) {
      obj.material = obj.material.map((m) => {
        const toon = convert(m);
        if (toon !== m) rewritten++;
        return toon;
      });
    } else if (obj.material) {
      const toon = convert(obj.material);
      if (toon !== obj.material) rewritten++;
      obj.material = toon;
    }
  });
  return rewritten;
}

/**
 * Apply a per-instance color tint to every mesh material under `root`.
 *
 * The first application CLONES each material (so the shared, cached toon
 * materials are never mutated — contract: tint "on CLONED materials only")
 * and records the clone's pre-tint color; later applications recompute from
 * that recorded base, so tints never compound. `tint` multiplies the base
 * color (white = unchanged), which is the right model for textured kits where
 * material.color is a multiplier over the texture.
 */
export function applyTintToScene(root: THREE.Object3D, tint: string): void {
  const tintColor = new THREE.Color(tint);
  root.traverse((obj) => {
    if (!isMesh(obj)) return;
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
    const out = mats.map((mat) => {
      if (!mat) return mat;
      let m = mat as THREE.MeshToonMaterial;
      if (!m.userData[TINT_CLONE_FLAG]) {
        m = m.clone() as THREE.MeshToonMaterial;
        m.userData[TINT_CLONE_FLAG] = true;
        m.userData[TINT_BASE_COLOR] = m.color ? m.color.getHex() : 0xffffff;
      }
      if (m.color) {
        m.color.setHex(m.userData[TINT_BASE_COLOR] as number).multiply(tintColor);
      }
      return m;
    });
    obj.material = Array.isArray(obj.material) ? out : out[0];
  });
}

/** True if a material was produced by {@link applyTintToScene} (test hook). */
export function isTintClone(mat: THREE.Material): boolean {
  return mat.userData?.[TINT_CLONE_FLAG] === true;
}
