/**
 * models.test.ts — EM-148 asset-layer gate. NO canvas/WebGL anywhere:
 *
 *   • registry shape — every VariantKey / PlaceKind / character key present,
 *     specs well-formed, urls under /models/;
 *   • the vendored files EXIST on disk and are real GLBs — we parse each
 *     GLB's JSON chunk (plain node fs + DataView, no loader) and re-measure
 *     its bounding box, so the registry scales are PROVEN to respect the
 *     city footprints (buildings ≤3.4 units on the long side in the
 *     4.2-spacing slot rings — the Wave D1 city convention; villager ~1.1
 *     tall, critters ≲0.8) — change a model file and this test tells you if
 *     it stops fitting;
 *   • declared animation clips actually exist in the GLBs;
 *   • license hygiene BOTH directions — ASSET_LICENSES.md records every
 *     vendored file, every hero-kit row in the doc points at a real registry
 *     file, no orphan GLBs sit in the hero-kit directories, and the retired
 *     Wave D1.5 medieval kit is GONE;
 *   • toonify helpers — conversion / caching / tint-cloning unit-tested on a
 *     stub Object3D tree with stub materials.
 */

import { describe, expect, it } from 'vitest';
// The app tsconfig ships no @types/node (and EM-148 adds no deps), so the
// node builtins this fs-backed test needs are imported under @ts-ignore —
// vitest executes in node, where they are real.
// @ts-ignore -- node builtin without @types/node
import { existsSync, readFileSync, readdirSync } from 'node:fs';
// @ts-ignore -- node builtin without @types/node
import { resolve } from 'node:path';
import * as THREE from 'three';
import type { VariantKey } from '../worldSpace';
import type { PlaceKind } from '../../../types';
import {
  CHARACTER_MODELS,
  MODEL_REGISTRY,
  MODEL_POOLS,
  PLACE_MODELS,
  PLACE_POOLS,
  VILLAGER_POOL,
  allModelSpecs,
  type ModelSpec,
} from './models';
import { effectiveTint } from './Model';
import {
  applyTintToScene,
  createToonifyCaches,
  isTintClone,
  toToonMaterial,
  toonifyScene,
} from './toonify';

// vitest's cwd is web/ (the vitest.config.ts root); no @types/node, so the
// one global we need is declared minimally here.
declare const process: { cwd(): string };
const PUBLIC_DIR = resolve(process.cwd(), 'public');
const REPO_ROOT = resolve(process.cwd(), '..');

const ALL_VARIANTS: VariantKey[] = [
  'garden', 'farm', 'workshop', 'library', 'clocktower',
  'house', 'stall', 'monument', 'well', 'zoo', 'generic',
  // EM-216/EM-217 distinct build-type variants
  'tavern', 'market', 'smithy', 'temple', 'school', 'clinic', 'granary',
  // EM-216b catalog expansion
  'bakery', 'bank', 'theater', 'lighthouse', 'bathhouse', 'dock',
];
const ALL_PLACE_KINDS: PlaceKind[] = ['work', 'home', 'social', 'governance', 'wild'];

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
    name?: string;
  }>;
  meshes?: Array<{ primitives: Array<{ attributes: { POSITION?: number } }> }>;
  accessors?: Array<{ min?: number[]; max?: number[] }>;
  scenes?: Array<{ nodes?: number[] }>;
  scene?: number;
  animations?: Array<{ name?: string }>;
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

// ── Registry shape ───────────────────────────────────────────────────────────

describe('MODEL_REGISTRY', () => {
  it('has an entry (model or explicit null) for every VariantKey', () => {
    expect(Object.keys(MODEL_REGISTRY).sort()).toEqual([...ALL_VARIANTS].sort());
  });

  it('wires garden, library, and zoo to EM-216 GLBs (were recorded nulls)', () => {
    for (const v of ['garden', 'library', 'zoo'] as const) {
      expect(MODEL_REGISTRY[v], v).not.toBeNull();
      expect(MODEL_REGISTRY[v]!.url, v).toContain('/models/poly/');
    }
  });
});

describe('PLACE_MODELS', () => {
  it('has an entry for every PlaceKind', () => {
    expect(Object.keys(PLACE_MODELS).sort()).toEqual([...ALL_PLACE_KINDS].sort());
  });
});

