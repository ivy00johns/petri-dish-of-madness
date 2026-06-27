/**
 * worldSpace tests — EM-130 (kind → style mapping + humanized kind labels),
 * EM-131 (deterministic building slot layout), and EM-122 (operational mesh
 * variants + health-aware soot tinting). Pure functions only; no canvas.
 */

import { describe, expect, it } from 'vitest';
import type { Agent, Place } from '../../types';
import {
  BUILDING_STYLES,
  SKIN_PALETTES,
  SLOT_BASE_RADIUS,
  SOOT_HEX,
  buildingStyle,
  healthTint,
  humanizeKind,
  operationalVariant,
  resolveCivicCenterId,
  resolveLivingOwner,
  skinPalette,
  slotLayout,
  type VariantKey,
  type WorldPoint,
} from './worldSpace';

// ── EM-130: humanizeKind ─────────────────────────────────────────────────────

describe('humanizeKind (EM-130)', () => {
  it('turns snake_case into Title Case words', () => {
    expect(humanizeKind('prepare_beds')).toBe('Prepare Beds');
    expect(humanizeKind('festival_booth')).toBe('Festival Booth');
    expect(humanizeKind('community')).toBe('Community');
  });

  it('handles kebab-case and mixed separators', () => {
    expect(humanizeKind('village-fair')).toBe('Village Fair');
    expect(humanizeKind('market_-_stall')).toBe('Market Stall');
  });

  it('falls back to "Building" for junk', () => {
    expect(humanizeKind('')).toBe('Building');
    expect(humanizeKind('___')).toBe('Building');
    expect(humanizeKind(' - ')).toBe('Building');
  });
});

// ── EM-130: buildingStyle mapping ────────────────────────────────────────────

describe('buildingStyle (EM-130)', () => {
  it('keeps curated tags for exact known kinds', () => {
    expect(buildingStyle('clocktower').tag).toBe('Clock Tower');
    expect(buildingStyle('garden').tag).toBe('Garden');
    expect(buildingStyle('monument').tag).toBe('Monument');
  });

  it('maps the live offender kinds onto existing palettes, never Monument', () => {
    const cases: Array<[kind: string, paletteKey: string, tag: string]> = [
      ['prepare_beds', 'garden', 'Prepare Beds'],
      ['village_fair', 'clocktower', 'Village Fair'],
      ['festival_booth', 'workshop', 'Festival Booth'],
      ['community', 'building', 'Community'],
    ];
    for (const [kind, paletteKey, tag] of cases) {
      const style = buildingStyle(kind);
      expect(style.body).toBe(BUILDING_STYLES[paletteKey].body);
      expect(style.roof).toBe(BUILDING_STYLES[paletteKey].roof);
      expect(style.tag).toBe(tag);
      expect(style.tag).not.toBe('Monument');
    }
  });

  it('keyword-maps common emergent kinds onto sensible palettes', () => {
    expect(buildingStyle('apple_orchard').roof).toBe(BUILDING_STYLES.garden.roof);
    expect(buildingStyle('wheat_farm_plot').roof).toBe(BUILDING_STYLES.farm.roof);
    expect(buildingStyle('night_market').roof).toBe(BUILDING_STYLES.workshop.roof);
    expect(buildingStyle('community_center').roof).toBe(BUILDING_STYLES.clocktower.roof);
    expect(buildingStyle('storm_shelter').roof).toBe(BUILDING_STYLES.house.roof);
    expect(buildingStyle('founders_statue').roof).toBe(BUILDING_STYLES.monument.roof);
  });

  it('matches keywords case-insensitively', () => {
    expect(buildingStyle('Village_FAIR').roof).toBe(BUILDING_STYLES.clocktower.roof);
    expect(buildingStyle('MARKET').roof).toBe(BUILDING_STYLES.workshop.roof);
  });

  it('orders the keyword table to dodge substring traps', () => {
    // "archive" contains "arch" → must hit library, not monument.
    expect(buildingStyle('town_archive').roof).toBe(BUILDING_STYLES.library.roof);
    // "garden_shed"… "garden" contains "den" → must hit garden, not house.
    expect(buildingStyle('herb_garden').roof).toBe(BUILDING_STYLES.garden.roof);
  });

  it('unknown kinds get the neutral building style, distinct from monument', () => {
    const style = buildingStyle('xyzzy');
    expect(style.body).toBe(BUILDING_STYLES.building.body);
    expect(style.tag).toBe('Xyzzy');
    expect(BUILDING_STYLES.building.roof).not.toBe(BUILDING_STYLES.monument.roof);
    expect(BUILDING_STYLES.building.body).not.toBe(BUILDING_STYLES.monument.body);
  });

  it('keyword-mapped and fallback tags are the humanized raw kind, never the style name', () => {
    expect(buildingStyle('market_stall').tag).toBe('Market Stall'); // not "Workshop"
    expect(buildingStyle('mystery_lodge').tag).toBe('Mystery Lodge'); // not "Building"
  });
});

