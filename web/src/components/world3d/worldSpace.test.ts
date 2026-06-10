/**
 * worldSpace tests — EM-130 (kind → style mapping + humanized kind labels),
 * EM-131 (deterministic building slot layout), and EM-122 (operational mesh
 * variants + health-aware soot tinting). Pure functions only; no canvas.
 */

import { describe, expect, it } from 'vitest';
import {
  BUILDING_STYLES,
  SLOT_BASE_RADIUS,
  SOOT_HEX,
  buildingStyle,
  healthTint,
  humanizeKind,
  operationalVariant,
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
