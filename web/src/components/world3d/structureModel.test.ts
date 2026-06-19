/**
 * structureModel.test.ts — EM-150 gate for the building→GLB resolution layer.
 * NO canvas/WebGL: everything under test is a pure helper (the React mounting
 * lives in Structure.tsx/Building.tsx; this layer decides WHAT they mount).
 *
 *   • variant→spec wiring: every VariantKey resolves to spec-or-null without
 *     throwing, agreeing exactly with MODEL_REGISTRY (the wiring table);
 *   • evil model-authored kinds ('constructor', '__proto__', …) never resolve
 *     through the prototype chain — this layer guards independently of
 *     operationalVariant's own guard;
 *   • fallback selection: the resolved `variant` is ALWAYS a valid procedural
 *     silhouette key (it is the Suspense fallback whether spec is null or not);
 *   • offline/health tint for the GLB path: structureModelTint feeds <Model>'s
 *     effectiveTint — offline dims, health soots, and the two compose;
 *   • rotation helpers return finite radians for every key and 0 for unknowns.
 */

import { describe, expect, it } from 'vitest';
import type { VariantKey } from './worldSpace';
import type { PlaceKind } from '../../types';
import { MODEL_REGISTRY, PLACE_MODELS } from './assets/models';
import { effectiveTint } from './assets/Model';
import {
  OFFLINE_MODEL_TINT,
  isFundBuilding,
  modelRotationY,
  placeModelRotationY,
  resolvePlaceModel,
  resolveStructureModel,
  structureModelTint,
} from './structureModel';

const ALL_VARIANTS: VariantKey[] = [
  'garden', 'farm', 'workshop', 'library', 'clocktower',
  'house', 'stall', 'monument', 'well', 'zoo', 'generic',
  // EM-216/EM-217 distinct build-type variants
  'tavern', 'market', 'smithy', 'temple', 'school', 'clinic', 'granary',
];
const ALL_PLACE_KINDS: PlaceKind[] = ['social', 'work', 'governance', 'home', 'wild'];

/** Model-authored strings that must never walk the prototype chain. */
const EVIL_KINDS = [
  'constructor', '__proto__', 'prototype', 'hasOwnProperty',
  'toString', 'valueOf', '__defineGetter__',
];

describe('resolveStructureModel', () => {
  it.each(ALL_VARIANTS.map((v) => [v] as const))(
    'kind %s resolves to its registry spec-or-null without throwing',
    (variant) => {
      const res = resolveStructureModel(variant);
      // Exact variant names round-trip (operationalVariant keyword tables map
      // each canonical name onto itself).
      expect(res.variant).toBe(variant);
      expect(res.spec).toBe(MODEL_REGISTRY[variant]);
    },
  );

  it('wires garden/library/zoo to GLBs (EM-216 new kits, were null)', () => {
    expect(resolveStructureModel('garden').spec).not.toBeNull();
    expect(resolveStructureModel('library').spec).not.toBeNull();
    expect(resolveStructureModel('zoo').spec).not.toBeNull();
  });

  it('emergent kinds resolve through the keyword table to a wired spec', () => {
    const forge = resolveStructureModel('dwarven forge');
    expect(forge.variant).toBe('workshop');
    expect(forge.spec).toBe(MODEL_REGISTRY.workshop);
    const bazaar = resolveStructureModel('night bazaar');
    expect(bazaar.variant).toBe('stall');
    expect(bazaar.spec).toBe(MODEL_REGISTRY.stall);
  });

  it.each(EVIL_KINDS.map((k) => [k] as const))(
    'evil kind %s never resolves through the prototype chain',
    (kind) => {
      const res = resolveStructureModel(kind);
      expect(ALL_VARIANTS).toContain(res.variant);
      // Whatever variant the keyword table lands on, the spec must be a
      // genuine registry value — not Object.prototype junk.
      expect(res.spec === null || typeof res.spec.url === 'string').toBe(true);
      expect(res.spec).toBe(MODEL_REGISTRY[res.variant]);
    },
  );

  it('fallback selection: variant is always a valid procedural key', () => {
    for (const kind of [...ALL_VARIANTS, ...EVIL_KINDS, '', 'meow', 'Grand Plaza Hotel']) {
      expect(ALL_VARIANTS).toContain(resolveStructureModel(kind).variant);
    }
  });
});

