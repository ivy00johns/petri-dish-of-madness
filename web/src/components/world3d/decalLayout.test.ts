/**
 * decalLayout tests (EM-302b) — the measured facade-decal placement.
 *
 *   • measurement gate (the models.test.ts discipline): GLB_DECAL_BOUNDS is
 *     re-measured from the VENDORED files for every building GLB url in
 *     MODEL_REGISTRY + MODEL_POOLS — coverage is exact both directions and
 *     every value matches to 5e-3, so a swapped/added model fails loudly
 *     (with the expected row printed) instead of mis-placing murals;
 *   • rotatedFrontExtent / rotatedXCenter — the y-rotation math on an
 *     asymmetric footprint;
 *   • decalPlacement — the defect cases: deep GLBs (theater/tavern) get a
 *     front past the old fixed 1.06, x-offset GLBs (dock) center the mural
 *     on the measured facade instead of the group origin, short GLBs
 *     (garden) shrink + lower the canvas, tall GLBs keep the exact legacy
 *     mural height, procedural statuses fall back per-variant, damaged gets
 *     the scorched-box front.
 */

import { describe, expect, it } from 'vitest';
// @ts-ignore -- node builtin without @types/node (models.test.ts precedent)
import { readFileSync } from 'node:fs';
// @ts-ignore -- node builtin without @types/node
import { resolve } from 'node:path';
import * as THREE from 'three';
import { MODEL_REGISTRY, MODEL_POOLS, type ModelSpec } from './assets/models';
import { modelRotationY, resolveStructureModel } from './structureModel';
import {
  DAMAGED_FRONT_Z,
  DECAL_BASE_Y,
  DECAL_EPSILON,
  DECAL_SIZE,
  GLB_DECAL_BOUNDS,
  LEGACY_DECAL_Z,
  PROCEDURAL_FRONT_Z,
  decalPlacement,
  rotatedFrontExtent,
  rotatedXCenter,
  type DecalBounds,
} from './decalLayout';

declare const process: { cwd(): string };
const PUBLIC_DIR = resolve(process.cwd(), 'public');

// ── Minimal GLB reader (JSON chunk only — copied from models.test.ts) ────────

interface GlbJson {
  nodes?: Array<{
    mesh?: number;
    children?: number[];
    matrix?: number[];
    translation?: number[];
    rotation?: number[];
    scale?: number[];
    name?: string;
  }>;
  meshes?: Array<{ primitives: Array<{ attributes: { POSITION?: number } }> }>;
  accessors?: Array<{ min?: number[]; max?: number[] }>;
  scenes?: Array<{ nodes?: number[] }>;
  scene?: number;
}

function readGlbJson(path: string): GlbJson {
  const buf = readFileSync(path);
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  expect(view.getUint32(0, true)).toBe(0x46546c67); // 'glTF' magic
  const jsonLen = view.getUint32(12, true);
  expect(view.getUint32(16, true)).toBe(0x4e4f534a); // 'JSON' chunk type
  return JSON.parse(buf.subarray(20, 20 + jsonLen).toString('utf8'));
}

