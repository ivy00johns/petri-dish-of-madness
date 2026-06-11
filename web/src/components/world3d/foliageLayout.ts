/**
 * foliageLayout — pure, DETERMINISTIC park-greenery math (EM-118, rebuilt for
 * Wave D1.5). No React, no three.js, no randomness: every position derives
 * from `hashUnit` (worldSpace) + the frozen city grid, so the same world
 * yields the same layout every frame, reload, and test run.
 *
 * THE WILDERNESS IS DEAD (contracts/wave-d1.5.md): the sim lives on the city
 * grid and every block is developed — there is no meadow for a treeline,
 * bushes, rocks, mushrooms, or flower scatter, and the lanes (and the
 * lamp/bench dressing that lined them) are gone with it; the city plan
 * (cityLayout) provides the street furniture.
 *
 * What remains is PARK greenery: a seeded light scatter of trees + grass
 * ONLY inside park landmark blocks — the blocks claimed by farm-district
 * places (the city's parks: e.g. The Commons Park, Willow Pond Park, Orchard
 * Green), falling back to wild-kind places for district-less legacy
 * snapshots. Trees render through Foliage.tsx (layoutTrees/splitByLod) and
 * grass through Scenery.tsx (layoutParkGrass).
 *
 * The Wave D1 cityLayout↔foliageLayout import cycle is gone: cityLayout no
 * longer imports BAND_MAX from here (deriveCoreRadius died with the ring),
 * and this module's one-way import of cityLayout's grid helpers is acyclic.
 *
 * The dead layers (layoutLamps/layoutBenches/layoutFences/layoutMushrooms/
 * layoutWildScatter) keep their exported signatures but return [] — their
 * consumer (Props.tsx) renders zero instances without churn.
 */

import type { Place } from '../../types';
import { placeToWorld, hashUnit } from './worldSpace';
import { snapToBlockCenter, BLOCK_HALF } from './cityLayout';

// ── Park tunables (world units) ──────────────────────────────────────────────

/** Tree-to-tree spacing inside a park so canopies don't merge into blobs. */
export const TREE_SPACING = 2.4;
/** Trees within this distance of world origin render at full detail (LOD). */
export const TREE_LOD_RADIUS = 34;
/** Light scatter per park landmark block (the contract says LIGHT). */
export const PARK_TREES_PER_BLOCK = 4;
export const PARK_GRASS_PER_BLOCK = 14;
/** Greenery keeps off the block's outer rim (the sidewalk strip). */
export const PARK_EDGE_INSET = 1.0;
/** Trees keep clear of the park's place anchor (its marker / structure). */
export const PARK_ANCHOR_CLEAR = 2.6;
/** Grass only needs a token clearance off the anchor. */
const GRASS_ANCHOR_CLEAR = 1.2;

// ── Types ────────────────────────────────────────────────────────────────────

export type TreeVariant = 'oak' | 'conifer' | 'blossom';

export interface ScatterItem {
  x: number;
  z: number;
  scale: number;
  rot: number;
}

export interface TreeItem extends ScatterItem {
  variant: TreeVariant;
}

// ── Park landmark blocks ─────────────────────────────────────────────────────

export interface ParkBlock {
  /** Owning place id (sorted; first claimant when places share a block). */
  id: string;
  /** Snapped block center (cityLayout grid). */
  cx: number;
  cz: number;
}

/** True if this place's landmark block is one of the city's parks. */
function isParkPlace(p: Place): boolean {
  return p.district === 'farm' || (!p.district && p.kind === 'wild');
}

/**
 * The park landmark blocks: farm-district places (legacy fallback: wild-kind
 * places) snapped to their claimed block centers, deduped, in sorted-id order
 * — deterministic in place content, not input order.
 */
