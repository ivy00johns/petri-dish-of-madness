/**
 * buildingRecipe.ts — EM-299 (Wave Q) parametric building-recipe geometry.
 *
 * A PURE, canvas-free derivation layer: `computeBuildingMesh(recipe, idHash)`
 * turns a model-authored recipe (footprint/floors/roof/material/palette/
 * window_density/trim — the closed-enum grammar validated server-side by
 * `petridish.engine.building_recipe`) into deterministic geometry + color
 * PARAMS. `Structure.tsx` maps those params to cheap THREE primitives (boxes,
 * cones, planes) — the same procedural register as the EM-122 silhouettes, so a
 * recipe building cel-shades into the golden-hour village instead of standing
 * out as a foreign asset.
 *
 * No React, no THREE here → fully unit-testable. Determinism is the contract:
 * the SAME (recipe, idHash) ALWAYS yields identical params (EM-155). `idHash`
 * (a stable [0,1) hash of the building id) drives only bounded, cosmetic
 * variety (depth ratio) so a row of same-recipe buildings isn't identical
 * clones — never the core silhouette.
 *
 * Colors are WebGL material colors (hex → THREE.Color), explicitly OUTSIDE the
 * CSS design-token system — the same village convention as worldSpace /
 * Structure (the GPU scene owns its warm palette; design-token-guard governs
 * DOM/CSS only).
 *
 * Defensive by construction: every enum lookup falls back to its grammar
 * default and `floors` is clamped to [1,8], so even a hand-crafted / malformed
 * recipe (the backend coerces, but a mock might not) renders a sane building —
 * never NaN geometry, never a hole.
 */

// The recipe shape (closed-enum grammar) lives in the canonical types module.
import type {
  BuildingRecipe,
  Footprint,
  Roof,
  BuildingMaterial as Material,
  BuildingPalette as Palette,
  WindowDensity,
  Trim,
} from '../../types';

export type { BuildingRecipe };

// ── Derived mesh params (what Structure.tsx renders) ─────────────────────────

/** One flush, front-face window (emissive when lit; dark when offline). */
export interface RecipeWindow {
  /** Local position on the body front face (z is the wall plane + a hair). */
  x: number;
  y: number;
  z: number;
  w: number;
  h: number;
}

export interface RecipeRoof {
  kind: Roof;
  /** Vertical extent of the roof above the body top. */
  height: number;
  /** Horizontal reach (cone radius / dome radius / slab half-width). */
  radius: number;
}

export interface RecipeTrim {
  /** A base plinth band at the foot of the walls. */
  plinth: boolean;
  /** A cornice band just under the roof. */
  cornice: boolean;
  /** Corner pilasters (gilded only) — the richest tier. */
  quoins: boolean;
  /** Accent hex for the bands/pilasters (gold for gilded, cream for ornate). */
  accent: string;
}

export interface RecipeMesh {
  /** Body footprint (X width, Z depth) — stays within a ~3.4u slot. */
  width: number;
  depth: number;
  floors: number;
  floorHeight: number;
  /** Wall height (floors × floorHeight, plus a ground-floor bump). */
  bodyHeight: number;
  /** bodyHeight + roof.height + plinth — the label-clearance height. */
  totalHeight: number;
  body: string;
  roofColor: string;
  windowColor: string;
  roof: RecipeRoof;
  windows: RecipeWindow[];
  trim: RecipeTrim;
}

// ── Grammar → geometry tables ────────────────────────────────────────────────

const FOOTPRINT_WIDTH: Record<Footprint, number> = {
  tiny: 1.6,
  small: 2.0,
  medium: 2.4,
  large: 2.8,
  grand: 3.2,
};

/** Window columns across the front, per footprint (denser plans read wider). */
const FOOTPRINT_COLS: Record<Footprint, number> = {
  tiny: 1,
  small: 2,
  medium: 2,
  large: 3,
  grand: 3,
};

const FLOOR_HEIGHT = 1.0;
/** The ground floor stands a little taller (a plinth/entry storey). */
const GROUND_BUMP = 0.2;
/** Base plinth height — the renderer imports this so windows/body/plinth agree. */
export const PLINTH_H = 0.16;

const FLOORS_MIN = 1;
const FLOORS_MAX = 8;

// ── Grammar → color tables (warm, toon-consistent) ───────────────────────────

