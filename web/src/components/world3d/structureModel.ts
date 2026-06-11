/**
 * structureModel.ts — EM-150 pure helpers wiring buildings to the EM-148 GLB
 * registry. NO React/canvas here: this is the testable resolution layer between
 * the renderer components (Structure.tsx / Building.tsx) and the asset layer.
 *
 *   • resolveStructureModel(kind) — building kind → { variant, spec }:
 *     `variant` names the EM-122 procedural silhouette (ALWAYS valid — it is
 *     the Suspense fallback whether or not a GLB exists), `spec` is the GLB to
 *     stream in (null = stay procedural, a first-class registry value).
 *   • resolvePlaceModel(kind) — place kind → anchor spec-or-null, same rules.
 *   • structureModelTint(offline) — the GLB equivalent of the procedural
 *     offline idiom (extinguished glows): toonified GLBs carry no emissive
 *     materials, so "offline" reads as a whole-model multiplicative dim
 *     instead. Composes with <Model health={…}> (EM-122 soot) downstream.
 *   • modelRotationY(variant) / placeModelRotationY(kind) — per-variant facing
 *     fixes (spec.rotation is unset in the wave-1 registry; these were
 *     eyeballed in the browser against the default (24, 22, 24) camera, which
 *     looks at the village from +X/+Z — fronts should face roughly +Z/+X).
 *
 * Kinds are MODEL-AUTHORED strings (agents invent them), so every lookup here
 * is own-property guarded: 'constructor' / '__proto__' must never resolve
 * through the prototype chain (same hardening as worldSpace.operationalVariant
 * and buildingStyle — this layer guards independently, belt and braces).
 */

import { MODEL_REGISTRY, PLACE_MODELS, type ModelSpec } from './assets/models';
import { operationalVariant, type VariantKey } from './worldSpace';

export interface StructureModelResolution {
  /** The EM-122 procedural silhouette — always the Suspense fallback. */
  variant: VariantKey;
  /** The GLB to render when non-null; null = render the procedural variant. */
  spec: ModelSpec | null;
}

/**
 * Resolve which GLB (if any) an OPERATIONAL building of `kind` renders.
 * Never throws — evil/emergent kinds fall through operationalVariant to
 * 'generic', and the registry lookup is own-property guarded on top.
 */
export function resolveStructureModel(kind: string): StructureModelResolution {
  const variant = operationalVariant(kind);
  const spec = Object.prototype.hasOwnProperty.call(MODEL_REGISTRY, variant)
    ? MODEL_REGISTRY[variant]
    : null;
  return { variant, spec: spec ?? null };
}

/**
 * Resolve a place-anchor GLB by place kind (Building.tsx). Unknown kinds (or
 * registry nulls — wild stays procedural by design) return null.
 */
export function resolvePlaceModel(kind: string): ModelSpec | null {
  const spec = Object.prototype.hasOwnProperty.call(PLACE_MODELS, kind)
    ? PLACE_MODELS[kind as keyof typeof PLACE_MODELS]
    : null;
  return spec ?? null;
}

/**
 * The offline dim multiplier for GLB buildings. The procedural offline idiom
 * extinguishes every emissive glow (windows/lanterns go WINDOW_OFF); toon-
 * converted GLBs have no emissives to extinguish, so the same "lights out"
 * read comes from multiplying every material color by this cool dusk gray
 * (applyTintToScene semantics: white = untouched, so ~55% luminance with the
 * warmth pulled out reads clearly shuttered next to a lit neighbor).
 */
export const OFFLINE_MODEL_TINT = '#878a92';

/**
 * The `tint` prop for <Model> on the operational/offline status path.
 * undefined keeps materials untouched; <Model> composes this with `health`
 * via worldSpace.healthTint, so an offline AND damaged GLB dims and soots.
 */
export function structureModelTint(offline: boolean): string | undefined {
  return offline ? OFFLINE_MODEL_TINT : undefined;
}

/**
 * Per-variant Y-rotation (radians) so each GLB's doorway/front reads toward
 * the default camera. Registry specs ship rotation unset; the EM-150 probe
 * methodology (render each GLB from the default +X/+Z azimuth at 0/±90/180)
 * found the Kenney kits author detail faces — storefront doors, fountain —
 * toward +Z/+X, which IS the default camera side (same convention the
 * cityModels.ts pieces rely on). Every variant therefore keeps rotation 0;
 * this table stays as the tuning point if a later kit swap reads backwards.
 */
const MODEL_ROTATION_Y: Partial<Record<VariantKey, number>> = {};

/** Y rotation (radians) applied around a building GLB; 0 when unneeded. */
export function modelRotationY(variant: VariantKey): number {
  const rot = Object.prototype.hasOwnProperty.call(MODEL_ROTATION_Y, variant)
    ? MODEL_ROTATION_Y[variant]
    : undefined;
  return rot ?? 0;
}

/** Same idea for place anchors (same probe: all read fine as authored). */
const PLACE_ROTATION_Y: Record<string, number> = {};

export function placeModelRotationY(kind: string): number {
  const rot = Object.prototype.hasOwnProperty.call(PLACE_ROTATION_Y, kind)
    ? PLACE_ROTATION_Y[kind]
    : undefined;
  return rot ?? 0;
}
