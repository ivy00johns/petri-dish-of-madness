/**
 * propModels.test.ts — Wave K (EM-218) PROP asset-layer gate. NO canvas/WebGL:
 *
 *   • registry shape — every PropKind present, specs well-formed, urls under
 *     /models/, and the (already-vendored) files EXIST on disk;
 *   • propVariant resolver — exact known kinds, case-insensitive substring
 *     keyword match, prototype-member hardening, and the unknown → null
 *     procedural-fallback path (never a hole);
 *   • license hygiene — every prop GLB is recorded in ASSET_LICENSES.md (the
 *     reuse note this wave requires).
 */

import { describe, expect, it } from 'vitest';
// @ts-ignore -- node builtin without @types/node
import { existsSync, readFileSync } from 'node:fs';
// @ts-ignore -- node builtin without @types/node
import { resolve } from 'node:path';
import {
  PROP_MODELS,
  PROP_POOLS,
  allPropModelSpecs,
  propModel,
  propVariant,
  type PropKind,
} from './propModels';

declare const process: { cwd(): string };
const PUBLIC_DIR = resolve(process.cwd(), 'public');
const REPO_ROOT = resolve(process.cwd(), '..');

const ALL_PROP_KINDS: PropKind[] = [
  'bench', 'lamp', 'tree', 'fence', 'bin', 'hydrant', 'fountain',
  // EM-216 new-kit props (poly.pizza CC0)
  'statue', 'planter', 'flower', 'rock', 'bush', 'crate', 'barrel', 'sign', 'stall',
];

