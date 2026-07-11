/**
 * decalLayout.ts — EM-302b pure placement math for SurfaceDecal (the EM-298
 * agent-painted facade mural). NO React/canvas here: this is the testable
 * layer between CozyWorld/SurfaceDecal and the asset registry, mirroring
 * structureModel.ts.
 *
 * THE DEFECT (EM-302b): the decal plane sat at a FIXED z=1.06 in front of the
 * building group. Real fronts vary wildly — the theater GLB's face lands at
 * z≈1.95 (decal buried inside the mesh), Kenney suburban houses at z≈1.18
 * (z-fighting/swallowed), the dock's whole hull sits in −z (decal floating
 * ~1.7u in the air) — and short models (garden bed top ≈0.52u) left the
 * 1.35-high mural hovering above the roofline.
 *
 * THE FIX: place the plane AT the measured front face plus a small
 * surface-normal epsilon (the plane's normal is +z, so the epsilon is applied
 * along +z), and clamp/shrink the canvas vertically to the measured height.
 * Front faces come from `GLB_DECAL_BOUNDS` — RAW model-space AABBs measured
 * from the vendored GLBs (decalLayout.test.ts re-measures the files and fails
 * if this table drifts, the models.test.ts discipline) — scaled by the SAME
 * resolved spec the Structure renderer uses (resolveStructureModel), with the
 * spec/variant Y-rotation folded in. Statuses that render procedurally fall
 * back to per-variant silhouette fronts (Suspense-fallback moments + damaged),
 * and anything unresolvable keeps the legacy 1.06 — never a crash, never a
 * hole.
 */

import type { Building } from '../../types';
import { modelRotationY, resolveStructureModel } from './structureModel';
import type { VariantKey } from './worldSpace';

/** Decal canvas size [w, h] — the modest mural plane (pre-EM-302 constant). */
export const DECAL_SIZE: [number, number] = [1.5, 1.1];

/** Default mural center height (the pre-EM-302 constant) — tall facades keep it. */
export const DECAL_BASE_Y = 1.35;

/**
 * The surface-normal epsilon: the plane sits this far along its +z normal off
 * the measured face. Big enough to clear depth-buffer z-fighting at the
 * village camera distances (the old 0.01 gap visibly fought), small enough to
 * still read as painted ON the wall.
 */
export const DECAL_EPSILON = 0.05;

/** The pre-EM-302 fixed offset — kept as the unresolvable-case fallback. */
export const LEGACY_DECAL_Z = 1.06;

/**
 * DamagedStructure's front: a 2.4-deep scorched box (face z=1.2) under a
 * [0.06, 0, −0.05] group tilt (≈+0.1 lean at mural height) + the scorch-scar
 * plane at z=1.22.
 */
export const DAMAGED_FRONT_Z = 1.32;

/** Raw model-space AABB extents of a vendored building GLB (scale/yOffset NOT
 * applied — the resolved ModelSpec supplies those at lookup time). */
export interface DecalBounds {
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
  maxY: number;
}

/**
 * MEASURED raw bounds for every building GLB url in MODEL_REGISTRY +
 * MODEL_POOLS (generated from the vendored files with the models.test.ts GLB
 * reader; decalLayout.test.ts re-measures and enforces coverage + values, so
 * a swapped model file fails loudly instead of mis-placing murals).
 */