describe('CHARACTER_MODELS', () => {
  it('has villager, cat and dog entries with idle+walk clips', () => {
    for (const key of ['villager', 'cat', 'dog'] as const) {
      const spec = CHARACTER_MODELS[key];
      expect(spec, key).not.toBeNull();
      expect(spec!.clips?.idle, `${key} idle clip`).toBeTruthy();
      expect(spec!.clips?.walk, `${key} walk clip`).toBeTruthy();
    }
  });
});

describe('every non-null ModelSpec', () => {
  const specs = allModelSpecs();

  it('exists (the registries are not all-null)', () => {
    expect(specs.length).toBeGreaterThan(0);
  });

  it.each(specs.map((s) => [s.url, s] as const))(
    '%s is well-formed and exists on disk',
    (_url, spec) => {
      expect(spec.url.startsWith('/models/')).toBe(true);
      expect(Number.isFinite(spec.scale)).toBe(true);
      expect(spec.scale).toBeGreaterThan(0);
      expect(Number.isFinite(spec.yOffset)).toBe(true);
      expect(existsSync(diskPath(spec)), `missing file: ${diskPath(spec)}`).toBe(true);
    },
  );

  // EM-248: the payload guard is a runaway-catch, NOT a count throttle. GLBs are
  // LAZY-loaded via drei useGLTF/preload — they are NOT first-paint bundle weight,
  // so adding MORE variety is free at load time. The total ceiling only catches an
  // accidental whole-kit dump; the per-file cap catches the real failure (a file
  // vendored without dedup/prune, or with the wrong compression). 15→28 (EM-216e)
  // → 64 MB total + 4 MB/file (EM-248).
  it('no single vendored GLB exceeds the 4 MB per-file sanity cap', () => {
    for (const s of specs) {
      const bytes = readFileSync(diskPath(s)).byteLength;
      expect(bytes, `${s.url} is ${(bytes / 1024 / 1024).toFixed(1)} MB — repack (dedup/prune, no compression)`)
        .toBeLessThanOrEqual(4 * 1024 * 1024);
    }
  });

  it('total vendored payload stays within the 64 MB runaway-catch', () => {
    const total = specs.reduce((sum, s) => sum + readFileSync(diskPath(s)).byteLength, 0);
    expect(total).toBeLessThanOrEqual(64 * 1024 * 1024);
  });
});

// ── Footprint discipline (measured from the real GLBs) ──────────────────────

describe('scaled footprints', () => {
  it.each(
    (Object.entries(MODEL_REGISTRY) as Array<[VariantKey, ModelSpec | null]>)
      .filter((e): e is [VariantKey, ModelSpec] => e[1] !== null),
  )('building %s stays ≤3.4 units on the long side (city convention)', (_k, spec) => {
    const { size } = glbBounds(readGlbJson(diskPath(spec)));
    const xz = Math.max(size.x, size.z) * spec.scale;
    expect(xz).toBeGreaterThan(1.2); // not a speck
    expect(xz).toBeLessThanOrEqual(3.4);
    expect(size.y * spec.scale).toBeLessThanOrEqual(4.2);
  });

  it.each(
    (Object.entries(PLACE_MODELS) as Array<[PlaceKind, ModelSpec | null]>)
      .filter((e): e is [PlaceKind, ModelSpec] => e[1] !== null),
  )('place anchor %s stays within the anchor footprint', (_k, spec) => {
    const { size } = glbBounds(readGlbJson(diskPath(spec)));
    expect(Math.max(size.x, size.z) * spec.scale).toBeLessThanOrEqual(3.4);
    expect(size.y * spec.scale).toBeLessThanOrEqual(5.5);
  });

  it('villager scales to roughly the 1.1-unit capsule', () => {
    const spec = CHARACTER_MODELS.villager!;
    const { size } = glbBounds(readGlbJson(diskPath(spec)));
    const h = size.y * spec.scale;
    expect(h).toBeGreaterThanOrEqual(0.9);
    expect(h).toBeLessThanOrEqual(1.4);
  });

  it.each([['cat'], ['dog']] as const)('critter %s stays small', (key) => {
    const spec = CHARACTER_MODELS[key]!;
    const { size } = glbBounds(readGlbJson(diskPath(spec)));
    expect(size.y * spec.scale).toBeLessThanOrEqual(0.8);
  });

  it('models sit on the ground (no floating/buried bases)', () => {
    for (const spec of allModelSpecs()) {
      const { min } = glbBounds(readGlbJson(diskPath(spec)));
      expect(Math.abs(min.y * spec.scale + spec.yOffset), spec.url).toBeLessThan(0.15);
    }
  });
});

// ── EM-216b: variety pools (per-slot variation) ──────────────────────────────

