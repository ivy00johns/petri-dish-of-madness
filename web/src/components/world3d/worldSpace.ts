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

import type { Agent, Place, PlaceKind, WorldEvent } from '../../types';

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
  // EM-208 H3: warm habitat palette — earthy tan walls, a terracotta/clay roof,
  // and a leafy green accent (the animal-pen ground and foliage tones).
  zoo:        { body: '#d4b896', roof: '#b5704a', accent: '#6aab5a', tag: 'Zoo' },
  // ── EM-217 (Wave K) build-type catalog ──────────────────────────────────
  // Each menu type a propose_project prompt offers gets its OWN distinct
  // palette + curated label, so a tavern never reads like a generic box (it
  // still resolves to its best vendored silhouette via EXACT_VARIANTS below).
  // These are WebGL material colors (THREE.Color), OUTSIDE the CSS token system.
  // tavern — warm ale-amber walls, deep oak roof, a hearth-orange accent.
  tavern:     { body: '#e3b86a', roof: '#7a4a2c', accent: '#ff9a4a', tag: 'Tavern' },
  // market — bright canvas-cream stalls, teal awning, a fresh-produce red accent.
  market:     { body: '#f4e3b8', roof: '#3a8f8a', accent: '#e8553a', tag: 'Market' },
  // smithy — sooty slate walls, iron-grey roof, an ember-orange forge accent.
  smithy:     { body: '#9a8c7e', roof: '#4a4640', accent: '#ff7a3a', tag: 'Smithy' },
  // school — chalk-cream walls, a slate-blue roof, brass accent (kin to library).
  school:     { body: '#ece4d2', roof: '#5b6f9c', accent: '#caa472', tag: 'School' },
  // temple — pale marble walls, a violet roof, a gilded accent (sacred register).
  temple:     { body: '#efe9dc', roof: '#6a5aa8', accent: '#ffd98a', tag: 'Temple' },
  // clinic — clean white walls, a soft mint roof, a caduceus-red accent.
  clinic:     { body: '#f3f1ea', roof: '#7ec8a8', accent: '#e35d5d', tag: 'Clinic' },
  // park — leafy ground, deep-green canopy roof, a blossom-pink accent.
  park:       { body: '#bfe39a', roof: '#4f8f4f', accent: '#ff8fb1', tag: 'Park' },
  // granary — golden-grain walls, a thatch-amber roof, a wheat accent (kin to farm).
  granary:    { body: '#ecd28a', roof: '#c08a3a', accent: '#e7b84f', tag: 'Granary' },
  // well — cool stone walls, a slate roof, a water-blue accent.
  well:       { body: '#cfc8bc', roof: '#7e766a', accent: '#5fa3c0', tag: 'Well' },
  // EM-130: the NEUTRAL fallback — a generic structure, deliberately distinct
  // from monument (cream walls + timber roof, reusing tints already in this
  // palette: clocktower body, workshop accent, clocktower accent).
  building:   { body: '#efe3c4', roof: '#c98b3a', accent: '#ffd27f', tag: 'Building' },
};

/**
 * EM-220 (Wave K): named building SKINS — an owner-set color override. A small
 * curated palette of friendly names → a single body hex. These are WebGL
 * material colors (THREE.Color), explicitly OUTSIDE the CSS design-token system
 * (the same convention as BUILDING_STYLES). The Structure renderer uses
 * skinPalette(building.skin) as the OPERATIONAL body color in place of the
 * kind palette's body, then composes healthTint on TOP (so soot still shows on
 * a re-skinned building). An unknown / absent skin is ignored (→ null) and the
 * kind palette body stands.
 */
export const SKIN_PALETTES: Record<string, string> = {
  rose:  '#e89bb0',
  sky:   '#9bc7e8',
  sage:  '#a9c99a',
  amber: '#e8b96a',
  slate: '#8a93a0',
  plum:  '#b08ac0',
};

/**
 * EM-220: resolve a building skin name to its body hex, or `null` when the skin
 * is absent/empty/unknown (caller falls back to the kind palette body). Pure;
 * own-property check so a model-authored skin string like 'constructor' can't
 * resolve through the prototype chain.
 */
export function skinPalette(skin: string | null | undefined): string | null {
  if (!skin) return null;
  return Object.prototype.hasOwnProperty.call(SKIN_PALETTES, skin)
    ? SKIN_PALETTES[skin]
    : null;
}

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
  [['zoo', 'menagerie', 'enclosure', 'habitat', 'sanctuary'], 'zoo'],
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
  | 'zoo'
  | 'generic';

/**
 * Exact BUILDING_STYLES keys map straight to their obvious variant.
 *
 * EM-217 (Wave K): the build-type catalog menu (tavern/market/smithy/school/
 * temple/clinic/park/granary/well) each pins to the best AVAILABLE vendored
 * silhouette + GLB — the type carries its OWN distinct palette/label
 * (BUILDING_STYLES above) while reusing a fitting EM-122 mesh/GLB so it renders
 * something real today (K0 ships fully distinct per-type GLBs later, wired with
 * zero further changes here). An off-menu kind still resolves through the
 * VARIANT_KEYWORDS fuzzy match below (EM-130 permissive fallback intact).
 */