export function parkBlocks(places: Place[]): ParkBlock[] {
  const out: ParkBlock[] = [];
  const seen = new Set<string>();
  const sorted = [...places].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  for (const p of sorted) {
    if (!isParkPlace(p)) continue;
    const w = placeToWorld(p);
    const c = snapToBlockCenter(w.x, w.z);
    const key = `${c.x},${c.z}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ id: p.id, cx: c.x, cz: c.z });
  }
  return out;
}

/** True if (x,z) lies inside some park landmark block's greenery area. */
export function insidePark(x: number, z: number, blocks: ParkBlock[]): boolean {
  const max = BLOCK_HALF - PARK_EDGE_INSET + 1e-9;
  return blocks.some((b) => Math.abs(x - b.cx) <= max && Math.abs(z - b.cz) <= max);
}

// ── Trees (light park scatter — rendered by Foliage.tsx) ────────────────────

/**
 * Seeded light tree scatter, ONLY inside park landmark blocks: a handful per
 * park, inset from the sidewalk rim, clear of the place anchor, self-spaced.
 * Variant mix: ~45% round oak, ~35% conifer, ~20% blossom.
 */
export function layoutTrees(places: Place[]): TreeItem[] {
  const out: TreeItem[] = [];
  for (const b of parkBlocks(places)) {
    const spread = BLOCK_HALF - PARK_EDGE_INSET;
    const placed: Array<{ x: number; z: number }> = [];
    let attempts = 0;
    let i = 0;
    while (placed.length < PARK_TREES_PER_BLOCK && attempts < PARK_TREES_PER_BLOCK * 12) {
      attempts++;
      const seed = `park-tree-${b.id}-${i++}`;
      const ox = (hashUnit(`${seed}-x`) - 0.5) * 2 * spread;
      const oz = (hashUnit(`${seed}-z`) - 0.5) * 2 * spread;
      if (Math.hypot(ox, oz) < PARK_ANCHOR_CLEAR) continue;
      if (placed.some((t) => Math.hypot(t.x - ox, t.z - oz) < TREE_SPACING)) continue;
      placed.push({ x: ox, z: oz });
      const roll = hashUnit(`${seed}-v`);
      out.push({
        x: b.cx + ox,
        z: b.cz + oz,
        scale: 0.8 + hashUnit(`${seed}-s`) * 0.45,
        rot: hashUnit(`${seed}-r`) * Math.PI * 2,
        variant: roll < 0.45 ? 'oak' : roll < 0.8 ? 'conifer' : 'blossom',
      });
    }
  }
  return out;
}

/**
 * Static LOD split: trees near the world origin (where the camera orbits)
 * render full multi-part detail; the rest render a simplified two-part
 * silhouette. Deterministic — no per-frame re-bucketing.
 */
export function splitByLod(trees: TreeItem[]): { near: TreeItem[]; far: TreeItem[] } {
  const near: TreeItem[] = [];
  const far: TreeItem[] = [];
  for (const t of trees) {
    (Math.hypot(t.x, t.z) <= TREE_LOD_RADIUS ? near : far).push(t);
  }
  return { near, far };
}

// ── Grass (park tufts — rendered by Scenery.tsx) ─────────────────────────────

/**
 * Seeded light grass-tuft scatter, ONLY inside park landmark blocks (token
 * clearance off the anchor; tufts may touch each other freely).
 */
export function layoutParkGrass(places: Place[]): ScatterItem[] {
  const out: ScatterItem[] = [];
  for (const b of parkBlocks(places)) {
    const spread = BLOCK_HALF - PARK_EDGE_INSET;
    let attempts = 0;
    let i = 0;
    let placed = 0;
    while (placed < PARK_GRASS_PER_BLOCK && attempts < PARK_GRASS_PER_BLOCK * 6) {
      attempts++;
      const seed = `park-grass-${b.id}-${i++}`;
      const ox = (hashUnit(`${seed}-x`) - 0.5) * 2 * spread;
      const oz = (hashUnit(`${seed}-z`) - 0.5) * 2 * spread;
      if (Math.hypot(ox, oz) < GRASS_ANCHOR_CLEAR) continue;
      placed++;
      out.push({
        x: b.cx + ox,
        z: b.cz + oz,
        scale: 0.7 + hashUnit(`${seed}-s`) * 0.8,
        rot: hashUnit(`${seed}-r`) * Math.PI * 2,
      });
    }
  }
  return out;
}

// ── Dead layers (Wave D1.5) — signatures kept, always empty ─────────────────

/** Dead since Wave D1.5 (no wilderness): kept so Props.tsx call sites hold. */
export const BUSH_COUNT = 0;
/** Dead since Wave D1.5 (no wilderness): kept so Props.tsx call sites hold. */
export const ROCK_COUNT = 0;

/** Lamps died with the lanes — the city plan provides street lighting. */
export function layoutLamps(_places: Place[]): ScatterItem[] {
  return [];
}

/** Place-ring benches died — the city plan provides street furniture. */
export function layoutBenches(_places: Place[]): ScatterItem[] {
  return [];
}

/** Home fence arcs died with the wilderness clearance model. */
export function layoutFences(_places: Place[]): ScatterItem[] {
  return [];
}

/** Mushroom clusters died with the wilderness. */
export function layoutMushrooms(_places: Place[]): ScatterItem[] {
  return [];
}

/** Wild scatter (bushes/rocks) died with the wilderness. */
export function layoutWildScatter(
  _count: number,
  _prefix: string,
  _places: Place[],
  _spread?: number,
): ScatterItem[] {
  return [];
}