// ── EM-122: operationalVariant ───────────────────────────────────────────────

describe('operationalVariant (EM-122)', () => {
  it('maps exact BUILDING_STYLES keys to their obvious variant', () => {
    expect(operationalVariant('clocktower')).toBe('clocktower');
    expect(operationalVariant('garden')).toBe('garden');
    expect(operationalVariant('workshop')).toBe('workshop');
    expect(operationalVariant('farm')).toBe('farm');
    expect(operationalVariant('library')).toBe('library');
    expect(operationalVariant('house')).toBe('house');
    expect(operationalVariant('monument')).toBe('monument');
    // the neutral palette key is the generic silhouette
    expect(operationalVariant('building')).toBe('generic');
  });

  it('keyword-maps realistic emergent kinds onto distinct variants', () => {
    const cases: Array<[kind: string, variant: VariantKey]> = [
      ['herb_garden', 'garden'],
      ['apple_orchard', 'garden'],
      ['flower_bed', 'garden'],
      ['grain_farm', 'farm'],
      ['wheat_field', 'farm'],
      ['blacksmith_forge', 'workshop'],
      ['tool_shed', 'workshop'],
      ['village_school', 'library'],
      ['watchtower', 'clocktower'],
      ['market_stall', 'stall'],
      ['trading_booth', 'stall'],
      ['night_market', 'stall'],
      ['memorial_arch', 'monument'],
      ['founders_statue', 'monument'],
      ['roadside_shrine', 'monument'],
      ['community_well', 'well'],
      ['stone_fountain', 'well'],
      ['storm_shelter', 'house'],
      ['cozy_cottage', 'house'],
    ];
    for (const [kind, variant] of cases) {
      expect(operationalVariant(kind), kind).toBe(variant);
    }
  });

  it('matches case-insensitively', () => {
    expect(operationalVariant('Herb_GARDEN')).toBe('garden');
    expect(operationalVariant('WATCHTOWER')).toBe('clocktower');
  });

  it('orders the keyword table to dodge substring traps', () => {
    // "archive" contains "arch" → library, not monument.
    expect(operationalVariant('town_archive')).toBe('library');
    // "lighthouse" contains "house" → clocktower (tall light), not house.
    expect(operationalVariant('old_lighthouse')).toBe('clocktower');
    // "workshop" contains "shop" → workshop, not stall.
    expect(operationalVariant('repair_workshop')).toBe('workshop');
  });

  it('unknown kinds fall back to generic', () => {
    expect(operationalVariant('xyzzy')).toBe('generic');
    expect(operationalVariant('community')).toBe('generic');
    expect(operationalVariant('')).toBe('generic');
  });

  it('prototype-member kinds never resolve through the prototype chain', () => {
    // Kinds are model-authored strings — these crashed the canvas pre-guard.
    for (const evil of ['constructor', 'toString', 'hasOwnProperty', '__proto__']) {
      expect(operationalVariant(evil)).toBe('generic');
      const style = buildingStyle(evil);
      expect(typeof style.body).toBe('string');
      expect(style.body.startsWith('#')).toBe(true);
    }
  });
});

// ── EM-208 H3: zoo style + variant ──────────────────────────────────────────