describe('PROP_MODELS registry', () => {
  it('has a non-null spec for every PropKind', () => {
    expect(Object.keys(PROP_MODELS).sort()).toEqual([...ALL_PROP_KINDS].sort());
    for (const k of ALL_PROP_KINDS) {
      expect(PROP_MODELS[k], k).toBeTruthy();
    }
  });

  it('every spec is well-formed and exists on disk (already-vendored, no new downloads)', () => {
    for (const spec of allPropModelSpecs()) {
      expect(spec.url.startsWith('/models/'), spec.url).toBe(true);
      expect(Number.isFinite(spec.scale)).toBe(true);
      expect(spec.scale).toBeGreaterThan(0);
      expect(Number.isFinite(spec.yOffset)).toBe(true);
      const disk = resolve(PUBLIC_DIR, spec.url.replace(/^\//, ''));
      expect(existsSync(disk), `missing prop GLB: ${disk}`).toBe(true);
    }
  });

  it('wires vendored kits (reused Kenney/KayKit + EM-216 poly.pizza CC0 props)', () => {
    const urls = allPropModelSpecs().map((s) => s.url);
    for (const u of urls) {
      expect(
        /^\/models\/(kenney-city|kenney-fantasy-town|kaykit-city|poly-props)\//.test(u),
        u,
      ).toBe(true);
    }
  });
});

describe('propVariant (EM-218 resolver)', () => {
  it('resolves exact known kinds to themselves', () => {
    for (const k of ALL_PROP_KINDS) {
      expect(propVariant(k), k).toBe(k);
    }
  });

  it('keyword-maps realistic emergent kinds (case-insensitive substring)', () => {
    const cases: Array<[string, PropKind]> = [
      ['park_bench', 'bench'],
      ['wooden_seat', 'bench'],
      ['street_lamp', 'lamp'],
      ['old_lantern', 'lamp'],
      ['Lamp_Post', 'lamp'],
      ['oak_tree', 'tree'],
      ['flowering_shrub', 'tree'],
      ['picket_fence', 'fence'],
      ['garden_hedge', 'fence'],
      ['trash_bin', 'bin'],
      ['rubbish_can', 'bin'],
      ['fire_hydrant', 'hydrant'],
      ['stone_fountain', 'fountain'],
      ['village_birdbath', 'fountain'],
      // EM-216 new-kit props — ordering dodges substring traps:
      ['marble_statue', 'statue'],
      ['flower_planter', 'planter'],
      ['potted_fern', 'planter'],
      ['rose_blossom', 'flower'],
      ['garden_boulder', 'rock'],
      ['cobblestone', 'rock'],
      ['rose_bush', 'bush'],
      ['supply_crate', 'crate'],
      ['wine_barrel', 'barrel'],
      ['wooden_signpost', 'sign'],
      ['market_stall', 'stall'],
    ];
    for (const [kind, want] of cases) {
      expect(propVariant(kind), kind).toBe(want);
    }
  });

  it('returns null for unknown / off-menu kinds (procedural fallback path)', () => {
    expect(propVariant('gnome')).toBeNull();
    expect(propVariant('moon-totem')).toBeNull();
    expect(propVariant('')).toBeNull();
    expect(propVariant('xyzzy')).toBeNull();
  });

  it('never resolves a prototype-member kind through the prototype chain', () => {
    for (const evil of ['constructor', 'toString', 'hasOwnProperty', '__proto__']) {
      expect(propVariant(evil), evil).toBeNull();
    }
  });
});

describe('propModel convenience', () => {
  it('returns the registry spec for a known kind and null for an unknown one', () => {
    expect(propModel('bench')).toBe(PROP_MODELS.bench);
    expect(propModel('street_lamp')).toBe(PROP_MODELS.lamp);
    expect(propModel('gnome')).toBeNull();
  });
});

describe('PROP_POOLS (EM-216b variety)', () => {
  it('each pool has ≥2 distinct GLBs and slot 0 is the PROP_MODELS default', () => {
    for (const [kind, pool] of Object.entries(PROP_POOLS)) {
      if (!pool) continue;
      expect(pool.length, kind).toBeGreaterThanOrEqual(2);
      expect(new Set(pool.map((s) => s.url)).size, kind).toBe(pool.length);
      expect(pool[0].url, kind).toBe(PROP_MODELS[kind as PropKind].url);
    }
  });

  it('every pool member is well-formed and exists on disk', () => {
    for (const [kind, pool] of Object.entries(PROP_POOLS)) {
      if (!pool) continue;
      for (const spec of pool) {
        expect(spec.scale, `${kind} ${spec.url}`).toBeGreaterThan(0);
        expect(Number.isFinite(spec.yOffset), `${kind} ${spec.url}`).toBe(true);
        const disk = resolve(PUBLIC_DIR, spec.url.replace(/^\//, ''));
        expect(existsSync(disk), `missing pool GLB: ${disk}`).toBe(true);
      }
    }
  });

  it('propModel picks a stable, distributed pool member from the prop id', () => {
    for (const [kind, pool] of Object.entries(PROP_POOLS)) {
      if (!pool) continue;
      const ids = Array.from({ length: 24 }, (_, i) => `prop_${kind}_${i}`);
      const picks = ids.map((id) => propModel(kind, id));
      for (const p of picks) expect(pool, kind).toContain(p);
      expect(propModel(kind, ids[0])).toBe(propModel(kind, ids[0])); // deterministic
      expect(new Set(picks.map((s) => s!.url)).size, kind).toBeGreaterThan(1); // distributes
    }
  });

  it('propModel without id returns the single PROP_MODELS default (slot 0)', () => {
    for (const kind of Object.keys(PROP_POOLS)) {
      expect(propModel(kind), kind).toBe(PROP_MODELS[kind as PropKind]);
    }
  });
});

describe('ASSET_LICENSES.md (prop reuse recorded)', () => {
  const doc = readFileSync(resolve(REPO_ROOT, 'ASSET_LICENSES.md'), 'utf8');

  it('records every prop GLB file path', () => {
    for (const spec of allPropModelSpecs()) {
      expect(doc, `ASSET_LICENSES.md is missing ${spec.url}`).toContain(
        `web/public${spec.url}`,
      );
    }
  });

  it('notes the Wave K no-new-download reuse', () => {
    expect(doc).toMatch(/Wave K/);
    expect(doc).toMatch(/PROP_MODELS/);
  });
});

// ── Payload guard (EM-248) ───────────────────────────────────────────────────
// models.test.ts caps building specs (allModelSpecs); props are a SEPARATE
// registry, so the per-file 4 MB sanity cap must be asserted here too — else the
// poly-props/ dir this wave expanded is protected by nothing. Same rationale:
// GLBs are lazy-loaded (not first-paint weight), so the cap targets the real
// failure mode (a file vendored without dedup/prune, or mis-compressed), not count.
describe('prop payload guard (EM-248)', () => {
  it('no single vendored prop GLB exceeds the 4 MB per-file sanity cap', () => {
    for (const spec of allPropModelSpecs()) {
      const disk = resolve(PUBLIC_DIR, spec.url.replace(/^\//, ''));
      const bytes = readFileSync(disk).byteLength;
      expect(
        bytes,
        `${spec.url} is ${(bytes / 1024 / 1024).toFixed(1)} MB — repack (dedup/prune, no compression)`,
      ).toBeLessThanOrEqual(4 * 1024 * 1024);
    }
  });
});
