/**
 * cityModels.test.ts — EM-152 city asset-layer gate (Wave D1a). NO canvas/GL:
 *
 *   • registry totality — every frozen CityPieceKey (contracts/wave-d1.md)
 *     present, specs well-formed, urls under /models/;
 *   • the vendored files EXIST on disk, are real GLBs, and carry no
 *     DRACO/meshopt extensions (no decoders ship under web/public/);
 *   • footprint bounds re-measured from the GLB bytes (models.test.ts
 *     pattern): road tiles land at EXACTLY TILE = 2.6 world units square,
 *     buildings ≤ 3.4 on the long side, props 0.4–1.2, cars ~1.6 long,
 *     everything ground-flush;
 *   • license hygiene BOTH directions — every vendored file has an
 *     ASSET_LICENSES.md row, every kenney-city/kaykit-city row in the doc
 *     points at a real vendored registry file, and no orphan GLBs sit in the
 *     vendored directories.
 *
 * NOTE: `CityPieceKey` lives in ../cityLayout (D1b's file, written in
 * parallel). It is imported as a TYPE only — esbuild/vitest erase it, so this
 * suite runs standalone before the sibling module lands.
 */

import { describe, expect, it } from 'vitest';
// The app tsconfig ships no @types/node; node builtins are real under vitest.
// @ts-ignore -- node builtin without @types/node
import { existsSync, readFileSync, readdirSync } from 'node:fs';
// @ts-ignore -- node builtin without @types/node
import { resolve } from 'node:path';
import * as THREE from 'three';
import type { CityPieceKey } from '../cityLayout';
import type { ModelSpec } from './models';
import { CITY_MODEL_REGISTRY, allCityModelSpecs } from './cityModels';

declare const process: { cwd(): string };
const PUBLIC_DIR = resolve(process.cwd(), 'public');
const REPO_ROOT = resolve(process.cwd(), '..');

/** Frozen TILE pitch (contracts/wave-d1.md §D1b). Not imported from
 * cityLayout because that module is a parallel deliverable — the contract
 * freezes the number, and this literal IS the cross-check. */
const TILE = 2.6;

/** The frozen 23-key vocabulary, verbatim from contracts/wave-d1.md. */
const ALL_CITY_KEYS: CityPieceKey[] = [
  'road_straight', 'road_corner', 'road_tee', 'road_cross', 'road_end',
  'com_a', 'com_b', 'com_c',
  'res_a', 'res_b', 'res_c',
  'ind_a', 'ind_b',
  'civic_a',
  'lamp', 'bench', 'hydrant', 'bin', 'fence', 'tree_city',
  'car_a', 'car_b', 'car_c',
];

const ROAD_KEYS: CityPieceKey[] = [
  'road_straight', 'road_corner', 'road_tee', 'road_cross', 'road_end',
];
const BUILDING_KEYS: CityPieceKey[] = [
  'com_a', 'com_b', 'com_c', 'res_a', 'res_b', 'res_c', 'ind_a', 'ind_b', 'civic_a',
];
const PROP_KEYS: CityPieceKey[] = ['lamp', 'bench', 'hydrant', 'bin', 'fence', 'tree_city'];
const CAR_KEYS: CityPieceKey[] = ['car_a', 'car_b', 'car_c'];