const EXACT_VARIANTS: Record<string, VariantKey> = {
  clocktower: 'clocktower',
  garden: 'garden',
  workshop: 'workshop',
  farm: 'farm',
  library: 'library',
  house: 'house',
  monument: 'monument',
  zoo: 'zoo',
  // EM-217 build-type catalog → best available vendored variant/GLB
  tavern: 'house',      // cozy building (suburban GLB)
  market: 'stall',      // open-air storefront (commercial GLB)
  smithy: 'workshop',   // forge shed (industrial GLB)
  school: 'library',    // hall + columns (procedural library)
  temple: 'monument',   // plinth + spire (fountain/obelisk GLB)
  clinic: 'generic',    // clean civic block (commercial GLB)
  park: 'garden',       // planting beds / greenery (procedural)
  granary: 'farm',      // fenced plot + haystack (warehouse GLB)
  well: 'well',         // stone ring + roof (fountain GLB)
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
  // EM-217: 'park' joins garden (greenery); ordering keeps garden's substrings
  // ('bed') ahead of house's 'den' exactly as before.
  [['garden', 'orchard', 'grove', 'herb', 'park', 'bed'], 'garden'],
  // EM-217: 'granary'/'silo' join farm.
  [['farm', 'field', 'grain', 'granary', 'silo', 'crop'], 'farm'],
  // 'smith' already catches 'smithy'; 'forge' covers the EM-217 smithy type.
  [['workshop', 'forge', 'smith', 'tool', 'craft'], 'workshop'],
  [['library', 'school', 'archive', 'book'], 'library'],
  [['zoo', 'menagerie', 'enclosure', 'habitat', 'sanctuary'], 'zoo'],
  [['clock', 'tower', 'watch', 'light'], 'clocktower'],
  [['stall', 'market', 'shop', 'booth', 'stand', 'bazaar'], 'stall'],
  [['well', 'fountain', 'water'], 'well'],
  // EM-217: 'tavern'/'pub' join house (cozy building); 'inn' already here.
  [['house', 'home', 'cottage', 'tavern', 'pub', 'inn', 'shelter', 'cabin'], 'house'],
  // EM-217: 'temple'/'chapel' join monument (sacred landmark); 'shrine' already here.
  [['monument', 'statue', 'memorial', 'temple', 'chapel', 'arch', 'shrine', 'obelisk'], 'monument'],
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
  cat:     { body: '#9a8c7a', belly: '#f1e6d4', accent: '#5b4a36', tag: 'cat'     },
  dog:     { body: '#c79a5b', belly: '#f3e2c0', accent: '#8a6b3a', tag: 'dog'     },
  // EM-143: 5 new species — WebGL material palette, warm/distinct per flavor.
  // Russet-brown skittish hoarder.
  squirrel:{ body: '#8b5e3c', belly: '#d4a96a', accent: '#5c3318', tag: 'squirrel' },
  // Grey ransacker with pale mask highlight.
  raccoon: { body: '#7a7a82', belly: '#d8d5cc', accent: '#3c3c44', tag: 'raccoon' },
  // Tan/cream stubborn grazer.
  goat:    { body: '#c8b880', belly: '#ede8d0', accent: '#8a7848', tag: 'goat'    },
  // Orange-red cunning raider with white accent.
  fox:     { body: '#cc5c1a', belly: '#f5dcc0', accent: '#7a2a08', tag: 'fox'     },
  // Near-black thieving trickster with grey sheen.
  crow:    { body: '#2a2a32', belly: '#6a6a78', accent: '#18181f', tag: 'crow'    },
};

/** Resolve an Animal style by species, defaulting to the cat tint. */
export function animalStyle(species: string): AnimalStyle {
  return ANIMAL_STYLES[species] ?? ANIMAL_STYLES.cat;
}

/**
 * Shared species → emoji helper (EM-143). One source of truth used in
 * Critter.tsx, AnimalChaosFeed.tsx, and RosterStrip.tsx — no per-site drift.
 * Unknown species fall back to 🐾 (the FALLBACK GUARANTEE: never a hole).
 */
export function speciesEmoji(species: string): string {
  switch (species) {
    case 'cat':      return '🐱';
    case 'dog':      return '🐶';
    case 'squirrel': return '🐿️';
    case 'raccoon':  return '🦝';
    case 'goat':     return '🐐';
    case 'fox':      return '🦊';
    case 'crow':     return '🐦‍⬛';
    default:         return '🐾';
  }
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

/** EM-131: radius of the first slot ring — clears the place's own structure.
 * Wave D1.6: shrunk 5.5 → 4.6 so OVERFLOW buildings (slotLayout is now the
 * fallback past a landmark block's realLots, contracts/wave-d1.6.md §2) keep
 * their centers inside the 5.2u half-block instead of standing on the road. */
export const SLOT_BASE_RADIUS = 4.6;

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

/**
 * Wave H4 (EM-209) — resolve a pet's LIVING owner for the 3D follow/leash.
 *
 * The backend serializes ALL agents (alive AND dead) in to_snapshot() and
 * never clears `owner_id` when the owner dies, so a dead owner's id keeps
 * dangling on the pet. This helper mirrors the backend's `_owner_of()` (a
 * dead owner ⇒ None ⇒ pet reverts to wandering) and RosterStrip's bond-line
 * filter (drops the bond when the owner isn't `alive`): it returns the owner
 * agent only when it exists AND is alive, else `undefined`. Keeping all three
 * layers on this same predicate prevents the pet from leashing to its dead
 * owner's corpse position in the 3D village.
 */
export function resolveLivingOwner(
  agents: readonly Agent[],
  ownerId: string | null | undefined,
): Agent | undefined {
  if (!ownerId) return undefined;
  return agents.find((a) => a.id === ownerId && a.alive);
}