export const GLB_DECAL_BOUNDS: Record<string, DecalBounds> = {
  '/models/kenney-city/civic-n.glb': { minX: -1.16, maxX: 1.16, minZ: -0.91, maxZ: 0.91, maxY: 2.48 },
  '/models/kenney-city/commercial-a.glb': { minX: -0.442, maxX: 0.442, minZ: -0.47, maxZ: 0.47, maxY: 1.293 },
  '/models/kenney-city/commercial-e.glb': { minX: -0.82, maxX: 0.82, minZ: -0.504, maxZ: 0.504, maxY: 0.893 },
  '/models/kenney-city/commercial-g.glb': { minX: -0.485, maxX: 0.485, minZ: -0.461, maxZ: 0.461, maxY: 1.693 },
  '/models/kenney-city/industrial-g.glb': { minX: -0.839, maxX: 0.839, minZ: -0.642, maxZ: 0.642, maxY: 1.28 },
  '/models/kenney-city/industrial-h.glb': { minX: -1.242, maxX: 0.08, minZ: -0.376, maxZ: 0.934, maxY: 0.734 },
  '/models/kenney-city/suburban-a.glb': { minX: -0.65, maxX: 0.65, minZ: -0.514, maxZ: 0.514, maxY: 0.834 },
  '/models/kenney-city/suburban-b.glb': { minX: -0.914, maxX: 0.914, minZ: -0.57, maxZ: 0.57, maxY: 1.138 },
  '/models/kenney-city/suburban-q.glb': { minX: -0.62, maxX: 0.62, minZ: -0.422, maxZ: 0.464, maxY: 0.918 },
  '/models/kenney-fantasy-town/fountain.glb': { minX: -1, maxX: 1, minZ: -1, maxZ: 1, maxY: 0.48 },
  '/models/poly/apartment-block.glb': { minX: -1.003, maxX: 1.003, minZ: -1, maxZ: 1, maxY: 3.05 },
  '/models/poly/bakery.glb': { minX: -1, maxX: 1, minZ: -1, maxZ: 1, maxY: 1.65 },
  '/models/poly/bank.glb': { minX: -1.748, maxX: 1.723, minZ: -1.906, maxZ: 1.886, maxY: 0.383 },
  '/models/poly/barn.glb': { minX: -0.249, maxX: 0.249, minZ: -0.33, maxZ: 0.374, maxY: 0.444 },
  '/models/poly/bathhouse.glb': { minX: -5, maxX: 5, minZ: -5, maxZ: 5, maxY: 1.988 },
  '/models/poly/bell-tower.glb': { minX: -0.968, maxX: 0.968, minZ: -1.125, maxZ: 1.103, maxY: 4.761 },
  '/models/poly/boutique.glb': { minX: -1.792, maxX: 1.792, minZ: -1.243, maxZ: 1.243, maxY: 4.946 },
  '/models/poly/cafe.glb': { minX: -1, maxX: 1, minZ: -1, maxZ: 1.02, maxY: 2.97 },
  '/models/poly/church.glb': { minX: -0.239, maxX: 0.238, minZ: -0.303, maxZ: 0.493, maxY: 1.013 },
  '/models/poly/civic-block.glb': { minX: -1.02, maxX: 1.02, minZ: -0.425, maxZ: 0.42, maxY: 1.5 },
  '/models/poly/civic-modern.glb': { minX: -1.5, maxX: 0.82, minZ: -1, maxZ: 0.82, maxY: 2.48 },
  '/models/poly/clinic.glb': { minX: -1.02, maxX: 1.02, minZ: -0.62, maxZ: 0.62, maxY: 1.68 },
  '/models/poly/condo-block.glb': { minX: -1.003, maxX: 1.003, minZ: -1, maxZ: 1, maxY: 2.35 },
  '/models/poly/dock.glb': { minX: -0.139, maxX: 1.169, minZ: -1.051, maxZ: -0.327, maxY: 0.552 },
  '/models/poly/factory.glb': { minX: -4.537, maxX: 3.337, minZ: -1.807, maxZ: 2.715, maxY: 9.493 },
  '/models/poly/garden.glb': { minX: -0.897, maxX: 0.892, minZ: -0.788, maxZ: 0.768, maxY: 0.318 },
  '/models/poly/glass-tower.glb': { minX: -0.62, maxX: 0.62, minZ: -0.62, maxZ: 0.62, maxY: 2.88 },
  '/models/poly/granary.glb': { minX: -3.421, maxX: 1.917, minZ: -1.665, maxZ: 1.845, maxY: 9.019 },
  '/models/poly/grand-hotel.glb': { minX: -2.322, maxX: 2.322, minZ: -1.928, maxZ: 1.928, maxY: 5.472 },
  '/models/poly/house-cabin.glb': { minX: -0.224, maxX: 0.213, minZ: -0.207, maxZ: 0.103, maxY: 0.35 },
  '/models/poly/house-cottage.glb': { minX: -0.15, maxX: 0.15, minZ: -0.249, maxZ: 0.217, maxY: 0.276 },
  '/models/poly/house-duplex.glb': { minX: -0.945, maxX: 0.976, minZ: -0.885, maxZ: 0.999, maxY: 0.946 },
  '/models/poly/house-fantasy.glb': { minX: -1.072, maxX: 1.072, minZ: -1.342, maxZ: 1.316, maxY: 3.39 },
  '/models/poly/house-modern.glb': { minX: -0.539, maxX: 0.351, minZ: -0.543, maxZ: 0.321, maxY: 0.766 },
  '/models/poly/house-q2.glb': { minX: -1.65, maxX: 1.994, minZ: -1.436, maxZ: 1.648, maxY: 2.912 },
  '/models/poly/house-terrace.glb': { minX: -0.706, maxX: 0.647, minZ: -0.794, maxZ: 0.667, maxY: 1.064 },
  '/models/poly/house-twostory.glb': { minX: -0.654, maxX: 0.654, minZ: -0.703, maxZ: 0.703, maxY: 1.137 },
  '/models/poly/house-walkup.glb': { minX: -0.62, maxX: 0.62, minZ: -0.72, maxZ: 0.62, maxY: 2.08 },
  '/models/poly/hut.glb': { minX: -0.435, maxX: 0.435, minZ: -0.585, maxZ: 0.587, maxY: 0.766 },
  '/models/poly/kiosk.glb': { minX: -0.475, maxX: 0.475, minZ: -0.597, maxZ: 0.593, maxY: 1.044 },
  '/models/poly/library.glb': { minX: -0.632, maxX: 0.632, minZ: -0.62, maxZ: 0.62, maxY: 1.064 },
  '/models/poly/lighthouse.glb': { minX: -4.624, maxX: 4.813, minZ: -4.82, maxZ: 4.157, maxY: 14.502 },
  '/models/poly/manor.glb': { minX: -2.858, maxX: 2.858, minZ: -1.11, maxZ: 1.11, maxY: 5.905 },
  '/models/poly/market-stalls.glb': { minX: -0.968, maxX: 0.653, minZ: -0.544, maxZ: 0.674, maxY: 0.545 },
  '/models/poly/market.glb': { minX: -0.969, maxX: 0.922, minZ: -1.081, maxZ: 1.028, maxY: 0.545 },
  '/models/poly/office-tower.glb': { minX: -2.353, maxX: 2.353, minZ: -2.195, maxZ: 2.195, maxY: 5.664 },
  '/models/poly/school.glb': { minX: -0.82, maxX: 0.82, minZ: -0.548, maxZ: 0.42, maxY: 0.88 },
  '/models/poly/shop-corner.glb': { minX: -1, maxX: 1, minZ: -1, maxZ: 1, maxY: 1.65 },
  '/models/poly/shop-kl.glb': { minX: -1.003, maxX: 1.003, minZ: -1, maxZ: 1, maxY: 2.35 },
  '/models/poly/skyscraper.glb': { minX: -0.62, maxX: 0.62, minZ: -0.62, maxZ: 0.62, maxY: 3.15 },
  '/models/poly/smithy.glb': { minX: -2.566, maxX: 1.324, minZ: -1.658, maxZ: 1.626, maxY: 2.999 },
  '/models/poly/tavern.glb': { minX: -2.018, maxX: 2.011, minZ: -2.011, maxZ: 2.011, maxY: 3.486 },
  '/models/poly/temple.glb': { minX: -1.096, maxX: 1.096, minZ: -1.096, maxZ: 1.096, maxY: 4.327 },
  '/models/poly/theater.glb': { minX: -16.617, maxX: 16.642, minZ: -1.208, maxZ: 19.701, maxY: 15.271 },
  '/models/poly/townhouse-a.glb': { minX: -3.996, maxX: 3.996, minZ: -1.372, maxZ: 1.372, maxY: 4.66 },
  '/models/poly/townhouse-b.glb': { minX: -1.874, maxX: 1.874, minZ: -1.372, maxZ: 1.372, maxY: 4.662 },
  '/models/poly/townhouse-c.glb': { minX: -1.526, maxX: 1.526, minZ: -2.201, maxZ: 2.195, maxY: 5.664 },
  '/models/poly/windmill.glb': { minX: -3.948, maxX: 3.976, minZ: -2.586, maxZ: 2.405, maxY: 11.38 },
  '/models/poly/zoo.glb': { minX: -2.839, maxX: 2.904, minZ: -3.091, maxZ: 3.091, maxY: 4.744 },
};