function diskPath(spec: ModelSpec): string {
  return resolve(PUBLIC_DIR, spec.url.replace(/^\//, ''));
}

// ── Minimal GLB reader (JSON chunk only — no GL, no loaders) ─────────────────

interface GlbJson {
  nodes?: Array<{
    mesh?: number;
    children?: number[];
    matrix?: number[];
    translation?: number[];
    rotation?: number[];
    scale?: number[];
  }>;
  meshes?: Array<{ primitives: Array<{ attributes: { POSITION?: number } }> }>;
  accessors?: Array<{ min?: number[]; max?: number[] }>;
  scenes?: Array<{ nodes?: number[] }>;
  scene?: number;
  animations?: Array<{ name?: string }>;
  extensionsRequired?: string[];
  extensionsUsed?: string[];
  buffers?: Array<{ uri?: string }>;
  images?: Array<{ uri?: string }>;
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
function glbBounds(g: GlbJson): { size: THREE.Vector3; min: THREE.Vector3 } {
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
  const size = new THREE.Vector3();
  box.getSize(size);
  return { size, min: box.min };
}

function measuredSpec(key: CityPieceKey) {
  const spec = CITY_MODEL_REGISTRY[key];
  expect(spec, `${key} expected non-null for this footprint check`).not.toBeNull();
  return { spec: spec!, ...glbBounds(readGlbJson(diskPath(spec!))) };
}

// ── Registry totality + shape ────────────────────────────────────────────────

describe('CITY_MODEL_REGISTRY', () => {
  it('covers the frozen 23-key CityPieceKey vocabulary exactly', () => {
    expect(Object.keys(CITY_MODEL_REGISTRY).sort()).toEqual([...ALL_CITY_KEYS].sort());
    expect(ALL_CITY_KEYS).toHaveLength(23);
  });

  it.each(allCityModelSpecs().map((s) => [s.url, s] as const))(
    '%s is well-formed and exists on disk',
    (_url, spec) => {
      expect(
        spec.url.startsWith('/models/kenney-city/') || spec.url.startsWith('/models/kaykit-city/'),
      ).toBe(true);
      expect(Number.isFinite(spec.scale)).toBe(true);
      expect(spec.scale).toBeGreaterThan(0);
      expect(spec.yOffset).toBe(0); // every vendored city kit is ground-flush
      expect(existsSync(diskPath(spec)), `missing file: ${diskPath(spec)}`).toBe(true);
    },
  );

  it('total NEW city payload stays within the 15 MB budget', () => {
    const total = allCityModelSpecs().reduce(
      (sum, s) => sum + readFileSync(diskPath(s)).byteLength,
      0,
    );
    expect(total).toBeLessThanOrEqual(15 * 1024 * 1024);
  });

  it('ships no DRACO/meshopt extensions (no decoders under web/public/)', () => {
    for (const spec of allCityModelSpecs()) {
      const g = readGlbJson(diskPath(spec));
      const exts = [...(g.extensionsRequired ?? []), ...(g.extensionsUsed ?? [])];
      expect(exts, spec.url).not.toContain('KHR_draco_mesh_compression');
      expect(exts, spec.url).not.toContain('EXT_meshopt_compression');
    }
  });

  it('embeds everything — no external buffer/texture URIs', () => {
    for (const spec of allCityModelSpecs()) {
      const g = readGlbJson(diskPath(spec));
      for (const b of g.buffers ?? []) expect(b.uri, `${spec.url} buffer`).toBeUndefined();
      for (const im of g.images ?? []) expect(im.uri, `${spec.url} image`).toBeUndefined();
    }
  });

  it('static set dressing carries no animations', () => {
    for (const spec of allCityModelSpecs()) {
      expect(readGlbJson(diskPath(spec)).animations ?? [], spec.url).toHaveLength(0);
    }
  });
});

// ── Footprint discipline (measured from the vendored GLB bytes) ─────────────

describe('scaled footprints', () => {
  it.each(ROAD_KEYS.map((k) => [k] as const))(
    'road tile %s lands at exactly TILE = 2.6 units square',
    (key) => {
      const { spec, size } = measuredSpec(key);
      expect(size.x * spec.scale).toBeCloseTo(TILE, 3);
      expect(size.z * spec.scale).toBeCloseTo(TILE, 3);
      expect(size.y * spec.scale).toBeLessThan(0.2); // flat tiles, not ramps
    },
  );

  it.each(BUILDING_KEYS.map((k) => [k] as const))(
    'building %s stays ≤ 3.4 units on the long side',
    (key) => {
      const { spec, size } = measuredSpec(key);
      const long = Math.max(size.x, size.z) * spec.scale;
      expect(long).toBeGreaterThan(1.8); // reads as a building, not a shed
      expect(long).toBeLessThanOrEqual(3.4);
    },
  );

  it.each(PROP_KEYS.map((k) => [k] as const))(
    'prop %s reads at 0.4–1.2 units (largest dimension)',
    (key) => {
      const { spec, size } = measuredSpec(key);
      const big = Math.max(size.x, size.y, size.z) * spec.scale;
      expect(big).toBeGreaterThanOrEqual(0.4);
      expect(big).toBeLessThanOrEqual(1.2);
    },
  );

  it.each(CAR_KEYS.map((k) => [k] as const))('car %s is ~1.6 units long', (key) => {
    const { spec, size } = measuredSpec(key);
    const long = Math.max(size.x, size.z) * spec.scale;
    expect(long).toBeGreaterThanOrEqual(1.45);
    expect(long).toBeLessThanOrEqual(1.75);
  });

  it('every piece sits on the ground (no floating/buried bases)', () => {
    for (const spec of allCityModelSpecs()) {
      const { min } = glbBounds(readGlbJson(diskPath(spec)));
      expect(Math.abs(min.y * spec.scale + spec.yOffset), spec.url).toBeLessThan(0.1);
    }
  });
});

// ── License hygiene — BOTH directions ────────────────────────────────────────

describe('ASSET_LICENSES.md ↔ vendored city files', () => {
  const doc = readFileSync(resolve(REPO_ROOT, 'ASSET_LICENSES.md'), 'utf8');
  const registryRepoPaths = new Set(
    allCityModelSpecs().map((s) => `web/public${s.url}`),
  );

  it('records every registry-referenced city GLB', () => {
    for (const repoPath of registryRepoPaths) {
      expect(doc, `ASSET_LICENSES.md is missing ${repoPath}`).toContain(repoPath);
    }
  });

  it('every kenney-city/kaykit-city row in the doc is a real registry file', () => {
    const rows = doc.match(/web\/public\/models\/(?:kenney-city|kaykit-city)\/[\w.-]+\.glb/g) ?? [];
    expect(rows.length).toBeGreaterThan(0);
    for (const repoPath of new Set<string>(rows)) {
      expect(registryRepoPaths.has(repoPath), `orphan license row: ${repoPath}`).toBe(true);
      expect(existsSync(resolve(REPO_ROOT, repoPath)), `row file missing: ${repoPath}`).toBe(true);
    }
  });

  it('no orphan GLBs sit in the vendored city directories', () => {
    for (const dir of ['kenney-city', 'kaykit-city']) {
      const files: string[] = readdirSync(resolve(PUBLIC_DIR, 'models', dir));
      for (const f of files) {
        expect(
          registryRepoPaths.has(`web/public/models/${dir}/${f}`),
          `orphan vendored file: web/public/models/${dir}/${f}`,
        ).toBe(true);
      }
    }
  });

  it('declares CC0 for the city kits', () => {
    expect(doc).toContain('kenney-city');
    expect(doc).toContain('kaykit-city');
    expect(doc).toContain('creativecommons.org/publicdomain/zero/1.0');
  });
});