describe('resolvePlaceModel', () => {
  it.each(ALL_PLACE_KINDS.map((k) => [k] as const))(
    'place kind %s resolves to its registry spec-or-null',
    (kind) => {
      expect(resolvePlaceModel(kind)).toBe(PLACE_MODELS[kind]);
    },
  );

  it('wild wears the EM-216 park gazebo; social wears the city fountain (D1.5)', () => {
    expect(resolvePlaceModel('wild')).not.toBeNull();
    expect(resolvePlaceModel('wild')!.url).toContain('/models/poly/park.glb');
    expect(resolvePlaceModel('social')).not.toBeNull();
    expect(resolvePlaceModel('social')!.url).toContain('fountain');
  });

  it.each(EVIL_KINDS.map((k) => [k] as const))(
    'evil kind %s returns null, never prototype members',
    (kind) => {
      expect(resolvePlaceModel(kind)).toBeNull();
    },
  );

  it('unknown kinds return null', () => {
    expect(resolvePlaceModel('volcano')).toBeNull();
    expect(resolvePlaceModel('')).toBeNull();
  });
});

describe('structureModelTint (GLB offline/health idiom)', () => {
  it('online buildings get no tint override (materials untouched)', () => {
    expect(structureModelTint(false)).toBeUndefined();
    // …which composes with full health to a no-op in <Model>:
    expect(effectiveTint(structureModelTint(false), 100)).toBeNull();
  });

  it('offline returns the dusk-gray dim multiplier', () => {
    expect(structureModelTint(true)).toBe(OFFLINE_MODEL_TINT);
    expect(OFFLINE_MODEL_TINT).toMatch(/^#[0-9a-f]{6}$/);
  });

  function channels(hex: string): number[] {
    return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  }

  it('offline dims relative to white (every channel darker)', () => {
    for (const c of channels(OFFLINE_MODEL_TINT)) {
      expect(c).toBeLessThan(0xff);
      expect(c).toBeGreaterThan(0x40); // dimmed, not blacked out
    }
  });

  it('offline + lost health compose: damaged-offline is darker than offline', () => {
    const offline = effectiveTint(structureModelTint(true), 100)!;
    const offlineDamaged = effectiveTint(structureModelTint(true), 30)!;
    expect(offline).toBe(OFFLINE_MODEL_TINT);
    const a = channels(offline);
    const b = channels(offlineDamaged);
    // soot lerp is monotonic: each channel moves toward charcoal
    expect(b[0]).toBeLessThan(a[0]);
    expect(b[1]).toBeLessThan(a[1]);
    expect(b[2]).toBeLessThan(a[2]);
  });

  it('health alone soots the GLB (the EM-122 semantics through <Model>)', () => {
    const healthy = effectiveTint(structureModelTint(false), 100);
    const hurt = effectiveTint(structureModelTint(false), 40)!;
    expect(healthy).toBeNull(); // pristine = untouched materials
    expect(hurt).toMatch(/^#[0-9a-f]{6}$/);
    for (const c of channels(hurt)) expect(c).toBeLessThan(0xff);
  });
});

describe('rotation helpers', () => {
  it('every variant gets a finite Y rotation (0 when un-overridden)', () => {
    for (const v of ALL_VARIANTS) {
      const r = modelRotationY(v);
      expect(Number.isFinite(r)).toBe(true);
      expect(Math.abs(r)).toBeLessThanOrEqual(Math.PI * 2);
    }
  });

  it('place rotations are finite for every kind and 0 for unknowns/evil', () => {
    for (const k of ALL_PLACE_KINDS) {
      expect(Number.isFinite(placeModelRotationY(k))).toBe(true);
    }
    for (const k of EVIL_KINDS) expect(placeModelRotationY(k)).toBe(0);
    expect(placeModelRotationY('volcano')).toBe(0);
  });
});

describe('isFundBuilding (EM-180)', () => {
  const b = (name: string, kind: string) => ({ name, kind });

  it('flags fund-ish names', () => {
    expect(isFundBuilding(b('Community Commons Fund', 'commons'))).toBe(true);
    expect(isFundBuilding(b('Relief Treasury', 'building'))).toBe(true);
    expect(isFundBuilding(b('The Coffers', 'building'))).toBe(true);
    expect(isFundBuilding(b('Winter Reserve', 'monument'))).toBe(true);
  });

  it('flags fund-ish kinds even when the name is plain', () => {
    expect(isFundBuilding(b('Old Stone Vault', 'endowment'))).toBe(true);
    expect(isFundBuilding(b('Pooled Pot', 'treasury'))).toBe(true);
    expect(isFundBuilding(b('The Stash', 'warchest'))).toBe(true);
  });

  it('leaves ordinary buildings alone', () => {
    expect(isFundBuilding(b('Village Clock Tower', 'clocktower'))).toBe(false);
    expect(isFundBuilding(b('The Commons Park', 'wild'))).toBe(false);
    expect(isFundBuilding(b("Ada's Cottage", 'house'))).toBe(false);
    expect(isFundBuilding(b('Old Library', 'library'))).toBe(false);
  });

  it('respects word boundaries (no false hits on refund/founders)', () => {
    expect(isFundBuilding(b('Refund Booth', 'stall'))).toBe(false);
    expect(isFundBuilding(b("Founders' Statue", 'monument'))).toBe(false);
  });
});
