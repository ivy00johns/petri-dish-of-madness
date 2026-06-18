/**
 * propModels.ts — PROP asset registry for Wave K (EM-218) "The Builders' City".
 *
 * Agents (and the god console) place lightweight DECORATIONS — benches, lamps,
 * trees, fences, bins, hydrants, fountains — as first-class `Prop` entities the
 * world tracks (types/index.ts `Prop`). This module is the single source of
 * truth mapping a prop `kind` → a vendored CC0 GLB (ModelSpec), exactly mirror-
 * ing models.ts / cityModels.ts.
 *
 * K0 note (EM-216): this wave wires the prop system to the ALREADY-VENDORED
 * furniture/nature GLBs (Kenney City/Furniture kits + the fantasy-town
 * fountain) — NO new kit downloads. Acquiring a wider Nature/Furniture
 * vocabulary (statues, planters, rocks, flowers…) is the recorded HITL
 * follow-on; the systems here consume it with zero further wiring.
 *
 * `null` is a first-class value (mirrors models.ts): an unknown prop kind →
 * `null` → the renderer draws a small PROCEDURAL fallback marker (never a hole,
 * EM-148 fallback invariant). PROP_MODELS only holds the KNOWN kinds.
 *
 * Scale discipline: every scale below is the SAME measured-and-tested value the
 * city-kit registry uses for that GLB (cityModels.ts CITY_MODEL_REGISTRY), so
 * props read at street-furniture size (0.5–1.2u largest dimension, the fountain
 * ~3.2u as a plaza piece) — cityModels.test.ts already proves those bounds for
 * the shared files; propModels.test.ts re-asserts they exist on disk.
 */

import type { ModelSpec } from './models';

const KENNEY_CITY = '/models/kenney-city';
const KAYKIT_CITY = '/models/kaykit-city';
const KENNEY_FANTASY_TOWN = '/models/kenney-fantasy-town';

/**
 * The KNOWN prop kinds. Every entry resolves to a vendored GLB; emergent /
 * off-menu kinds resolve to `null` (procedural fallback) via {@link propVariant}.
 */
export type PropKind =
  | 'bench'
  | 'lamp'
  | 'tree'
  | 'fence'
  | 'bin'
  | 'hydrant'
  | 'fountain';

/**
 * Prop kind → GLB. Wired to already-vendored furniture/nature/fountain GLBs
 * (shared BY URL with cityModels.ts where applicable — one download, one
 * toonified scene). All seven keys are non-null.
 */
export const PROP_MODELS: Record<PropKind, ModelSpec> = {
  // park bench (Kenney Furniture Kit): 0.47 tall / 0.40 long → ~0.75u / 0.64u.
  bench: { url: `${KENNEY_CITY}/bench.glb`, scale: 1.6, yOffset: 0 },
  // curved streetlight (Kenney City Roads kit): 0.675 tall → ~1.15u.
  lamp: { url: `${KENNEY_CITY}/lamp-curved.glb`, scale: 1.7, yOffset: 0 },
  // city tree (Kenney City Suburban kit, large): 0.767 tall → ~1.19u.
  tree: { url: `${KENNEY_CITY}/tree-large.glb`, scale: 1.55, yOffset: 0 },
  // picket fence segment (Kenney City Suburban kit): 0.475 long → ~1.05u.
  fence: { url: `${KENNEY_CITY}/fence.glb`, scale: 2.2, yOffset: 0 },
  // trashcan (Kenney Furniture Kit): 0.428 tall → ~0.60u.
  bin: { url: `${KENNEY_CITY}/trashcan.glb`, scale: 1.4, yOffset: 0 },
  // fire hydrant (KayKit City Builder Bits): 0.225 tall → ~0.54u.
  hydrant: { url: `${KAYKIT_CITY}/firehydrant.glb`, scale: 2.4, yOffset: 0 },
  // round fountain (Kenney Fantasy Town kit): 2.0 raw → ~3.2u as a plaza piece.
  fountain: { url: `${KENNEY_FANTASY_TOWN}/fountain.glb`, scale: 1.6, yOffset: 0 },
};

/**
 * EM-218: keyword → known prop kind, tried in order with case-insensitive
 * SUBSTRING match on the raw kind (mirrors worldSpace.operationalVariant /
 * VARIANT_KEYWORDS). Order is load-bearing: a substring trap must be resolved
 * by the EARLIER row. (Currently no two prop keywords are substrings of one
 * another, so the order is just stable/intentional.)
 */
const PROP_KEYWORDS: ReadonlyArray<readonly [readonly string[], PropKind]> = [
  [['bench', 'seat', 'pew'], 'bench'],
  [['lamp', 'light', 'streetlight', 'lantern', 'post'], 'lamp'],
  [['tree', 'oak', 'pine', 'shrub', 'bush', 'plant', 'sapling'], 'tree'],
  [['fence', 'railing', 'hedge', 'gate'], 'fence'],
  [['bin', 'trash', 'can', 'bucket', 'barrel'], 'bin'],
  [['hydrant', 'pump'], 'hydrant'],
  [['fountain', 'well', 'water', 'birdbath'], 'fountain'],
];

/**
 * EM-218: resolve a prop `kind` to a KNOWN PropKind, or `null` for an unknown /
 * off-menu kind (the renderer draws a procedural marker). Pure; own-property
 * check so a model-authored kind like 'constructor' can't resolve through the
 * prototype chain, and an exact known kind wins before the keyword scan.
 */
export function propVariant(kind: string): PropKind | null {
  const exact = Object.prototype.hasOwnProperty.call(PROP_MODELS, kind)
    ? (kind as PropKind)
    : null;
  if (exact) return exact;
  const lower = kind.toLowerCase();
  for (const [keywords, propKind] of PROP_KEYWORDS) {
    if (keywords.some((k) => lower.includes(k))) return propKind;
  }
  return null;
}

/**
 * Resolve a prop kind to its GLB spec, or `null` (unknown → procedural
 * fallback). Thin convenience over {@link propVariant} + {@link PROP_MODELS}.
 */
export function propModel(kind: string): ModelSpec | null {
  const v = propVariant(kind);
  return v ? PROP_MODELS[v] : null;
}

/** Every prop GLB spec, de-duped by url (preload + tests). */
export function allPropModelSpecs(): ModelSpec[] {
  const seen = new Set<string>();
  return Object.values(PROP_MODELS).filter((s) =>
    seen.has(s.url) ? false : (seen.add(s.url), true),
  );
}
