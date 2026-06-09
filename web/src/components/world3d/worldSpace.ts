/**
 * worldSpace — shared constants & helpers for the cozy 3D village.
 *
 * World mapping (per the build contract):
 *   SIZE = 40
 *   worldX = (place.x / 1000 - 0.5) * SIZE
 *   worldZ = (place.y / 1000 - 0.5) * SIZE
 * Ground is the XZ plane, Y is up.
 */

import type { Place, PlaceKind, WorldEvent } from '../../types';

/** Edge length of the village ground plane in world units. */
export const SIZE = 40;

/** Convert a place's logical (0..1000) x to world X. */
export function toWorldX(x: number): number {
  return (x / 1000 - 0.5) * SIZE;
}

/** Convert a place's logical (0..1000) y to world Z. */
export function toWorldZ(y: number): number {
  return (y / 1000 - 0.5) * SIZE;
}

/** A place's center in world space. */
export interface WorldPoint {
  x: number;
  z: number;
}

export function placeToWorld(place: Place): WorldPoint {
  return { x: toWorldX(place.x), z: toWorldZ(place.y) };
}

/**
 * Distribute co-located agents in a small ring around a place center so they
 * don't overlap. `index` is the agent's index among the agents at this place;
 * `count` is how many share the place.
 */
export function ringOffset(
  center: WorldPoint,
  index: number,
  count: number,
  radius = 2,
): WorldPoint {
  if (count <= 1) return { ...center };
  const angle = (index / count) * Math.PI * 2 - Math.PI / 2;
  return {
    x: center.x + Math.cos(angle) * radius,
    z: center.z + Math.sin(angle) * radius,
  };
}

/** Cozy palette per place kind (warm, charming low-poly). */
export interface PlaceStyle {
  /** Accent/roof color for the building. */
  accent: string;
  /** Wall / body color. */
  body: string;
  /** Short display tag. */
  tag: string;
}

export const PLACE_STYLES: Record<PlaceKind, PlaceStyle> = {
  social: { accent: '#ef6f6c', body: '#f6e2b3', tag: 'Plaza' },
  work: { accent: '#f4a259', body: '#e7d3a1', tag: 'Market' },
  governance: { accent: '#7b6cf6', body: '#efe7d6', tag: 'Town Hall' },
  home: { accent: '#e07a5f', body: '#f2cc8f', tag: 'Hearth' },
  wild: { accent: '#5fa05f', body: '#c5e1a5', tag: 'Commons' },
};

/**
 * Latest model that actually answered for a given agent, derived from events.
 * Events are newest-first; we scan for the first event by this actor that
 * carries payload.routed_via. Falls back to undefined (caller uses profile).
 */
export function latestRoutedVia(
  events: WorldEvent[],
  agentId: string,
): string | undefined {
  for (const e of events) {
    if (e.actor_id !== agentId) continue;
    const via = e.payload?.routed_via;
    if (typeof via === 'string' && via.length > 0) return via;
  }
  return undefined;
}

/**
 * Material palette for a W7 Building, keyed by `kind`. Warm low-poly tints —
 * these are WebGL material colors (THREE.Color), explicitly OUTSIDE the CSS
 * design-token system (same convention as Building/Villager/Scenery: the GPU
 * scene mixes its own warm palette; design-token-guard governs DOM/CSS only).
 *
 * `body`/`roof`/`accent` finish the operational structure; `tag` is the floating
 * label suffix. Unknown kinds fall back to MONUMENT (a neutral cultural stub).
 */
export interface BuildingStyle {
  body: string;
  roof: string;
  accent: string;
  tag: string;
}

export const BUILDING_STYLES: Record<string, BuildingStyle> = {
  clocktower: { body: '#efe3c4', roof: '#7b6cf6', accent: '#ffd27f', tag: 'Clock Tower' },
  garden:     { body: '#cdebb0', roof: '#5fa05f', accent: '#ff8fb1', tag: 'Garden' },
  workshop:   { body: '#e7d3a1', roof: '#f4a259', accent: '#c98b3a', tag: 'Workshop' },
  farm:       { body: '#f0d9a0', roof: '#d2a24c', accent: '#e7b84f', tag: 'Farm' },
  library:    { body: '#e6dcc8', roof: '#9c6b4a', accent: '#caa472', tag: 'Library' },
  house:      { body: '#f2cc8f', roof: '#e07a5f', accent: '#ffe0a3', tag: 'House' },
  monument:   { body: '#dcd2c0', roof: '#bfa98a', accent: '#fff3e0', tag: 'Monument' },
};

/** Resolve a Building style by kind, defaulting to the monument tint. */
export function buildingStyle(kind: string): BuildingStyle {
  return BUILDING_STYLES[kind] ?? BUILDING_STYLES.monument;
}

/**
 * Material palette for a W8 Animal, keyed by `species`. Warm low-poly tints —
 * like BUILDING_STYLES these are WebGL material colors (THREE.Color), explicitly
 * OUTSIDE the CSS design-token system (the GPU scene owns its warm palette;
 * design-token-guard governs DOM/CSS only). A chaotic animal additionally gets a
 * magenta accent glow applied in the Critter component (the chaos-feed magenta,
 * mirrored from --marker-animal so the registers agree).
 *
 * `body`/`belly`/`accent` finish the critter; `tag` is the floating-label suffix.
 */
export interface AnimalStyle {
  body: string;
  belly: string;
  accent: string;
  tag: string;
}

export const ANIMAL_STYLES: Record<string, AnimalStyle> = {
  cat: { body: '#9a8c7a', belly: '#f1e6d4', accent: '#5b4a36', tag: 'cat' },
  dog: { body: '#c79a5b', belly: '#f3e2c0', accent: '#8a6b3a', tag: 'dog' },
};

/** Resolve an Animal style by species, defaulting to the cat tint. */
export function animalStyle(species: string): AnimalStyle {
  return ANIMAL_STYLES[species] ?? ANIMAL_STYLES.cat;
}

/**
 * The chaos magenta for an animal accent (chaotic critters + chaos-feed
 * register). Mirrors --marker-animal in inspector-tokens.css so the 3D accent
 * and the 2D feed/timeline read as the SAME magenta. This is a WebGL material
 * color (the 3D scene's own palette), kept in lockstep with the DOM token by
 * intent rather than by import.
 */
export const ANIMAL_CHAOS_MAGENTA = '#d957d9';

/**
 * A satellite world position for a structure that sits NEAR (not on top of) a
 * place's structure. Buildings ring the place center on a stable angle derived
 * from the building id, so two structures at the same place don't overlap.
 */
export function buildingSpot(
  center: WorldPoint,
  buildingId: string,
  radius = 5.5,
): WorldPoint {
  const angle = hashUnit(buildingId) * Math.PI * 2;
  return {
    x: center.x + Math.cos(angle) * radius,
    z: center.z + Math.sin(angle) * radius,
  };
}

/** Stable pseudo-random in [0,1) from a string seed (for scenery scatter). */
export function hashUnit(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  // map to [0,1)
  return ((h >>> 0) % 100000) / 100000;
}