describe('MODEL_POOLS (EM-216b variety)', () => {
  const poolEntries = Object.entries(MODEL_POOLS) as Array<[VariantKey, ModelSpec[]]>;

  it('each pool has ≥2 distinct GLBs and includes its MODEL_REGISTRY default', () => {
    expect(poolEntries.length).toBeGreaterThan(0);
    for (const [variant, pool] of poolEntries) {
      expect(pool.length, variant).toBeGreaterThanOrEqual(2);
      const urls = pool.map((s) => s.url);
      expect(new Set(urls).size, `${variant} has duplicate urls`).toBe(pool.length);
      // slot 0 is the single-spec default so the no-id path agrees with the pool
      expect(pool[0].url, `${variant} slot 0`).toBe(MODEL_REGISTRY[variant]!.url);
    }
  });

  it('every pool member fits the city footprint and sits on the ground', () => {
    for (const [variant, pool] of poolEntries) {
      for (const spec of pool) {
        const { size, min } = glbBounds(readGlbJson(diskPath(spec)));
        const xz = Math.max(size.x, size.z) * spec.scale;
        expect(xz, `${variant} ${spec.url} xz`).toBeGreaterThan(1.2);
        expect(xz, `${variant} ${spec.url} xz`).toBeLessThanOrEqual(3.4);
        expect(size.y * spec.scale, `${variant} ${spec.url} y`).toBeLessThanOrEqual(4.2);
        expect(
          Math.abs(min.y * spec.scale + spec.yOffset),
          `${variant} ${spec.url} ground`,
        ).toBeLessThan(0.15);
      }
    }
  });
});

describe('PLACE_POOLS (EM-248 anchor variety)', () => {
  const poolEntries = Object.entries(PLACE_POOLS) as Array<[PlaceKind, ModelSpec[]]>;

  it('each pool has ≥2 distinct GLBs and includes its PLACE_MODELS default at slot 0', () => {
    expect(poolEntries.length).toBeGreaterThan(0);
    for (const [kind, pool] of poolEntries) {
      expect(pool.length, kind).toBeGreaterThanOrEqual(2);
      expect(new Set(pool.map((s) => s.url)).size, `${kind} dup urls`).toBe(pool.length);
      expect(pool[0].url, `${kind} slot 0`).toBe(PLACE_MODELS[kind]!.url);
    }
  });

  it('every pool member fits the anchor footprint and sits on the ground', () => {
    for (const [kind, pool] of poolEntries) {
      for (const spec of pool) {
        const { size, min } = glbBounds(readGlbJson(diskPath(spec)));
        expect(Math.max(size.x, size.z) * spec.scale, `${kind} ${spec.url} xz`).toBeLessThanOrEqual(3.4);
        expect(size.y * spec.scale, `${kind} ${spec.url} y`).toBeLessThanOrEqual(5.5);
        expect(Math.abs(min.y * spec.scale + spec.yOffset), `${kind} ${spec.url} ground`).toBeLessThan(0.15);
      }
    }
  });
});

// ── EM-216b: villager variety pool ───────────────────────────────────────────

describe('VILLAGER_POOL (EM-216b variety)', () => {
  it('has ≥2 distinct meshes; slot 0 is the KayKit villager default', () => {
    expect(VILLAGER_POOL.length).toBeGreaterThanOrEqual(2);
    expect(new Set(VILLAGER_POOL.map((s) => s.url)).size).toBe(VILLAGER_POOL.length);
    expect(VILLAGER_POOL[0].url).toBe(CHARACTER_MODELS.villager!.url);
  });

  it.each(VILLAGER_POOL.map((s) => [s.url, s] as const))(
    '%s declares idle/walk clips that exist in the GLB and scales ~human height',
    (_url, spec) => {
      const json = readGlbJson(diskPath(spec));
      const names = (json.animations ?? []).map((a) => a.name);
      expect(names, `${spec.url} idle`).toContain(spec.clips!.idle);
      expect(names, `${spec.url} walk`).toContain(spec.clips!.walk);
      const h = glbBounds(json).size.y * spec.scale;
      expect(h, `${spec.url} height`).toBeGreaterThanOrEqual(0.8);
      expect(h, `${spec.url} height`).toBeLessThanOrEqual(1.6);
    },
  );
});

// ── Declared clips exist in the GLBs ─────────────────────────────────────────

