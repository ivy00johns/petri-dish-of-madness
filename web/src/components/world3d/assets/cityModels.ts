/**
 * cityModels.ts — GLB registry for the generated city ring (EM-152, Wave D1a).
 *
 * Maps every frozen `CityPieceKey` (contracts/wave-d1.md) to a vendored CC0
 * model under web/public/models/kenney-city/ (+ kaykit-city/ for the one prop
 * Kenney doesn't ship). `null` is first-class: it means "the renderer skips
 * this piece" (rule 10 — never a hole, never a crash). All 23 keys are
 * currently non-null.
 *
 * Scale discipline (contract-frozen, §D1a):
 *   • road tiles land at EXACTLY TILE = 2.6 world units square — Kenney City
 *     Kit Roads tiles are authored at exactly 1×1, so every road scale is 2.6;
 *   • buildings ≤ 3.4 world units on the long (XZ) side;
 *   • street props 0.4–1.2 (largest dimension);
 *   • cars ~1.6 units long (parked; ambient traffic is EM-169 / W17).
 * Every `scale` below was derived from the GLB's measured bounding box;
 * cityModels.test.ts re-measures the vendored bytes and enforces these bounds.
 *
 * Sources (all CC0, license text verified in each archive before vendoring —
 * see ASSET_LICENSES.md): Kenney City Kit Roads 2.0 / Commercial 2.1 /
 * Suburban 2.0 / Industrial 1.0, Kenney Car Kit 3.1, Kenney Furniture Kit 2.0,
 * KayKit City Builder Bits 1.0 (fire hydrant only).
 */

import type { ModelSpec } from './models';
import type { CityPieceKey } from '../cityLayout';

const KENNEY_CITY = '/models/kenney-city';
const KAYKIT_CITY = '/models/kaykit-city';

/**
 * One entry per frozen CityPieceKey. Renderer contract (D1d): non-null →
 * instanced GLB; null → skip silently. Road pieces are authored "open end
 * faces ±Z/±X" in Kenney's convention; D1b's generator owns rotations.
 */
export const CITY_MODEL_REGISTRY: Record<CityPieceKey, ModelSpec | null> = {
  // ── roads — Kenney tiles are exactly 1×1×0.02, so 2.6 ⇒ the frozen TILE ──
  road_straight: { url: `${KENNEY_CITY}/road-straight.glb`, scale: 2.6, yOffset: 0 },
  road_corner: { url: `${KENNEY_CITY}/road-bend.glb`, scale: 2.6, yOffset: 0 },
  road_tee: { url: `${KENNEY_CITY}/road-intersection.glb`, scale: 2.6, yOffset: 0 },
  road_cross: { url: `${KENNEY_CITY}/road-crossroad.glb`, scale: 2.6, yOffset: 0 },
  road_end: { url: `${KENNEY_CITY}/road-end-round.glb`, scale: 2.6, yOffset: 0 },

  // ── commercial (City Kit Commercial 2.1) ────────────────────────────────
  // building-a: 0.884×0.940 → 2.44u; building-g: 0.970×0.922 → 2.33u (tall);
  // building-e: 1.640×1.008 → 3.28u wide storefront.
  com_a: { url: `${KENNEY_CITY}/commercial-a.glb`, scale: 2.6, yOffset: 0 },
  com_b: { url: `${KENNEY_CITY}/commercial-g.glb`, scale: 2.4, yOffset: 0 },
  com_c: { url: `${KENNEY_CITY}/commercial-e.glb`, scale: 2.0, yOffset: 0 },

  // ── residential (City Kit Suburban 2.0) ─────────────────────────────────
  // type-a: 1.300 → 2.99u; type-b: 1.828 → 3.29u; type-q: 1.240 → 2.85u.
  res_a: { url: `${KENNEY_CITY}/suburban-a.glb`, scale: 2.3, yOffset: 0 },
  res_b: { url: `${KENNEY_CITY}/suburban-b.glb`, scale: 1.8, yOffset: 0 },
  res_c: { url: `${KENNEY_CITY}/suburban-q.glb`, scale: 2.3, yOffset: 0 },

  // ── industrial (City Kit Industrial 1.0) ────────────────────────────────
  // building-g: 1.678 → 3.36u factory; building-h: 1.322 → 3.17u warehouse.
  ind_a: { url: `${KENNEY_CITY}/industrial-g.glb`, scale: 2.0, yOffset: 0 },
  ind_b: { url: `${KENNEY_CITY}/industrial-h.glb`, scale: 2.4, yOffset: 0 },

  // ── civic — Commercial 2.1's grandest block (2.320×1.820 → 3.36u) ───────
  civic_a: { url: `${KENNEY_CITY}/civic-n.glb`, scale: 1.45, yOffset: 0 },

  // ── street furniture + greenery (props 0.4–1.2) ─────────────────────────
  // streetlight (Roads kit): 0.675 tall → 1.15u.
  lamp: { url: `${KENNEY_CITY}/lamp-curved.glb`, scale: 1.7, yOffset: 0 },
  // park bench (Furniture Kit): 0.47 tall / 0.40 long → 0.75u / 0.64u.
  bench: { url: `${KENNEY_CITY}/bench.glb`, scale: 1.6, yOffset: 0 },
  // fire hydrant (KayKit City Builder Bits): 0.225 tall → 0.54u.
  hydrant: { url: `${KAYKIT_CITY}/firehydrant.glb`, scale: 2.4, yOffset: 0 },
  // trashcan (Furniture Kit): 0.428 tall → 0.60u.
  bin: { url: `${KENNEY_CITY}/trashcan.glb`, scale: 1.4, yOffset: 0 },
  // picket fence segment (Suburban kit): 0.475 long → 1.05u.
  fence: { url: `${KENNEY_CITY}/fence.glb`, scale: 2.2, yOffset: 0 },
  // city tree (Suburban kit, large): 0.767 tall → 1.19u.
  tree_city: { url: `${KENNEY_CITY}/tree-large.glb`, scale: 1.55, yOffset: 0 },

  // ── parked cars (Car Kit 3.1) — long axis is Z, ~1.6u after scaling ──────
  car_a: { url: `${KENNEY_CITY}/car-sedan.glb`, scale: 0.63, yOffset: 0 },
  car_b: { url: `${KENNEY_CITY}/car-suv.glb`, scale: 0.59, yOffset: 0 },
  car_c: { url: `${KENNEY_CITY}/car-taxi.glb`, scale: 0.58, yOffset: 0 },
};

/** Every non-null city spec, de-duped by url (preload + tests). */
export function allCityModelSpecs(): ModelSpec[] {
  const seen = new Set<string>();
  return Object.values(CITY_MODEL_REGISTRY)
    .filter((s): s is ModelSpec => s !== null)
    .filter((s) => (seen.has(s.url) ? false : (seen.add(s.url), true)));
}