const MATERIAL_BODY: Record<Material, string> = {
  wood: '#c89b63',
  timber_frame: '#d8c49a',
  brick: '#b5654a',
  stone: '#b8b2a4',
  marble: '#ece7dc',
  plaster: '#e6d8bf',
  mud_brick: '#c99e73',
};

const MATERIAL_ROOF: Record<Material, string> = {
  wood: '#7a4a2c',
  timber_frame: '#6b4f32',
  brick: '#8a4a3a',
  stone: '#6f6a60',
  marble: '#9a8fb0',
  plaster: '#a5754f',
  mud_brick: '#8a5a3a',
};

/** Palette "mood" anchor the body/roof are nudged toward (kept warm). */
const PALETTE_ANCHOR: Record<Palette, string> = {
  warm: '#e8b06a',
  cool: '#7fb0c8',
  earthy: '#c19a6b',
  pastel: '#e7c9d8',
  vivid: '#e2703a',
  muted: '#b9ad97',
  monochrome: '#cfcabc',
};

/** Warm window glow, per palette (cool/vivid tint the lit panes slightly). */
const PALETTE_WINDOW: Record<Palette, string> = {
  warm: '#ffcf7a',
  cool: '#bfe0ff',
  earthy: '#ffcf7a',
  pastel: '#ffe0ea',
  vivid: '#ffd06a',
  muted: '#f0d9a8',
  monochrome: '#e8e2cf',
};

const GILDED = '#ffd27f';
const ORNATE = '#efe3c4';

// ── Hex helpers (pure) ───────────────────────────────────────────────────────

function clampByte(n: number): number {
  return Math.max(0, Math.min(255, Math.round(n)));
}

