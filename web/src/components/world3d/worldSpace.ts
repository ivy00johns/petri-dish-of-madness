/**
 * worldSpace — shared constants & helpers for the cozy 3D village.
 *
 * World mapping (per the build contract):
 *   SIZE = 66
 *   worldX = (place.x / 1000 - 0.5) * SIZE
 *   worldZ = (place.y / 1000 - 0.5) * SIZE
 * Ground is the XZ plane, Y is up.
 *
 * Wave C (EM-149): SIZE retuned 40 → 66 so the 15-place district town
 * breathes — intra-district spacing (≥60 logical) lands at ~4 world units,
 * comfortably past the 4.2 slot-ring pitch, and district centroids (≥250
 * logical) sit ~16.5 apart. The mapping math itself is unchanged.
 *
 * Wave D1.5: SIZE stays 66 and now the city IS the world — a compact 5×5
 * block grid spanning ~±33 centered on the origin (the decorative D1 ring
 * and its WORLD_REACH sprawl are gone). WORLD_REACH is the half-extent the
 * terrain, pan clamp, fog and camera distances are tuned against: city span
 * + a small grass apron.
 */

import type { Place, PlaceKind, WorldEvent } from '../../types';

/** Edge length of the city ground square in world units (city span ≈ 66). */
export const SIZE = 66;

/**
 * Half-extent of the FULL scene envelope — the compact city + grass apron
 * (Wave D1.5). Ground plane, pan bounds, fog and camera distances are tuned
 * against this, NOT against SIZE. 0.85 × 66 ≈ 56.1 covers the grid's ±33
 * with ~23 units of grass apron.
 */
export const WORLD_REACH = SIZE * 0.85;

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
 * label suffix. Unknown kinds are keyword-mapped onto an existing palette where
 * possible (EM-130), otherwise they take the neutral BUILDING style — and their
 * tag is always the humanized raw kind, never a borrowed style name.
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
  // EM-130: the NEUTRAL fallback — a generic structure, deliberately distinct
  // from monument (cream walls + timber roof, reusing tints already in this
  // palette: clocktower body, workshop accent, clocktower accent).
  building:   { body: '#efe3c4', roof: '#c98b3a', accent: '#ffd27f', tag: 'Building' },
};

/**
 * EM-130: keyword → palette mapping for emergent (agent-invented) kinds, tried
 * in order with case-insensitive SUBSTRING match on the raw kind. Order is
 * load-bearing: garden's `bed` must beat house's `den` (both ⊂ "garden…"), and
 * library's `archive` must beat monument's `arch`.
 */
const KIND_KEYWORD_STYLES: ReadonlyArray<readonly [readonly string[], string]> = [
  [['garden', 'orchard', 'grove', 'bed'], 'garden'],
  [['farm'], 'farm'],
  [['library', 'school', 'archive'], 'library'],
  [['market', 'stall', 'shop', 'booth', 'bazaar'], 'workshop'],
  [['hall', 'civic', 'center', 'centre', 'fair', 'pavilion'], 'clocktower'],
  [['house', 'home', 'inn', 'shelter', 'den'], 'house'],
  [['monument', 'statue', 'arch'], 'monument'],
];

/**
 * EM-130: humanize a raw building kind for display — snake/kebab case becomes
 * Title Case words ("prepare_beds" → "Prepare Beds"). Junk (empty or only
 * separators) falls back to "Building".
 */