describe('animation clips', () => {
  it.each([
    ['villager'], ['cat'], ['dog'],
    // EM-216b: the 5 new critters were clip-normalized to Idle/Walk like cat/dog.
    ['squirrel'], ['raccoon'], ['goat'], ['fox'], ['crow'],
  ] as const)(
    '%s GLB contains the declared idle/walk clips',
    (key) => {
      const spec = CHARACTER_MODELS[key]!;
      const names = (readGlbJson(diskPath(spec)).animations ?? []).map((a) => a.name);
      expect(names).toContain(spec.clips!.idle);
      expect(names).toContain(spec.clips!.walk);
    },
  );

  it('static building models carry no animations', () => {
    for (const spec of Object.values(MODEL_REGISTRY)) {
      if (!spec) continue;
      expect(readGlbJson(diskPath(spec)).animations ?? []).toHaveLength(0);
    }
  });
});

// ── License hygiene ──────────────────────────────────────────────────────────

describe('ASSET_LICENSES.md', () => {
  const doc = readFileSync(resolve(REPO_ROOT, 'ASSET_LICENSES.md'), 'utf8');

  /** The hero-kit dirs THIS registry owns rows for (kenney-city is shared
   *  with cityModels.ts, whose test runs the same checks for that dir). */
  const HERO_DIRS = ['kaykit-adventurers', 'kenney-fantasy-town', 'quaternius', 'poly'] as const;

  it('records every vendored model file', () => {
    for (const spec of allModelSpecs()) {
      expect(doc, `ASSET_LICENSES.md is missing ${spec.url}`).toContain(
        `web/public${spec.url}`,
      );
    }
  });

  it('every hero-kit row in the doc is a real registry file (no orphan rows)', () => {
    const registryRepoPaths = new Set(allModelSpecs().map((s) => `web/public${s.url}`));
    const rows =
      doc.match(
        /web\/public\/models\/(?:kaykit-adventurers|kenney-fantasy-town|quaternius|poly|kaykit-medieval-hexagon)\/[\w.-]+\.glb/g,
      ) ?? [];
    expect(rows.length).toBeGreaterThan(0);
    for (const repoPath of new Set<string>(rows)) {
      expect(registryRepoPaths.has(repoPath), `orphan license row: ${repoPath}`).toBe(true);
      expect(existsSync(resolve(REPO_ROOT, repoPath)), `row file missing: ${repoPath}`).toBe(true);
    }
  });

  it('no orphan GLBs sit in the hero-kit directories', () => {
    const registryRepoPaths = new Set(allModelSpecs().map((s) => `web/public${s.url}`));
    for (const dir of HERO_DIRS) {
      const files: string[] = readdirSync(resolve(PUBLIC_DIR, 'models', dir));
      for (const f of files) {
        expect(
          registryRepoPaths.has(`web/public/models/${dir}/${f}`),
          `orphan vendored file: web/public/models/${dir}/${f}`,
        ).toBe(true);
      }
    }
  });

  it('the medieval kit is retired (Wave D1.5): no dir, no license rows', () => {
    expect(existsSync(resolve(PUBLIC_DIR, 'models', 'kaykit-medieval-hexagon'))).toBe(false);
    expect(doc).not.toContain('kaykit-medieval-hexagon');
    // the fantasy-town stall went with it (the fountain stays)
    expect(doc).not.toContain('kenney-fantasy-town/stall.glb');
    expect(existsSync(resolve(PUBLIC_DIR, 'models', 'kenney-fantasy-town', 'stall.glb'))).toBe(false);
  });

  it('declares CC0 for the vendored kits', () => {
    for (const kit of ['kaykit-adventurers', 'kenney-fantasy-town', 'kenney-city', 'quaternius']) {
      expect(doc).toContain(kit);
    }
    expect(doc).toContain('creativecommons.org/publicdomain/zero/1.0');
  });
});

// ── toonify (stub Object3D tree, stub materials — no GL) ─────────────────────

type StubMesh = THREE.Mesh<THREE.BufferGeometry, THREE.Material>;

function stubTree() {
  const root = new THREE.Group();
  const map = new THREE.Texture();
  const shared = new THREE.MeshStandardMaterial({ color: '#e07a5f', map });
  const meshA: StubMesh = new THREE.Mesh(new THREE.BufferGeometry(), shared);
  const meshB: StubMesh = new THREE.Mesh(new THREE.BufferGeometry(), shared);
  const solo = new THREE.MeshStandardMaterial({ color: '#5fa05f', transparent: true, opacity: 0.5 });
  const meshC: StubMesh = new THREE.Mesh(new THREE.BufferGeometry(), solo);
  root.add(meshA, meshB, meshC);
  return { root, map, shared, solo, meshA, meshB, meshC };
}