function parseHex(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

function toHex(r: number, g: number, b: number): string {
  const c = (n: number) => clampByte(n).toString(16).padStart(2, '0');
  return `#${c(r)}${c(g)}${c(b)}`;
}

/** Linear blend a→b by t∈[0,1]; t=0 is a, t=1 is b. Deterministic. */
export function mixHex(a: string, b: string, t: number): string {
  const [ar, ag, ab] = parseHex(a);
  const [br, bg, bb] = parseHex(b);
  const k = Math.max(0, Math.min(1, t));
  return toHex(ar + (br - ar) * k, ag + (bg - ag) * k, ab + (bb - ab) * k);
}

/** Lighten toward white by t (for the simple-trim band). */
function lighten(hex: string, t: number): string {
  return mixHex(hex, '#ffffff', t);
}

// ── Enum guards (default-safe) ───────────────────────────────────────────────

/** Return `key` when it's an own value of the closed enum set, else `fallback`. */
function oneOf<T extends string>(values: readonly T[], key: string, fallback: T): T {
  return (values as readonly string[]).includes(key) ? (key as T) : fallback;
}

const FOOTPRINTS: readonly Footprint[] = ['tiny', 'small', 'medium', 'large', 'grand'];
const ROOFS: readonly Roof[] = ['flat', 'shed', 'gable', 'hip', 'dome', 'spire'];
const MATERIALS: readonly Material[] =
  ['wood', 'timber_frame', 'brick', 'stone', 'marble', 'plaster', 'mud_brick'];
const PALETTES: readonly Palette[] =
  ['warm', 'cool', 'earthy', 'pastel', 'vivid', 'muted', 'monochrome'];
const DENSITIES: readonly WindowDensity[] = ['none', 'sparse', 'regular', 'dense'];
const TRIMS: readonly Trim[] = ['none', 'simple', 'ornate', 'gilded'];

function clampFloors(n: number): number {
  const f = Math.floor(Number.isFinite(n) ? n : FLOORS_MIN);
  return Math.max(FLOORS_MIN, Math.min(FLOORS_MAX, f));
}

// ── Roof geometry ────────────────────────────────────────────────────────────

function roofFor(kind: Roof, width: number): RecipeRoof {
  const half = width / 2;
  switch (kind) {
    case 'flat':
      return { kind, height: 0.12, radius: half + 0.1 };
    case 'shed':
      return { kind, height: 0.5, radius: half + 0.05 };
    case 'gable':
      return { kind, height: 0.85, radius: half + 0.15 };
    case 'hip':
      return { kind, height: 0.9, radius: half + 0.12 };
    case 'dome':
      return { kind, height: width * 0.42, radius: half * 0.92 };
    case 'spire':
      return { kind, height: 1.7, radius: half * 0.72 };
    default:
      return { kind: 'gable', height: 0.85, radius: half + 0.15 };
  }
}

// ── Windows ──────────────────────────────────────────────────────────────────

function windowsFor(
  density: WindowDensity,
  cols: number,
  floors: number,
  width: number,
  depth: number,
  floorHeight: number,
  groundY: number,
): RecipeWindow[] {
  if (density === 'none') return [];
  // Dense adds one extra column; sparse checkerboards; regular fills the grid.
  const effCols = density === 'dense' ? cols + 1 : cols;
  const win: RecipeWindow[] = [];
  const w = Math.min(0.5, (width * 0.62) / effCols);
  const h = Math.min(0.62, floorHeight * 0.5);
  const z = depth / 2 + 0.02;
  const colStep = width / (effCols + 1);
  for (let row = 0; row < floors; row++) {
    // window centered vertically within its storey
    const y = groundY + row * floorHeight + floorHeight * 0.55;
    for (let col = 0; col < effCols; col++) {
      // sparse: checkerboard — skip when (row+col) is odd
      if (density === 'sparse' && (row + col) % 2 === 1) continue;
      const x = -width / 2 + colStep * (col + 1);
      win.push({ x, y, z, w, h });
    }
  }
  return win;
}

// ── Trim ─────────────────────────────────────────────────────────────────────

function trimFor(trim: Trim, body: string): RecipeTrim {
  switch (trim) {
    case 'none':
      return { plinth: false, cornice: false, quoins: false, accent: body };
    case 'simple':
      return { plinth: true, cornice: false, quoins: false, accent: lighten(body, 0.25) };
    case 'ornate':
      return { plinth: true, cornice: true, quoins: false, accent: ORNATE };
    case 'gilded':
      return { plinth: true, cornice: true, quoins: true, accent: GILDED };
    default:
      return { plinth: true, cornice: false, quoins: false, accent: lighten(body, 0.25) };
  }
}

// ── The derivation ───────────────────────────────────────────────────────────

/**
 * Derive deterministic geometry + color params for a recipe building.
 *
 * @param recipe the model-authored (server-coerced) recipe.
 * @param idHash a stable [0,1) hash of the building id (worldSpace.hashUnit) —
 *   drives ONLY bounded cosmetic variety (front/side depth ratio), never the
 *   silhouette, so determinism holds and same-recipe rows still vary a little.
 */
export function computeBuildingMesh(recipe: BuildingRecipe, idHash: number): RecipeMesh {
  const footprint = oneOf(FOOTPRINTS, recipe.footprint, 'medium');
  const material = oneOf(MATERIALS, recipe.material, 'wood');
  const palette = oneOf(PALETTES, recipe.palette, 'earthy');
  const roof = oneOf(ROOFS, recipe.roof, 'gable');
  const density = oneOf(DENSITIES, recipe.window_density, 'regular');
  const trimKind = oneOf(TRIMS, recipe.trim, 'simple');

  const floors = clampFloors(recipe.floors);
  const width = FOOTPRINT_WIDTH[footprint];
  // depth: bounded per-building variety (0.82–0.92 of width) keyed on idHash so
  // a run of identical recipes isn't a row of perfect cubes. Deterministic.
  const hash = Number.isFinite(idHash) ? Math.max(0, Math.min(1, idHash)) : 0;
  const depth = width * (0.82 + hash * 0.1);

  const floorHeight = FLOOR_HEIGHT;
  const bodyHeight = floors * floorHeight + GROUND_BUMP;
  const roofParams = roofFor(roof, width);
  const totalHeight = PLINTH_H + bodyHeight + roofParams.height;

  const body = mixHex(MATERIAL_BODY[material], PALETTE_ANCHOR[palette], 0.35);
  const roofColor = mixHex(MATERIAL_ROOF[material], PALETTE_ANCHOR[palette], 0.18);
  const windowColor = PALETTE_WINDOW[palette];

  const cols = FOOTPRINT_COLS[footprint];
  const groundY = PLINTH_H;
  const windows = windowsFor(
    density, cols, floors, width, depth, floorHeight, groundY,
  );

  return {
    width,
    depth,
    floors,
    floorHeight,
    bodyHeight,
    totalHeight,
    body,
    roofColor,
    windowColor,
    roof: roofParams,
    windows,
    trim: trimFor(trimKind, body),
  };
}