/**
 * Front-face z per EM-122 PROCEDURAL silhouette (read off Structure.tsx
 * geometry at mural height, y≈0.8–1.9) — the fallback when a variant has no
 * GLB spec (a registry null) and the honest face for the brief Suspense
 * moments. Aliased build-types reuse their VARIANT_COMPONENTS silhouette's
 * value. Coarse by design: these are fallback moments, not the steady state.
 */
export const PROCEDURAL_FRONT_Z: Record<VariantKey, number> = {
  garden: 1.15,
  farm: 1.23,
  workshop: 1.15,
  library: 1.45,
  clocktower: 1.25,
  house: 1.18,
  stall: 1.0,
  monument: 1.0,
  well: 1.05,
  zoo: 0.95,
  generic: 1.22,
  // aliases (VARIANT_COMPONENTS fallback silhouettes)
  tavern: 1.18,      // → house
  market: 1.0,       // → stall
  smithy: 1.15,      // → workshop
  temple: 1.0,       // → monument
  school: 1.45,      // → library
  clinic: 1.22,      // → generic
  granary: 1.23,     // → farm
  bakery: 1.0,       // → stall
  bank: 1.0,         // → monument
  theater: 1.22,     // → generic
  lighthouse: 1.25,  // → clocktower
  bathhouse: 1.22,   // → generic
  dock: 1.15,        // → workshop
};