export function humanizeKind(kind: string): string {
  const words = kind.replace(/[_-]+/g, ' ').trim().replace(/\s+/g, ' ');
  if (!words) return 'Building';
  return words
    .split(' ')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

/**
 * Resolve a Building style by kind (EM-130). Exact keys keep their curated
 * tag; emergent kinds borrow a palette via keyword match (or take the neutral
 * `building` style) but ALWAYS carry the humanized raw kind as their tag, so a
 * market stall is never labeled "Monument".
 */
export function buildingStyle(kind: string): BuildingStyle {
  // Own-property check: kinds are model-authored strings — 'constructor' etc.
  // must not resolve through the prototype chain.
  const exact = Object.prototype.hasOwnProperty.call(BUILDING_STYLES, kind)
    ? BUILDING_STYLES[kind]
    : undefined;
  if (exact) return exact;
  const lower = kind.toLowerCase();
  const tag = humanizeKind(kind);
  for (const [keywords, styleKey] of KIND_KEYWORD_STYLES) {
    if (keywords.some((k) => lower.includes(k))) {
      return { ...BUILDING_STYLES[styleKey], tag };
    }
  }
  return { ...BUILDING_STYLES.building, tag };
}

/**
 * EM-122: the small set of DISTINCT procedural operational meshes. Every
 * emergent building kind renders as exactly one of these silhouettes
 * (Structure.tsx owns the geometry; this module owns the kind → variant
 * mapping so it stays pure and testable).
 */
export type VariantKey =
  | 'garden'
  | 'farm'
  | 'workshop'
  | 'library'
  | 'clocktower'
  | 'house'
  | 'stall'
  | 'monument'
  | 'well'
  | 'generic';

/** Exact BUILDING_STYLES keys map straight to their obvious variant. */
const EXACT_VARIANTS: Record<string, VariantKey> = {
  clocktower: 'clocktower',
  garden: 'garden',
  workshop: 'workshop',
  farm: 'farm',
  library: 'library',
  house: 'house',
  monument: 'monument',
  building: 'generic',
};

/**
 * EM-122: keyword → variant mapping for emergent kinds, tried in order with
 * case-insensitive SUBSTRING match (same approach as KIND_KEYWORD_STYLES).
 * Order is load-bearing, mirroring EM-130's substring traps:
 *   - library's `archive` must beat monument's `arch`;
 *   - workshop's `workshop` must beat stall's `shop` (`shop` ⊂ "workshop");
 *   - clocktower's `light`/`tower` must beat house's `house` ("lighthouse",
 *     "watchtower").
 */
const VARIANT_KEYWORDS: ReadonlyArray<readonly [readonly string[], VariantKey]> = [
  [['garden', 'orchard', 'grove', 'herb', 'bed'], 'garden'],
  [['farm', 'field', 'grain', 'crop'], 'farm'],
  [['workshop', 'forge', 'smith', 'tool', 'craft'], 'workshop'],
  [['library', 'school', 'archive', 'book'], 'library'],
  [['clock', 'tower', 'watch', 'light'], 'clocktower'],
  [['stall', 'market', 'shop', 'booth', 'stand', 'bazaar'], 'stall'],
  [['well', 'fountain', 'water'], 'well'],
  [['house', 'home', 'cottage', 'inn', 'shelter', 'cabin'], 'house'],
  [['monument', 'statue', 'memorial', 'arch', 'shrine', 'obelisk'], 'monument'],
];

/**
 * EM-122: resolve which procedural operational mesh a building kind gets.
 * Exact palette keys map directly; emergent kinds are keyword-matched; the
 * rest fall back to the neutral `generic` silhouette.
 */
export function operationalVariant(kind: string): VariantKey {
  // Own-property check: see buildingStyle — prototype members are not variants.
  const exact = Object.prototype.hasOwnProperty.call(EXACT_VARIANTS, kind)
    ? EXACT_VARIANTS[kind]
    : undefined;
  if (exact) return exact;
  const lower = kind.toLowerCase();
  for (const [keywords, variant] of VARIANT_KEYWORDS) {
    if (keywords.some((k) => lower.includes(k))) return variant;
  }
  return 'generic';
}

/** EM-122: the charcoal/soot tone damaged-but-operational bodies lerp toward. */
export const SOOT_HEX = '#2f2a26';

/**
 * Cap on the soot mix at health 0 — a dying building reads scorched, not
 * pure charcoal (the `damaged` status renderer owns the full burn look).
 */
const MAX_SOOT_MIX = 0.78;

/** Parse #rgb or #rrggbb into [r, g, b] (0..255), or null if malformed. */
function parseHex(hex: string): [number, number, number] | null {
  const m3 = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(hex);
  if (m3) return [m3[1], m3[2], m3[3]].map((c) => parseInt(c + c, 16)) as [number, number, number];
  const m6 = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (m6) return [m6[1], m6[2], m6[3]].map((c) => parseInt(c, 16)) as [number, number, number];
  return null;
}

/**
 * EM-122: health-aware body tint for OPERATIONAL buildings. Pure: lerps `hex`
 * toward {@link SOOT_HEX} proportionally to missing health, so a half-burned
 * workshop LOOKS half-burned before it ever flips to `damaged`.
 *
 *   - health is clamped to [0, 100]; health >= 100 returns the input UNCHANGED;
 *   - darkening is monotonic in lost health, capped at MAX_SOOT_MIX;
 *   - output is always a valid lowercase #rrggbb hex;
 *   - malformed input (or a non-finite health) is returned untouched.
 */
export function healthTint(hex: string, health: number): string {
  if (!Number.isFinite(health)) return hex;
  const h = Math.max(0, Math.min(100, health));
  if (h >= 100) return hex;
  const rgb = parseHex(hex);
  if (!rgb) return hex;
  const soot = parseHex(SOOT_HEX)!;
  const t = ((100 - h) / 100) * MAX_SOOT_MIX;
  const mixed = rgb.map((c, i) => Math.round(c + (soot[i] - c) * t));
  return `#${mixed.map((c) => c.toString(16).padStart(2, '0')).join('')}`;
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

/** EM-131: minimum spacing between building slot centers (largest structure
 * footprint is ~3.6 world units, so 4.2 leaves breathing room for labels). */
export const SLOT_SPACING = 4.2;

/** EM-131: radius of the first slot ring — clears the place's own structure
 * (matches the legacy `buildingSpot` satellite distance). */
export const SLOT_BASE_RADIUS = 5.5;

/**
 * EM-131: deterministic slot layout for ALL buildings sharing one place.
 * Ids are sorted, then placed on concentric rings around the place anchor:
 * each ring holds as many slots as keep SLOT_SPACING along its circumference,
 * and the radius grows ring by ring. Pure function of (center, id list) —
 * no randomness, no clock — so the same world yields the same layout every
 * frame, reload, and input ordering. No slot ever sits on the anchor itself.
 */
export function slotLayout(
  center: WorldPoint,
  buildingIds: readonly string[],
): Map<string, WorldPoint> {
  const sorted = [...buildingIds].sort();
  const out = new Map<string, WorldPoint>();
  let placed = 0;
  for (let ring = 0; placed < sorted.length; ring++) {
    const radius = SLOT_BASE_RADIUS + ring * SLOT_SPACING;
    const capacity = Math.max(1, Math.floor((2 * Math.PI * radius) / SLOT_SPACING));
    const inRing = Math.min(capacity, sorted.length - placed);
    for (let s = 0; s < inRing; s++) {
      // spread the ring's occupants evenly; stagger alternate rings by half a
      // slot so buildings don't line up into radial spokes.
      const angle = ((s + (ring % 2) * 0.5) / inRing) * Math.PI * 2 - Math.PI / 2;
      out.set(sorted[placed + s], {
        x: center.x + Math.cos(angle) * radius,
        z: center.z + Math.sin(angle) * radius,
      });
    }
    placed += inRing;
  }
  return out;
}

/**
 * A satellite world position for a structure that sits NEAR (not on top of) a
 * place's structure, on a stable angle derived from the id. Buildings now use
 * `slotLayout` (EM-131); this remains for single satellites like the notice
 * board.
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
