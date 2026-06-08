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