/**
 * The +z extent of a model's XZ footprint after a Y-rotation (three.js
 * convention: z' = z·cosθ − x·sinθ). Rotating the four AABB footprint corners
 * and taking the max z' gives the front-most face the CAMERA sees, so the
 * decal clears a rotated GLB too (all registry rotations are 0 today — this
 * keeps the math honest if a kit swap ever needs a facing fix).
 */
export function rotatedFrontExtent(box: DecalBounds, rotationY: number): number {
  const cos = Math.cos(rotationY);
  const sin = Math.sin(rotationY);
  const corners: Array<[number, number]> = [
    [box.minX, box.minZ],
    [box.minX, box.maxZ],
    [box.maxX, box.minZ],
    [box.maxX, box.maxZ],
  ];
  let front = -Infinity;
  for (const [x, z] of corners) front = Math.max(front, z * cos - x * sin);
  return front;
}

export interface DecalPlacement {
  /** Mural center height (world units above the lot). */
  y: number;
  /** Plane z — the measured front face + DECAL_EPSILON along the +z normal. */
  z: number;
  /** Uniform XY shrink (≤1) so short models keep the mural on the facade. */
  scale: number;
}

const MIN_DECAL_SCALE = 0.3;
const TOP_MARGIN = 0.1;   // mural top stays this far under the measured roofline
const GROUND_CLEAR = 0.05; // mural bottom stays this far above grade

/** Vertical fit: shrink + lower the canvas when the model is shorter than the
 * default mural band; tall facades keep the exact pre-EM-302 y=1.35, scale=1. */
function fitVertically(topY: number): { y: number; scale: number } {
  const h = DECAL_SIZE[1];
  const available = topY - TOP_MARGIN - GROUND_CLEAR;
  const scale = Math.min(1, Math.max(MIN_DECAL_SCALE, available / h));
  const half = (h * scale) / 2;
  const y = Math.max(GROUND_CLEAR + half, Math.min(DECAL_BASE_Y, topY - TOP_MARGIN - half));
  return { y, scale };
}

/**
 * Where (and how big) the facade decal renders for `building`, in the
 * building group's local frame. Deterministic — same resolution as the
 * Structure renderer (resolveStructureModel on kind+id), so the decal tracks
 * whichever GLB the variety pool picked for this exact building.
 */
export function decalPlacement(
  building: Pick<Building, 'id' | 'kind' | 'status'>,
): DecalPlacement {
  // damaged renders the scorched procedural box (GLBs are operational/offline only).
  if (building.status === 'damaged') {
    return { y: DECAL_BASE_Y, z: DAMAGED_FRONT_Z + DECAL_EPSILON, scale: 1 };
  }
  if (building.status !== 'operational' && building.status !== 'offline') {
    // planned / under_construction / abandoned / destroyed: no finished facade
    // to measure — keep the legacy plane (rising walls sit at z≈1.0).
    return { y: DECAL_BASE_Y, z: LEGACY_DECAL_Z, scale: 1 };
  }
  const { variant, spec } = resolveStructureModel(building.kind, building.id);
  if (!spec) {
    const front = Object.prototype.hasOwnProperty.call(PROCEDURAL_FRONT_Z, variant)
      ? PROCEDURAL_FRONT_Z[variant]
      : LEGACY_DECAL_Z;
    return { y: DECAL_BASE_Y, z: front + DECAL_EPSILON, scale: 1 };
  }
  const box = Object.prototype.hasOwnProperty.call(GLB_DECAL_BOUNDS, spec.url)
    ? GLB_DECAL_BOUNDS[spec.url]
    : undefined;
  if (!box) {
    // An unmeasured GLB (decalLayout.test.ts makes this unreachable for the
    // vendored registry) — keep the legacy plane rather than guessing.
    return { y: DECAL_BASE_Y, z: LEGACY_DECAL_Z, scale: 1 };
  }
  const rotation = (spec.rotation ?? 0) + modelRotationY(variant);
  const z = rotatedFrontExtent(box, rotation) * spec.scale + DECAL_EPSILON;
  const topY = box.maxY * spec.scale + spec.yOffset;
  const { y, scale } = fitVertically(topY);
  return { y, z, scale };
}