/** World-space AABB from accessor min/max run through the node hierarchy. */
function measuredBounds(url: string): DecalBounds {
  const g = readGlbJson(resolve(PUBLIC_DIR, url.replace(/^\//, '')));
  const box = new THREE.Box3();
  const nodes = g.nodes ?? [];
  const visit = (ni: number, parent: THREE.Matrix4) => {
    const n = nodes[ni];
    const local = new THREE.Matrix4();
    if (n.matrix) local.fromArray(n.matrix);
    else
      local.compose(
        new THREE.Vector3(...((n.translation ?? [0, 0, 0]) as [number, number, number])),
        new THREE.Quaternion(...((n.rotation ?? [0, 0, 0, 1]) as [number, number, number, number])),
        new THREE.Vector3(...((n.scale ?? [1, 1, 1]) as [number, number, number])),
      );
    const world = new THREE.Matrix4().multiplyMatrices(parent, local);
    if (n.mesh !== undefined) {
      for (const prim of g.meshes![n.mesh].primitives) {
        const acc = prim.attributes.POSITION !== undefined
          ? g.accessors![prim.attributes.POSITION]
          : undefined;
        if (acc?.min && acc?.max) {
          const sub = new THREE.Box3(
            new THREE.Vector3(...(acc.min as [number, number, number])),
            new THREE.Vector3(...(acc.max as [number, number, number])),
          ).applyMatrix4(world);
          box.union(sub);
        }
      }
    }
    for (const c of n.children ?? []) visit(c, world);
  };
  const scene = (g.scenes ?? [])[g.scene ?? 0] ?? {};
  for (const ni of scene.nodes ?? []) visit(ni, new THREE.Matrix4());
  return {
    minX: box.min.x,
    maxX: box.max.x,
    minZ: box.min.z,
    maxZ: box.max.z,
    maxY: box.max.y,
  };
}

/** Every building GLB url the resolver can hand a decal (registry + pools). */
function buildingUrls(): string[] {
  const urls = new Set<string>();
  for (const spec of Object.values(MODEL_REGISTRY)) if (spec) urls.add(spec.url);
  for (const pool of Object.values(MODEL_POOLS) as ModelSpec[][])
    for (const spec of pool) urls.add(spec.url);
  return [...urls].sort();
}

// ── measurement gate ─────────────────────────────────────────────────────────

describe('GLB_DECAL_BOUNDS (measured from the vendored files)', () => {
  it('covers EXACTLY the building GLB urls (registry + pools, both directions)', () => {
    expect(Object.keys(GLB_DECAL_BOUNDS).sort()).toEqual(buildingUrls());
  });

  it.each(buildingUrls().map((u) => [u] as const))(
    '%s matches the file on disk (regenerate the row on model swap)',
    (url) => {
      const measured = measuredBounds(url);
      const baked = GLB_DECAL_BOUNDS[url];
      for (const key of ['minX', 'maxX', 'minZ', 'maxZ', 'maxY'] as const) {
        expect(
          Math.abs(baked[key] - measured[key]),
          `${url} ${key}: baked ${baked[key]} vs measured ${measured[key]} — ` +
          `expected row: '${url}': { minX: ${measured.minX.toFixed(3)}, ` +
          `maxX: ${measured.maxX.toFixed(3)}, minZ: ${measured.minZ.toFixed(3)}, ` +
          `maxZ: ${measured.maxZ.toFixed(3)}, maxY: ${measured.maxY.toFixed(3)} }`,
        ).toBeLessThan(5e-3);
      }
    },
  );
});

// ── rotatedFrontExtent ───────────────────────────────────────────────────────

describe('rotatedFrontExtent', () => {
  const box: DecalBounds = { minX: -1, maxX: 2, minZ: -3, maxZ: 4, maxY: 9 };

  it('rotation 0 is the raw +z extent', () => {
    expect(rotatedFrontExtent(box, 0)).toBeCloseTo(4, 10);
  });

  it('rotation π/2 faces the −x side forward (z′ = −x)', () => {
    expect(rotatedFrontExtent(box, Math.PI / 2)).toBeCloseTo(1, 10);
  });

  it('rotation π faces the −z side forward', () => {
    expect(rotatedFrontExtent(box, Math.PI)).toBeCloseTo(3, 10);
  });

  it('rotation −π/2 faces the +x side forward (z′ = x)', () => {
    expect(rotatedFrontExtent(box, -Math.PI / 2)).toBeCloseTo(2, 10);
  });
});

// ── rotatedXCenter ───────────────────────────────────────────────────────────

describe('rotatedXCenter', () => {
  // Footprint center (1, −2): x-offset AND z-offset so every rotation differs.
  const box: DecalBounds = { minX: -1, maxX: 3, minZ: -5, maxZ: 1, maxY: 9 };

  it('rotation 0 is the raw footprint x-center', () => {
    expect(rotatedXCenter(box, 0)).toBeCloseTo(1, 10);
  });

  it('rotation π/2 maps the z-center onto x (x′ = z)', () => {
    expect(rotatedXCenter(box, Math.PI / 2)).toBeCloseTo(-2, 10);
  });

  it('rotation π mirrors the x-center (x′ = −x)', () => {
    expect(rotatedXCenter(box, Math.PI)).toBeCloseTo(-1, 10);
  });

  it('rotation −π/2 maps the negated z-center onto x (x′ = −z)', () => {
    expect(rotatedXCenter(box, -Math.PI / 2)).toBeCloseTo(2, 10);
  });

  it('matches the midpoint of the rotated corner x-extent (any angle)', () => {
    // The analytic center-rotation must equal brute-forcing the corners.
    const theta = 0.7;
    const cos = Math.cos(theta);
    const sin = Math.sin(theta);
    const xs = (
      [
        [box.minX, box.minZ],
        [box.minX, box.maxZ],
        [box.maxX, box.minZ],
        [box.maxX, box.maxZ],
      ] as Array<[number, number]>
    ).map(([x, z]) => x * cos + z * sin);
    expect(rotatedXCenter(box, theta)).toBeCloseTo(
      (Math.min(...xs) + Math.max(...xs)) / 2, 10);
  });
});

// ── decalPlacement ───────────────────────────────────────────────────────────

const operational = (kind: string, id = 'b1') =>
  ({ id, kind, status: 'operational' as const });

describe('decalPlacement (EM-302b)', () => {
  it('places the plane at the resolved GLB front + the surface-normal epsilon', () => {
    // tavern is registry-only (no pool): poly/tavern.glb, maxZ 2.011 × 0.78.
    const spec = MODEL_REGISTRY.tavern!;
    const box = GLB_DECAL_BOUNDS[spec.url];
    const p = decalPlacement(operational('tavern'));
    expect(p.z).toBeCloseTo(box.maxZ * spec.scale + DECAL_EPSILON, 6);
    // The defect: the fixed 1.06 sat INSIDE this facade (front ≈1.57).
    expect(p.z).toBeGreaterThan(1.5);
    // And the mural centers on the measured facade x (tavern ≈ origin-centered).
    expect(p.x).toBeCloseTo(((box.minX + box.maxX) / 2) * spec.scale, 6);
  });

  it('tracks the SAME pool GLB the Structure renderer picked for this id', () => {
    for (const id of ['b1', 'b2', 'casa', 'x9']) {
      const { variant, spec } = resolveStructureModel('house', id);
      const p = decalPlacement(operational('house', id));
      expect(spec).not.toBeNull();
      // The exact rotation the implementation folds in: spec + variant facing.
      const rotation = (spec!.rotation ?? 0) + modelRotationY(variant);
      expect(p.z).toBeCloseTo(
        rotatedFrontExtent(GLB_DECAL_BOUNDS[spec!.url], rotation) *
          spec!.scale + DECAL_EPSILON,
        6,
      );
      expect(p.x).toBeCloseTo(
        rotatedXCenter(GLB_DECAL_BOUNDS[spec!.url], rotation) * spec!.scale,
        6,
      );
    }
  });

  it('keeps the legacy mural height + full size on tall facades', () => {
    // temple is registry-only (no pool): top ≈ 4.327 × 0.92 ≈ 3.98u of wall.
    const p = decalPlacement(operational('temple'));
    expect(p.y).toBeCloseTo(DECAL_BASE_Y, 6);
    expect(p.scale).toBe(1);
    const spec = MODEL_REGISTRY.temple!;
    expect(p.z).toBeCloseTo(
      GLB_DECAL_BOUNDS[spec.url].maxZ * spec.scale + DECAL_EPSILON, 6);
  });

  it('an unknown emergent kind resolves exactly like generic (same id)', () => {
    expect(decalPlacement(operational('some emergent kind', 'z1')))
      .toEqual(decalPlacement(operational('generic', 'z1')));
  });

  it('shrinks + lowers the canvas on a SHORT model instead of hovering', () => {
    // garden: top ≈ 0.318 × 1.65 ≈ 0.52u — the old y=1.35 mural floated in air.
    const spec = MODEL_REGISTRY.garden!;
    const top = GLB_DECAL_BOUNDS[spec.url].maxY * spec.scale + spec.yOffset;
    const p = decalPlacement(operational('garden'));
    expect(p.scale).toBeLessThan(1);
    expect(p.scale).toBeGreaterThanOrEqual(0.3);
    // The whole canvas stays at/below the roofline margin and above grade.
    expect(p.y + (DECAL_SIZE[1] * p.scale) / 2).toBeLessThanOrEqual(top);
    expect(p.y - (DECAL_SIZE[1] * p.scale) / 2).toBeGreaterThan(0);
  });

  it('handles a front that sits in −z (dock hull is entirely behind origin)', () => {
    const spec = MODEL_REGISTRY.dock!;
    const p = decalPlacement(operational('dock'));
    // maxZ −0.327 × 1.91 ≈ −0.62: the old 1.06 plane floated ~1.7u in the air.
    expect(p.z).toBeLessThan(0);
    expect(p.z).toBeCloseTo(
      GLB_DECAL_BOUNDS[spec.url].maxZ * spec.scale + DECAL_EPSILON, 6);
  });

  it('centers the mural on the measured facade x (dock hull is x-offset)', () => {
    const spec = MODEL_REGISTRY.dock!;
    const box = GLB_DECAL_BOUNDS[spec.url];
    const p = decalPlacement(operational('dock'));
    // minX −0.139 / maxX 1.169 × 1.91: the hull's center sits ≈ 0.98 to the
    // right of the group origin — an x=0 mural hung half off the planks.
    expect(p.x).toBeCloseTo(((box.minX + box.maxX) / 2) * spec.scale, 6);
    expect(p.x).toBeGreaterThan(0.9);
  });

  it('offline uses the same measured GLB placement as operational', () => {
    const a = decalPlacement(operational('tavern'));
    const b = decalPlacement({ id: 'b1', kind: 'tavern', status: 'offline' });
    expect(b).toEqual(a);
  });

  it('damaged gets the scorched procedural-box front', () => {
    const p = decalPlacement({ id: 'b1', kind: 'tavern', status: 'damaged' });
    expect(p).toEqual({
      x: 0, y: DECAL_BASE_Y, z: DAMAGED_FRONT_Z + DECAL_EPSILON, scale: 1,
    });
  });

  it.each([['planned'], ['under_construction'], ['abandoned'], ['destroyed']] as const)(
    '%s keeps the legacy plane (no finished facade to measure)',
    (status) => {
      const p = decalPlacement({ id: 'b1', kind: 'house', status: status as never });
      expect(p).toEqual({ x: 0, y: DECAL_BASE_Y, z: LEGACY_DECAL_Z, scale: 1 });
    },
  );

  it('PROCEDURAL_FRONT_Z covers every variant the resolver can return', () => {
    // The fallback table must never miss (a registry null or streaming moment
    // reads it) — keys match MODEL_REGISTRY's VariantKey set exactly.
    expect(Object.keys(PROCEDURAL_FRONT_Z).sort())
      .toEqual(Object.keys(MODEL_REGISTRY).sort());
    for (const v of Object.values(PROCEDURAL_FRONT_Z)) {
      expect(v).toBeGreaterThan(0.5);
      expect(v).toBeLessThan(2);
    }
  });
});