describe('toonifyScene', () => {
  it('converts every material to MeshToonMaterial preserving color + map', () => {
    const { root, map, meshA, meshC } = stubTree();
    const rewritten = toonifyScene(root, createToonifyCaches());
    expect(rewritten).toBe(3);
    const matA = meshA.material as THREE.MeshToonMaterial;
    expect(matA).toBeInstanceOf(THREE.MeshToonMaterial);
    expect(matA.map).toBe(map);
    expect(matA.color.getHexString()).toBe('e07a5f');
    expect(matA.gradientMap).not.toBeNull();
    const matC = meshC.material as THREE.MeshToonMaterial;
    expect(matC.transparent).toBe(true);
    expect(matC.opacity).toBe(0.5);
  });

  it('shared source materials convert to the IDENTICAL toon instance', () => {
    const { root, meshA, meshB, meshC } = stubTree();
    toonifyScene(root, createToonifyCaches());
    expect(meshA.material).toBe(meshB.material);
    expect(meshA.material).not.toBe(meshC.material);
  });

  it('is cached per scene root — the second call is a no-op', () => {
    const { root, meshA } = stubTree();
    const caches = createToonifyCaches();
    toonifyScene(root, caches);
    const converted = meshA.material;
    expect(toonifyScene(root, caches)).toBe(0);
    expect(meshA.material).toBe(converted);
  });

  it('flips shadow flags on', () => {
    const { root, meshA, meshB, meshC } = stubTree();
    toonifyScene(root, createToonifyCaches());
    for (const m of [meshA, meshB, meshC]) {
      expect(m.castShadow).toBe(true);
      expect(m.receiveShadow).toBe(true);
    }
  });

  it('toToonMaterial passes through materials that are already toon', () => {
    const toon = new THREE.MeshToonMaterial();
    expect(toToonMaterial(toon)).toBe(toon);
  });
});

describe('applyTintToScene', () => {
  function converted() {
    const t = stubTree();
    toonifyScene(t.root, createToonifyCaches());
    return t;
  }

  it('clones materials before tinting (shared toon materials untouched)', () => {
    const { root, meshA, meshB } = converted();
    const sharedToon = meshA.material as THREE.MeshToonMaterial;
    applyTintToScene(root, '#808080');
    expect(meshA.material).not.toBe(sharedToon);
    expect(isTintClone(meshA.material as THREE.Material)).toBe(true);
    expect(isTintClone(sharedToon)).toBe(false);
    // the shared material kept its original color
    expect(sharedToon.color.getHexString()).toBe('e07a5f');
    // both meshes got tinted clones
    expect(isTintClone(meshB.material as THREE.Material)).toBe(true);
  });

  it('multiplies the base color (white tint = unchanged)', () => {
    const { root, meshA } = converted();
    applyTintToScene(root, '#ffffff');
    const m = meshA.material as THREE.MeshToonMaterial;
    expect(m.color.getHexString()).toBe('e07a5f');
  });

  it('re-tinting recomputes from the recorded base — tints never compound', () => {
    const { root, meshA } = converted();
    applyTintToScene(root, '#808080');
    const afterFirst = (meshA.material as THREE.MeshToonMaterial).color.getHex();
    const cloneRef = meshA.material;
    applyTintToScene(root, '#808080');
    expect(meshA.material).toBe(cloneRef); // no clone stacking
    expect((meshA.material as THREE.MeshToonMaterial).color.getHex()).toBe(afterFirst);
    applyTintToScene(root, '#ffffff');
    expect((meshA.material as THREE.MeshToonMaterial).color.getHexString()).toBe('e07a5f');
  });
});

describe('effectiveTint', () => {
  it('returns null when nothing would change', () => {
    expect(effectiveTint(undefined, undefined)).toBeNull();
    expect(effectiveTint('#ffffff', undefined)).toBeNull();
    expect(effectiveTint(undefined, 100)).toBeNull();
  });

  it('passes the tint through and soots it by health', () => {
    expect(effectiveTint('#e07a5f', undefined)).toBe('#e07a5f');
    const sooted = effectiveTint(undefined, 0);
    expect(sooted).not.toBeNull();
    // healthTint('#ffffff', 0) — heavily darkened toward soot
    expect(sooted).toMatch(/^#[0-9a-f]{6}$/);
    expect(sooted!).not.toBe('#ffffff');
  });
});
