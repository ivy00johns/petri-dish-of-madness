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
// EM-216 new-kit acquisition: CC0 props vendored from poly.pizza (Quaternius /
// Kenney / Isa Lousberg mirrors — every file recorded in ASSET_LICENSES.md).
const POLY_PROPS = '/models/poly-props';

/**
 * The KNOWN prop kinds. Every entry resolves to a vendored GLB; emergent /
 * off-menu kinds resolve to `null` (procedural fallback) via {@link propVariant}.
 *
 * EM-216 expanded the original 7 reused-GLB kinds with 9 net-new CC0 props
 * (statue, planter, flower, rock, bush, crate, barrel, sign, stall) so an agent
 * dropping a "statue" or "market stall" in the plaza renders real distinct art.
 */
export type PropKind =
  | 'bench'
  | 'lamp'
  | 'tree'
  | 'fence'
  | 'bin'
  | 'hydrant'
  | 'fountain'
  // ── EM-216 new-kit props (poly.pizza CC0) ──
  | 'statue'
  | 'planter'
  | 'flower'
  | 'rock'
  | 'bush'
  | 'crate'
  | 'barrel'
  | 'sign'
  | 'stall';

/**
 * Prop kind → GLB. The first seven reuse already-vendored Kenney/KayKit GLBs
 * (shared BY URL with cityModels.ts — one download, one toonified scene); the
 * rest are EM-216's net-new CC0 poly.pizza props. Every key is non-null;
 * scales fit street-furniture size (largest dim ~0.5–1.5u), yOffsets seat
 * origin-centered models (crate/bush) on the ground.
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
  // ── EM-216 new-kit props (poly.pizza CC0; measured longest dim in comments) ──
  // Quaternius Fox Statue: 3.752 tall → ~1.6u plaza statue.
  statue: { url: `${POLY_PROPS}/statue.glb`, scale: 0.43, yOffset: 0 },
  // Isa Lousberg Medium Pot: 1.0 → ~0.7u planter.
  planter: { url: `${POLY_PROPS}/planter.glb`, scale: 0.7, yOffset: 0 },
  // Quaternius Flowers (patch of 7): 3.594 wide → ~1.1u flower bed.
  flower: { url: `${POLY_PROPS}/flower.glb`, scale: 0.31, yOffset: 0 },
  // Quaternius Rocks: 0.304 → ~0.6u rock cluster.
  rock: { url: `${POLY_PROPS}/rock.glb`, scale: 2.0, yOffset: 0 },
  // Quaternius Bush (origin-centered, min.y -0.289): 2.069 → ~0.9u; lift to ground.
  bush: { url: `${POLY_PROPS}/bush.glb`, scale: 0.44, yOffset: 0.13 },
  // Quaternius Cube Crate (origin-centered, min.y -1.01): 2.021 → ~0.6u; lift to ground.
  crate: { url: `${POLY_PROPS}/crate.glb`, scale: 0.3, yOffset: 0.3 },
  // Kenney Barrel: 0.76 → ~0.65u.
  barrel: { url: `${POLY_PROPS}/barrel.glb`, scale: 0.85, yOffset: 0 },
  // Kenney Signpost Single: 0.46 tall → ~0.92u signpost.
  sign: { url: `${POLY_PROPS}/sign.glb`, scale: 2.0, yOffset: 0 },
  // Quaternius Market Stand: 1.154 → ~1.4u vendor stall.
  stall: { url: `${POLY_PROPS}/stall.glb`, scale: 1.2, yOffset: 0 },
};

/**
 * EM-218: keyword → known prop kind, tried in order with case-insensitive
 * SUBSTRING match on the raw kind (mirrors worldSpace.operationalVariant /
 * VARIANT_KEYWORDS). Order is LOAD-BEARING — substring traps are resolved by
 * the EARLIER row:
 *   - 'sign'/'signpost' beats lamp's 'post' ("signpost" ⊃ "post");
 *   - 'barrel' beats bin (a barrel is its own prop, not a bin);
 *   - tree keeps 'shrub' so "flowering_shrub" → tree, while 'flower' sits AFTER
 *     tree so "flowering_shrub" never grabs the flower row;
 *   - 'fountain' beats rock's 'stone' so "stone_fountain" → fountain.
 */
const PROP_KEYWORDS: ReadonlyArray<readonly [readonly string[], PropKind]> = [
  [['bench', 'seat', 'pew'], 'bench'],
  [['sign', 'signpost', 'placard', 'noticeboard'], 'sign'],
  [['lamp', 'streetlight', 'lantern', 'light', 'post'], 'lamp'],
  [['planter', 'potted', 'flowerpot'], 'planter'],
  [['bush', 'shrubbery'], 'bush'],
  [['tree', 'oak', 'pine', 'shrub', 'sapling', 'plant'], 'tree'],
  [['flower', 'blossom', 'tulip', 'petal', 'bloom'], 'flower'],
  [['fence', 'railing', 'hedge', 'gate'], 'fence'],
  [['barrel', 'keg', 'cask'], 'barrel'],
  [['crate', 'box', 'chest', 'pallet'], 'crate'],
  [['bin', 'trash', 'rubbish', 'can', 'bucket'], 'bin'],
  [['hydrant', 'pump'], 'hydrant'],
  [['stall', 'stand', 'kiosk', 'booth', 'market'], 'stall'],
  [['statue', 'sculpture', 'bust', 'effigy'], 'statue'],
  [['fountain', 'well', 'water', 'birdbath'], 'fountain'],
  [['rock', 'boulder', 'pebble', 'stone'], 'rock'],
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
