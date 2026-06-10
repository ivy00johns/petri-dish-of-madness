/**
 * models.ts — THE GLB asset registry for the cozy village (EM-148).
 *
 * Single source of truth mapping renderer concepts → vendored CC0 models
 * under web/public/models/ (every file recorded in ASSET_LICENSES.md).
 * `null` is a first-class value: it means "stay procedural" — the Wave B
 * procedural mesh keeps rendering (it is ALSO the Suspense fallback while a
 * non-null model streams in, per the Wave C fallback invariant).
 *
 * Scale discipline (load-bearing): building slot rings space structures
 * 4.2 world units apart and buildings must read at ≲3 units; villagers are
 * ~1.1-unit capsules; critters ~0.5–0.65. Every `scale` below was derived
 * from the GLB's measured bounding box (see models.test.ts, which re-measures
 * the vendored files and enforces these bounds — change a model, the test
 * tells you if it stops fitting).
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

const KAYKIT_MEDIEVAL = '/models/kaykit-medieval-hexagon';
const KAYKIT_ADVENTURERS = '/models/kaykit-adventurers';
const KENNEY_FANTASY_TOWN = '/models/kenney-fantasy-town';
const QUATERNIUS = '/models/quaternius';

/**
 * Operational-building models, keyed by EM-122's `operationalVariant(kind)`.
 * All 10 VariantKeys are present; `null` keeps the procedural silhouette
 * (garden's flower beds and the library have no good CC0 match in the
 * headlessly-acquirable kits — recorded in the EM-148 report).
 */
export const MODEL_REGISTRY: Record<VariantKey, ModelSpec | null> = {
  // KayKit buildings are authored at hex-tile scale (~0.7–1.4 units wide),
  // hence the 1.7–2.8× scales to read at ~2–2.9 world units.
  garden: null, // procedural flower beds stay — no CC0 garden kit acquired
  farm: { url: `${KAYKIT_MEDIEVAL}/building_windmill.glb`, scale: 2.3, yOffset: 0 },
  workshop: { url: `${KAYKIT_MEDIEVAL}/building_blacksmith.glb`, scale: 2.2, yOffset: 0 },
  library: null, // no CC0 library model in the acquired kits — stays procedural
  clocktower: { url: `${KAYKIT_MEDIEVAL}/building_tower.glb`, scale: 1.7, yOffset: 0 },
  house: { url: `${KAYKIT_MEDIEVAL}/building_home_a.glb`, scale: 2.8, yOffset: 0 },
  stall: { url: `${KENNEY_FANTASY_TOWN}/stall.glb`, scale: 2.3, yOffset: 0 },
  monument: { url: `${KENNEY_FANTASY_TOWN}/fountain.glb`, scale: 1.3, yOffset: 0 },
  well: { url: `${KAYKIT_MEDIEVAL}/building_well.glb`, scale: 2.3, yOffset: 0 },
  generic: { url: `${KAYKIT_MEDIEVAL}/building_tavern.glb`, scale: 2.1, yOffset: 0 },
};

/**
 * Place-anchor models keyed by PlaceKind (the structure that marks a place
 * itself, not the agent-built satellites). Anchors may read slightly larger
 * than ring buildings. `null` = the existing procedural place structure.
 */
export const PLACE_MODELS: Record<PlaceKind, ModelSpec | null> = {
  social: null, // the plaza is an open square — procedural stays
  work: { url: `${KAYKIT_MEDIEVAL}/building_lumbermill.glb`, scale: 2.0, yOffset: 0 },
  governance: { url: `${KAYKIT_MEDIEVAL}/building_castle.glb`, scale: 1.25, yOffset: 0 },
  home: { url: `${KAYKIT_MEDIEVAL}/building_home_b.glb`, scale: 2.3, yOffset: 0 },
  wild: null, // the commons keeps its procedural wilds
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