describe('buildingStyle("zoo") (EM-208 H3)', () => {
  it('resolves to the zoo palette with tag "Zoo"', () => {
    const style = buildingStyle('zoo');
    expect(style.tag).toBe('Zoo');
    expect(style.body).toBe(BUILDING_STYLES.zoo.body);
    expect(style.roof).toBe(BUILDING_STYLES.zoo.roof);
  });

  it('keyword-maps menagerie/enclosure/habitat/sanctuary to zoo palette with humanized tag', () => {
    const cases: Array<[string, string]> = [
      ['city_menagerie', 'City Menagerie'],
      ['animal_enclosure', 'Animal Enclosure'],
      ['wildlife_habitat', 'Wildlife Habitat'],
      ['nature_sanctuary', 'Nature Sanctuary'],
    ];
    for (const [kind, tag] of cases) {
      const style = buildingStyle(kind);
      expect(style.body, kind).toBe(BUILDING_STYLES.zoo.body);
      expect(style.tag, kind).toBe(tag);
    }
  });

  it('unknown kind still falls back to generic with humanized tag (fallback guarantee)', () => {
    const style = buildingStyle('xyzzy_tower_thing');
    expect(style.body).toBe(BUILDING_STYLES.building.body);
    expect(style.tag).toBe('Xyzzy Tower Thing');
    expect(style.tag).not.toBe('Zoo');
  });
});

describe('operationalVariant("zoo") (EM-208 H3)', () => {
  it('maps exact "zoo" kind to the zoo variant', () => {
    expect(operationalVariant('zoo')).toBe('zoo');
  });

  it('keyword-maps zoo-related kinds to zoo variant', () => {
    expect(operationalVariant('city_zoo')).toBe('zoo');
    expect(operationalVariant('animal_enclosure')).toBe('zoo');
    expect(operationalVariant('wildlife_habitat')).toBe('zoo');
    expect(operationalVariant('nature_sanctuary')).toBe('zoo');
    expect(operationalVariant('wild_menagerie')).toBe('zoo');
  });

  it('unknown kind still falls back to generic (fallback guarantee)', () => {
    expect(operationalVariant('xyzzy')).toBe('generic');
    expect(operationalVariant('')).toBe('generic');
  });
});

// ── EM-217 (Wave K): build-type catalog ──────────────────────────────────────
//
// Each menu type the propose_project prompt surfaces (tavern/market/smithy/
// school/temple/clinic/park/granary/well, plus the existing kinds) resolves to
// a DISTINCT palette + curated label AND its best-available vendored silhouette
// — while an off-menu kind still resolves to the neutral fallback (no dead
// turn), and the EM-130 humanizeKind tag behavior stays intact.

const CATALOG_TYPES = [
  'tavern', 'market', 'smithy', 'school', 'temple',
  'clinic', 'park', 'granary', 'well',
] as const;

