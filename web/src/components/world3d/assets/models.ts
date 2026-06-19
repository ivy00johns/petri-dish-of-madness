/**
 * models.ts — THE GLB asset registry for the cozy 3-D CITY (EM-148, re-aimed
 * by Wave D1.5: the medieval village look is retired; the sim lives on a
 * compact dense city grid, so place anchors and agent-built structures wear
 * the same Kenney city kits as the generated blocks).
 *
 * Single source of truth mapping renderer concepts → vendored CC0 models
 * under web/public/models/ (every file recorded in ASSET_LICENSES.md).
 * `null` is a first-class value: it means "stay procedural" — the Wave B
 * procedural mesh keeps rendering (it is ALSO the Suspense fallback while a
 * non-null model streams in, per the Wave C fallback invariant).
 *
 * Scale discipline (load-bearing): building slot rings space structures
 * 4.2 world units apart and buildings must stay ≤3.4 units on the long side
 * (the Wave D1 city convention); villagers are ~1.1-unit capsules; critters
 * ~0.5–0.65. Every `scale` below was derived from the GLB's measured bounding
 * box (see models.test.ts, which re-measures the vendored files and enforces
 * these bounds — change a model, the test tells you if it stops fitting).
 * City-kit GLBs are shared with cityModels.ts BY URL (one download, one
 * toonified scene) but carry their own scale rows here — anchors may read
 * ~15% larger than ring buildings per the Wave C convention.
 *
 * Consumers (wave 2):
 *   • C4 Structure/Building → MODEL_REGISTRY[operationalVariant(kind)]
 *   • C4 place anchors      → PLACE_MODELS[place.kind]
 *   • C5 Villager/Critter   → CHARACTER_MODELS.villager / .cat / .dog
 *     (animation clip names live in `clips`; play `clips.idle` at rest and
 *     `clips.walk` while the position lerp is in flight.)
 */

import type { VariantKey } from '../worldSpace';
import type { PlaceKind } from '../../../types';

export interface ModelSpec {
  /** Public URL under /models/ (drei useGLTF fetches it). */
  url: string;
  /** Uniform scale that fits the model into its village footprint. */
  scale: number;
  /** Lift above ground (world units, AFTER scaling). 0 for ground-flush kits. */
  yOffset: number;
  /** Optional Y rotation (radians) to face the model "forward". */
  rotation?: number;
  /** Animation clip names (rigged characters only). */
  clips?: { idle?: string; walk?: string };
}

const KAYKIT_ADVENTURERS = '/models/kaykit-adventurers';
const KENNEY_FANTASY_TOWN = '/models/kenney-fantasy-town';
const KENNEY_CITY = '/models/kenney-city';
const QUATERNIUS = '/models/quaternius';
// EM-216 new-kit acquisition: CC0 building/anchor GLBs vendored from poly.pizza
// (Quaternius / Kenney mirrors). Fills the recorded garden/library/zoo nulls
// and the wild anchor, and gives the EM-217 build-type catalog distinct meshes.
const POLY = '/models/poly';

/**
 * Operational-building models, keyed by EM-122's `operationalVariant(kind)`.
 * All 10 VariantKeys are present; `null` keeps the procedural silhouette
 * (garden's flower beds and the library have no good CC0 match in the
 * headlessly-acquirable kits — recorded in the EM-148 report).
 *
 * Wave D1.5: agent-built structures wear the Kenney city kits (measured
 * bounds in cityModels.ts): ind_b 1.322 long, ind_a 1.678, res_a 1.300,
 * com_a 0.940 (1.293 tall), civic_a 2.320 (2.480 tall), com_b 0.970
 * (1.693 tall), fountain 2.000. All land at 2.3–3.4u long, ≤4.1u tall.
 */
export const MODEL_REGISTRY: Record<VariantKey, ModelSpec | null> = {
  // EM-216: Quaternius "Crops" plot → ~2.95u garden bed (was procedural null).
  garden: { url: `${POLY}/garden.glb`, scale: 1.65, yOffset: 0 },
  farm: { url: `${KENNEY_CITY}/industrial-h.glb`, scale: 2.4, yOffset: 0 }, // warehouse → 3.17u
  workshop: { url: `${KENNEY_CITY}/industrial-g.glb`, scale: 2.0, yOffset: 0 }, // factory → 3.36u
  // EM-216: Quaternius "Town Center" → ~2.97u civic hall (was procedural null).
  library: { url: `${POLY}/library.glb`, scale: 2.35, yOffset: 0 },
  clocktower: { url: `${KENNEY_CITY}/civic-n.glb`, scale: 1.45, yOffset: 0 }, // civic landmark → 3.36u, 3.60u tall
  house: { url: `${KENNEY_CITY}/suburban-a.glb`, scale: 2.3, yOffset: 0 }, // → 2.99u
  stall: { url: `${KENNEY_CITY}/commercial-a.glb`, scale: 2.6, yOffset: 0 }, // storefront → 2.44u
  monument: { url: `${KENNEY_FANTASY_TOWN}/fountain.glb`, scale: 1.3, yOffset: 0 }, // → 2.60u
  well: { url: `${KENNEY_FANTASY_TOWN}/fountain.glb`, scale: 1.3, yOffset: 0 }, // city fountain → 2.60u
  // EM-216: Quaternius "Open Barn" → ~3.21u animal enclosure (was procedural null).
  zoo: { url: `${POLY}/zoo.glb`, scale: 0.52, yOffset: 0 },
  generic: { url: `${KENNEY_CITY}/commercial-g.glb`, scale: 2.4, yOffset: 0 }, // tall commercial → 2.33u, 4.06u tall
  // ── EM-216/EM-217: distinct per-build-type GLBs (poly.pizza CC0). Measured
  //    longest-XZ × scale lands each in the (1.2, 3.4]u city footprint, height
  //    ≤4.2u (granary/temple are the tall ones). ──
  tavern: { url: `${POLY}/tavern.glb`, scale: 0.78, yOffset: 0 }, // Fantasy Inn → 3.14u, 2.72u tall
  market: { url: `${POLY}/market.glb`, scale: 1.4, yOffset: 0 }, // Village Market stalls → 2.95u
  smithy: { url: `${POLY}/smithy.glb`, scale: 0.8, yOffset: 0 }, // Blacksmith forge → 3.11u
  temple: { url: `${POLY}/temple.glb`, scale: 0.92, yOffset: 0 }, // columned Temple → 2.02u, 3.98u tall
  school: { url: `${POLY}/school.glb`, scale: 1.65, yOffset: 0 }, // Kenney Small Building → 2.71u
  clinic: { url: `${POLY}/clinic.glb`, scale: 1.45, yOffset: 0 }, // Kenney Large Building → 2.96u
  granary: { url: `${POLY}/granary.glb`, scale: 0.45, yOffset: 0 }, // Silo House → 2.40u, 4.08u tall
};

/**
 * Place-anchor models keyed by PlaceKind (the structure that marks a place
 * itself, not the agent-built satellites). Anchors may read slightly larger
 * than ring buildings (~15%, Wave C convention) but stay ≤3.4u on the long
 * side. `null` = the existing procedural place structure.
 */
export const PLACE_MODELS: Record<PlaceKind, ModelSpec | null> = {
  // The Kenney fantasy-town fountain reads fine as a city plaza fountain
  // (2.000 raw → 3.20u at anchor scale, vs 2.60u as a ring building).
  social: { url: `${KENNEY_FANTASY_TOWN}/fountain.glb`, scale: 1.6, yOffset: 0 },
  work: { url: `${KENNEY_CITY}/commercial-e.glb`, scale: 2.0, yOffset: 0 }, // wide storefront → 3.28u
  governance: { url: `${KENNEY_CITY}/civic-n.glb`, scale: 1.45, yOffset: 0 }, // grand civic block → 3.36u
  home: { url: `${KENNEY_CITY}/suburban-b.glb`, scale: 1.8, yOffset: 0 }, // → 3.29u
  // EM-216: Quaternius "Gazebo" park hero → ~2.90u (was procedural null).
  wild: { url: `${POLY}/park.glb`, scale: 2.3, yOffset: 0 },
};

/**
 * Rigged characters. The villager is KayKit's Rogue (weapon prop nodes
 * stripped at vendor time); cat/dog are Quaternius. Clip names are exact
 * (case-sensitive) — full per-model clip lists are in ASSET_LICENSES.md's
 * companion notes and the EM-148 report.
 */
export const CHARACTER_MODELS: {
  villager: ModelSpec | null;
  cat: ModelSpec | null;
  dog: ModelSpec | null;
} = {
  // 2.19u tall at scale 1 → ~1.1u, matching the Wave B capsule.
  villager: {
    url: `${KAYKIT_ADVENTURERS}/villager.glb`,
    scale: 0.5,
    yOffset: 0,
    clips: { idle: 'Idle', walk: 'Walking_A' },
  },
  cat: {
    url: `${QUATERNIUS}/cat.glb`,
    scale: 0.28,
    yOffset: 0,
    clips: { idle: 'Idle', walk: 'Walk' },
  },
  dog: {
    url: `${QUATERNIUS}/dog.glb`,
    scale: 0.32,
    yOffset: 0,
    clips: { idle: 'Idle', walk: 'Walk' },
  },
};

/** Every non-null spec across the three registries (preload + tests). */
export function allModelSpecs(): ModelSpec[] {
  const specs = [
    ...Object.values(MODEL_REGISTRY),
    ...Object.values(PLACE_MODELS),
    ...Object.values(CHARACTER_MODELS),
  ].filter((s): s is ModelSpec => s !== null);
  // De-dupe by url (a model may serve several keys).
  const seen = new Set<string>();
  return specs.filter((s) => (seen.has(s.url) ? false : (seen.add(s.url), true)));
}