describe('build-type catalog — buildingStyle (EM-217)', () => {
  it('gives every catalog type its own curated tag', () => {
    const tags: Record<(typeof CATALOG_TYPES)[number], string> = {
      tavern: 'Tavern', market: 'Market', smithy: 'Smithy', school: 'School',
      temple: 'Temple', clinic: 'Clinic', park: 'Park', granary: 'Granary',
      well: 'Well',
    };
    for (const t of CATALOG_TYPES) {
      expect(buildingStyle(t).tag, t).toBe(tags[t]);
    }
  });

  it('gives every catalog type a DISTINCT body palette (no two collide)', () => {
    const bodies = CATALOG_TYPES.map((t) => buildingStyle(t).body);
    expect(new Set(bodies).size).toBe(CATALOG_TYPES.length);
    // …and none is the neutral fallback body (each is its own thing).
    for (const t of CATALOG_TYPES) {
      expect(buildingStyle(t).body, t).not.toBe(BUILDING_STYLES.building.body);
    }
  });

  it('every catalog type is a well-formed BuildingStyle (valid hexes)', () => {
    for (const t of CATALOG_TYPES) {
      const s = buildingStyle(t);
      for (const c of [s.body, s.roof, s.accent]) {
        expect(c, `${t}:${c}`).toMatch(/^#[0-9a-f]{6}$/i);
      }
    }
  });

  it('keeps the existing curated kinds intact (no regression)', () => {
    expect(buildingStyle('clocktower').tag).toBe('Clock Tower');
    expect(buildingStyle('garden').tag).toBe('Garden');
    expect(buildingStyle('zoo').tag).toBe('Zoo');
  });
});

describe('build-type catalog — operationalVariant (EM-217/EM-216)', () => {
  it('pins every catalog type to its own distinct variant (EM-216 GLBs)', () => {
    // EM-216 gave the build-types their OWN variant + GLB (was a shared
    // silhouette pre-acquisition). park/well keep their shared greenery/fountain.
    const variants: Record<(typeof CATALOG_TYPES)[number], VariantKey> = {
      tavern: 'tavern', market: 'market', smithy: 'smithy', school: 'school',
      temple: 'temple', clinic: 'clinic', park: 'garden', granary: 'granary',
      well: 'well',
    };
    for (const t of CATALOG_TYPES) {
      expect(operationalVariant(t), t).toBe(variants[t]);
    }
  });

  it('off-menu / emergent forms of the new types still resolve sensibly (no dead turn)', () => {
    const cases: Array<[string, VariantKey]> = [
      ['old_tavern', 'house'],
      ['village_pub', 'house'],
      ['night_market', 'stall'],
      ['blacksmith_smithy', 'workshop'],
      ['grand_temple', 'monument'],
      ['stone_chapel', 'monument'],
      ['riverside_park', 'garden'],
      ['stone_granary', 'farm'],
      ['grain_silo', 'farm'],
    ];
    for (const [kind, variant] of cases) {
      expect(operationalVariant(kind), kind).toBe(variant);
    }
  });

  it('a truly off-menu kind still falls back to generic (EM-130 permissive)', () => {
    expect(operationalVariant('moon_temple_of_xyzzy')).toBe('monument'); // 'temple' substring
    expect(operationalVariant('xyzzy_thing')).toBe('generic');
    expect(buildingStyle('xyzzy_thing').tag).toBe('Xyzzy Thing'); // humanized, intact
  });

  it('preserves the EM-122/EM-130 substring-trap ordering', () => {
    // 'archive' (library) must still beat 'arch' (monument).
    expect(operationalVariant('town_archive')).toBe('library');
    // 'lighthouse' (clocktower) must still beat 'house'.
    expect(operationalVariant('old_lighthouse')).toBe('clocktower');
    // night_market keeps its EM-130 palette (workshop), unchanged by EM-217.
    expect(buildingStyle('night_market').roof).toBe(BUILDING_STYLES.workshop.roof);
  });
});

// ── EM-225: census kind → variant mapping (stop the generic collapse) ─────────
//
// The agent-authored `kind` vocabulary (frequency across 1064 snapshots) was
// collapsing ~86% of buildings onto the neutral `generic` silhouette. This maps
// the high-frequency emergent kinds onto real, distinct silhouettes AND keeps
// their buildingStyle palette in lockstep with that variant. Each pair below is
// [kind, intendedVariant] — operationalVariant() must hit the variant, and
// buildingStyle() must use that variant's OWN palette (non-neutral) with the
// humanized raw kind as the tag.

describe('census kind → variant mapping (EM-225)', () => {
  // kind → (variant, paletteKey used by buildingStyle). For these the variant
  // name and the BUILDING_STYLES palette key coincide.
  const MAPPED: Array<[kind: string, variant: VariantKey]> = [
    // workshop ⇐ collective, guild
    ['collective', 'workshop'],
    ['guild', 'workshop'],
    // smithy ⇐ repair, rebuild, maintenance
    ['repair', 'smithy'],
    ['rebuild', 'smithy'],
    ['maintenance', 'smithy'],
    // stall ⇐ commerce, commercial
    ['commerce', 'stall'],
    ['commercial', 'stall'],
    // clocktower ⇐ governance, hall, council, security
    ['governance', 'clocktower'],
    ['hall', 'clocktower'],
    ['council', 'clocktower'],
    ['security', 'clocktower'],
    // temple ⇐ rule, policy, charter, law
    ['rule', 'temple'],
    ['policy', 'temple'],
    ['charter', 'temple'],
    ['law', 'temple'],
    // monument ⇐ decor, plaza, ornament
    ['decor', 'monument'],
    ['plaza', 'monument'],
    ['ornament', 'monument'],
    // dock ⇐ infrastructure, terminal, depot
    ['infrastructure', 'dock'],
    ['terminal', 'dock'],
    ['depot', 'dock'],
    // bank ⇐ audit, ledger, finance, exchange
    ['audit', 'bank'],
    ['ledger', 'bank'],
    ['finance', 'bank'],
    ['exchange', 'bank'],
    // theater ⇐ event, festival, culture
    ['event', 'theater'],
    ['festival', 'theater'],
    ['culture', 'theater'],
    // clinic ⇐ lab, research, investigation
    ['lab', 'clinic'],
    ['research', 'clinic'],
    ['investigation', 'clinic'],
    // bathhouse ⇐ amenity, wellness
    ['amenity', 'bathhouse'],
    ['wellness', 'bathhouse'],
    // library ⇐ record, registry
    ['record', 'library'],
    ['registry', 'library'],
  ];

  // The variant a buildingStyle palette key is keyed by (variant === paletteKey
  // for every target above — stall maps to the 'stall'… wait: stall has no own
  // BUILDING_STYLES palette, it shares 'workshop'. Map variant → palette key.)
  const PALETTE_FOR_VARIANT: Partial<Record<VariantKey, string>> = {
    workshop: 'workshop',
    smithy: 'smithy',
    stall: 'workshop', // stall silhouette shares the workshop palette (market kin)
    clocktower: 'clocktower',
    temple: 'temple',
    monument: 'monument',
    dock: 'dock',
    bank: 'bank',
    theater: 'theater',
    clinic: 'clinic',
    bathhouse: 'bathhouse',
    library: 'library',
  };

  it('resolves each census kind to its intended distinct variant', () => {
    for (const [kind, variant] of MAPPED) {
      expect(operationalVariant(kind), kind).toBe(variant);
    }
  });

  it('gives each census kind a NON-neutral palette matching its variant', () => {
    for (const [kind, variant] of MAPPED) {
      const paletteKey = PALETTE_FOR_VARIANT[variant]!;
      const style = buildingStyle(kind);
      expect(style.body, `${kind} body`).toBe(BUILDING_STYLES[paletteKey].body);
      expect(style.roof, `${kind} roof`).toBe(BUILDING_STYLES[paletteKey].roof);
      // never the neutral generic palette. (The clocktower BODY happens to share
      // the neutral cream body hex, so assert on the ROOF — which is distinct for
      // every mapped variant — to prove the style is non-neutral.)
      expect(style.roof, `${kind} not-neutral roof`).not.toBe(BUILDING_STYLES.building.roof);
    }
  });

  it('tags each census kind with the humanized raw kind, not the style name', () => {
    expect(buildingStyle('collective').tag).toBe('Collective');
    expect(buildingStyle('governance').tag).toBe('Governance');
    expect(buildingStyle('infrastructure').tag).toBe('Infrastructure');
    expect(buildingStyle('exchange_board').tag).toBe('Exchange Board');
    expect(buildingStyle('community_event').tag).toBe('Community Event');
  });

  it('catches the observed COMPOUND kinds via substring rows', () => {
    // 'community_event' → theater (via 'event'); NOT generic, NOT house.
    expect(operationalVariant('community_event')).toBe('theater');
    expect(buildingStyle('community_event').roof).toBe(BUILDING_STYLES.theater.roof);
    // 'exchange_board' → bank (via 'exchange').
    expect(operationalVariant('exchange_board')).toBe('bank');
    expect(buildingStyle('exchange_board').roof).toBe(BUILDING_STYLES.bank.roof);
  });

  it('KEEPS social / community / commons on the generic silhouette', () => {
    for (const kind of ['social', 'community', 'commons']) {
      expect(operationalVariant(kind), kind).toBe('generic');
      expect(buildingStyle(kind).body, kind).toBe(BUILDING_STYLES.building.body);
    }
  });

  // ── adversarial near-misses: the substring traps must still hold ───────────
  it('preserves every documented substring trap against the new tokens', () => {
    // 'archive' (library) must still beat monument's 'arch'.
    expect(operationalVariant('town_archive')).toBe('library');
    expect(buildingStyle('town_archive').roof).toBe(BUILDING_STYLES.library.roof);
    // 'watchtower' / 'lighthouse' → clocktower, never house.
    expect(operationalVariant('watchtower')).toBe('clocktower');
    expect(operationalVariant('old_lighthouse')).toBe('clocktower');
    // 'workshop' contains 'shop' → workshop, not stall.
    expect(operationalVariant('repair_workshop')).toBe('workshop');
    // garden's 'bed' beats house's 'den'.
    expect(operationalVariant('herb_garden')).toBe('garden');
  });

  it('the short/dangerous tokens (lab/law/rule/hall) do NOT match as substrings', () => {
    // 'lab' must NOT catch 'collaborative' / 'available' (clinic is EXACT-only).
    expect(operationalVariant('collaborative')).toBe('generic');
    expect(operationalVariant('available_space')).toBe('generic');
    expect(operationalVariant('collaborative_studio')).toBe('generic');
    // 'law' must NOT catch 'lawn' (temple is EXACT-only for 'law').
    expect(operationalVariant('lawn')).toBe('generic');
    // 'rule' must NOT catch 'ruler_shop' style words via substring (EXACT-only).
    expect(operationalVariant('overruled_thing')).toBe('generic');
    // 'hall' must NOT catch 'shallow' / 'marshall' (clocktower is EXACT-only).
    expect(operationalVariant('shallow_pool')).toBe('generic');
    // 'commerc' keyword is fine (no false friends), but verify it stays scoped.
    expect(operationalVariant('commercial')).toBe('stall');
  });

  it("the '_event' compound row does NOT leak into the prevent / eventual families", () => {
    // The bare 'event' kind is handled by EXACT_VARIANTS; the substring row uses
    // '_event' (leading underscore) so it catches ONLY 'community_event'-style
    // compounds — never 'event' ⊂ 'prevent'/'prevention'/'preventive'/'eventual'.
    expect(operationalVariant('event')).toBe('theater'); // exact
    expect(operationalVariant('community_event')).toBe('theater'); // _event compound
    for (const kind of [
      'preventive_clinic', 'prevention_office', 'crime_prevention_unit',
      'eventual_plan', 'uneventful_office', 'health_prevention_center',
    ]) {
      expect(operationalVariant(kind), kind).not.toBe('theater');
    }
    // The sharpest case: a 'preventive_clinic' is neutral generic, never a pink
    // theater (clinic is EXACT-only, so it cannot fall back to clinic either).
    expect(operationalVariant('preventive_clinic')).toBe('generic');
    expect(buildingStyle('preventive_clinic').roof).not.toBe(BUILDING_STYLES.theater.roof);
  });

  it('NEVER captures fund / treasury kinds (those render as treasury objects)', () => {
    // These must fall through to generic here — isFundBuilding owns them.
    for (const kind of ['town_fund', 'treasury', 'shared_treasury', 'reserve_fund']) {
      expect(operationalVariant(kind), kind).toBe('generic');
    }
  });

  it('stays pure / deterministic for the new kinds (EM-155 replay invariant)', () => {
    for (const [kind] of MAPPED) {
      expect(operationalVariant(kind)).toBe(operationalVariant(kind));
      expect(buildingStyle(kind).body).toBe(buildingStyle(kind).body);
    }
  });
});

// ── EM-220 (Wave K): skinPalette ──────────────────────────────────────────────
//
// An owner-set named skin overrides the operational BODY color; an unknown /
// absent skin is ignored (→ null) so the kind palette body stands. Pure +
// own-property hardened against model-authored skin strings.

describe('skinPalette (EM-220)', () => {
  it('resolves every named skin to a valid #rrggbb body hex', () => {
    for (const name of Object.keys(SKIN_PALETTES)) {
      const hex = skinPalette(name);
      expect(hex, name).toBe(SKIN_PALETTES[name]);
      expect(hex!).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it('ships the documented friendly names (rose/sky/sage/amber/slate/plum)', () => {
    for (const name of ['rose', 'sky', 'sage', 'amber', 'slate', 'plum']) {
      expect(skinPalette(name), name).not.toBeNull();
    }
  });

  it('every skin is a DISTINCT color', () => {
    const hexes = Object.values(SKIN_PALETTES);
    expect(new Set(hexes).size).toBe(hexes.length);
  });

  it('returns null for an absent skin (unknown → kind palette body stands)', () => {
    expect(skinPalette(null)).toBeNull();
    expect(skinPalette(undefined)).toBeNull();
    expect(skinPalette('')).toBeNull();
    expect(skinPalette('chartreuse')).toBeNull();
    expect(skinPalette('ROSE')).toBeNull(); // case-sensitive, exact names only
  });

  it('never resolves a prototype-member skin through the prototype chain', () => {
    for (const evil of ['constructor', 'toString', 'hasOwnProperty', '__proto__']) {
      expect(skinPalette(evil), evil).toBeNull();
    }
  });
});

// ── EM-122: healthTint ───────────────────────────────────────────────────────

/** Channel sum (0..765) as a simple brightness proxy for monotonicity checks. */
function brightness(hex: string): number {
  return (
    parseInt(hex.slice(1, 3), 16) +
    parseInt(hex.slice(3, 5), 16) +
    parseInt(hex.slice(5, 7), 16)
  );
}

describe('healthTint (EM-122)', () => {
  it('is the identity at health 100 and above (input returned unchanged)', () => {
    expect(healthTint('#f2cc8f', 100)).toBe('#f2cc8f');
    expect(healthTint('#F2CC8F', 100)).toBe('#F2CC8F'); // exact string, case kept
    expect(healthTint('#f2cc8f', 150)).toBe('#f2cc8f'); // clamped high
  });

  it('clamps health below zero to the health-0 tint', () => {
    expect(healthTint('#f2cc8f', -40)).toBe(healthTint('#f2cc8f', 0));
  });

  it('is pure: identical input → identical output', () => {
    expect(healthTint('#cdebb0', 37)).toBe(healthTint('#cdebb0', 37));
  });

  it('always returns a valid #rrggbb hex when tinting', () => {
    for (const h of [0, 1, 25, 50, 75, 99]) {
      expect(healthTint('#f2cc8f', h)).toMatch(/^#[0-9a-f]{6}$/);
    }
    // short-hex input is normalized while tinting
    expect(healthTint('#fc8', 50)).toMatch(/^#[0-9a-f]{6}$/);
  });

  it('darkens monotonically toward soot as health drops', () => {
    const steps = [100, 80, 60, 40, 20, 0].map((h) => brightness(healthTint('#f2cc8f', h)));
    for (let i = 1; i < steps.length; i++) {
      expect(steps[i]).toBeLessThanOrEqual(steps[i - 1]);
    }
    expect(steps[steps.length - 1]).toBeLessThan(steps[0]);
  });

  it('never reaches pure charcoal — the damaged renderer owns the full burn', () => {
    const scorched = healthTint('#f2cc8f', 0);
    expect(scorched).not.toBe(SOOT_HEX);
    expect(brightness(scorched)).toBeGreaterThan(brightness(SOOT_HEX));
  });

  it('returns malformed input untouched instead of throwing', () => {
    expect(healthTint('not-a-hex', 50)).toBe('not-a-hex');
    expect(healthTint('#f2cc8f', Number.NaN)).toBe('#f2cc8f');
  });
});

// ── EM-131: slotLayout ───────────────────────────────────────────────────────

const CENTER: WorldPoint = { x: 4, z: -6 };

function ids(n: number): string[] {
  return Array.from({ length: n }, (_, i) => `bld-${String(i).padStart(2, '0')}`);
}

function dist(a: WorldPoint, b: WorldPoint): number {
  return Math.hypot(a.x - b.x, a.z - b.z);
}

describe('slotLayout (EM-131)', () => {
  it('gives every building a distinct, well-separated position', () => {
    const layout = slotLayout(CENTER, ids(12)); // spills past the first ring
    expect(layout.size).toBe(12);
    const points = [...layout.values()];
    for (let i = 0; i < points.length; i++) {
      for (let j = i + 1; j < points.length; j++) {
        expect(dist(points[i], points[j])).toBeGreaterThan(3.5);
      }
    }
  });

  it('never places a slot on the place anchor itself', () => {
    for (const p of slotLayout(CENTER, ids(12)).values()) {
      expect(dist(p, CENTER)).toBeGreaterThanOrEqual(SLOT_BASE_RADIUS - 1e-9);
    }
  });

  it('is deterministic: identical input → identical layout', () => {
    const a = slotLayout(CENTER, ids(7));
    const b = slotLayout(CENTER, ids(7));
    expect([...a.entries()]).toEqual([...b.entries()]);
  });

  it('is stable under input reordering (pure function of the sorted id set)', () => {
    const forward = ids(9);
    const shuffled = [forward[4], forward[8], forward[0], forward[2], forward[6],
      forward[1], forward[7], forward[3], forward[5]];
    const a = slotLayout(CENTER, forward);
    const b = slotLayout(CENTER, shuffled);
    for (const id of forward) {
      expect(b.get(id)).toEqual(a.get(id));
    }
  });

  it('handles the empty and single-building cases', () => {
    expect(slotLayout(CENTER, []).size).toBe(0);
    const solo = slotLayout(CENTER, ['only']);
    expect(solo.size).toBe(1);
    expect(dist(solo.get('only')!, CENTER)).toBeCloseTo(SLOT_BASE_RADIUS, 6);
  });
});

// ── Wave H4 (EM-209): resolveLivingOwner ─────────────────────────────────────
//
// Locks the THREE pet-bond layers in agreement on a single predicate
// (owner exists AND is alive):
//   • backend  — _owner_of() returns None for a dead owner ⇒ pet wanders
//     (test_pet_with_dead_or_missing_owner_reverts_to_wandering)
//   • RosterStrip — drops the bond line via `a.alive` (the "bond dies with the
//     owner" test)
//   • CozyWorld 3D — gates the follow/leash ownerPos on this helper so the pet
//     never leashes to a dead owner's corpse position.
// to_snapshot() serializes dead agents and the backend never clears owner_id
// on owner death, so a dead owner's id keeps dangling — this is the guard.

function agent(id: string, alive: boolean): Agent {
  return { id, alive } as Agent;
}

describe('resolveLivingOwner (Wave H4 EM-209 — pet bond agreement)', () => {
  const owner = agent('agent-owner', true);
  const deadOwner = agent('agent-dead', false);
  const bystander = agent('agent-other', true);
  const roster: Agent[] = [owner, deadOwner, bystander];

  it('returns the owner when it exists and is alive (pet follows/leashes)', () => {
    expect(resolveLivingOwner(roster, 'agent-owner')).toBe(owner);
  });

  it('returns undefined when the owner is DEAD (the dangling owner_id case)', () => {
    // The corpse is still in the snapshot, but the pet must revert to wander.
    expect(resolveLivingOwner(roster, 'agent-dead')).toBeUndefined();
  });

  it('returns undefined when owner_id points at no agent (missing owner)', () => {
    expect(resolveLivingOwner(roster, 'agent-ghost')).toBeUndefined();
  });

  it('returns undefined for an absent owner_id (unowned pet — null/undefined)', () => {
    expect(resolveLivingOwner(roster, null)).toBeUndefined();
    expect(resolveLivingOwner(roster, undefined)).toBeUndefined();
    expect(resolveLivingOwner(roster, '')).toBeUndefined();
  });

  it('matches by id, not position — never resolves a different living agent', () => {
    // A dead owner must NOT silently fall through to some other alive agent.
    expect(resolveLivingOwner(roster, 'agent-dead')).not.toBe(bystander);
    expect(resolveLivingOwner([], 'agent-owner')).toBeUndefined();
  });
});

// ── EM-183: resolveCivicCenterId (3D orbit home ↔ backend civic_center_id) ────

function place(id: string, kind: Place['kind'], extra: Partial<Place> = {}): Place {
  return { id, name: id, x: 500, y: 500, kind, description: '', ...extra };
}

describe('resolveCivicCenterId (EM-183 — town center vote)', () => {
  const townhall = place('townhall', 'governance');
  const plaza = place('plaza', 'social');
  const market = place('market', 'work');
  const town: Place[] = [townhall, plaza, market];

  it('returns the VOTED center when it names a real place', () => {
    expect(resolveCivicCenterId(town, 'market')).toBe('market');
    expect(resolveCivicCenterId(town, 'townhall')).toBe('townhall');
  });

  it('falls back to the plaza when no center is voted (default)', () => {
    expect(resolveCivicCenterId(town, '')).toBe('plaza');
    expect(resolveCivicCenterId(town, null)).toBe('plaza');
    expect(resolveCivicCenterId(town, undefined)).toBe('plaza');
  });

  it('ignores a dangling voted id (falls through to the plaza chain)', () => {
    // Matches the backend tolerance of a town_center_id whose place vanished.
    expect(resolveCivicCenterId(town, 'ghost-place')).toBe('plaza');
  });

  it('falls back to the first SOCIAL place when there is no plaza', () => {
    const noPlaza: Place[] = [townhall, place('green', 'social'), market];
    expect(resolveCivicCenterId(noPlaza, null)).toBe('green');
  });

  it('falls back to the first place when there is no plaza or social place', () => {
    const noSocial: Place[] = [townhall, market];
    expect(resolveCivicCenterId(noSocial, null)).toBe('townhall');
  });

  it('returns null for an empty world', () => {
    expect(resolveCivicCenterId([], null)).toBeNull();
    expect(resolveCivicCenterId([], 'market')).toBeNull();
  });
});
