/**
 * worldSpace tests — EM-130 (kind → style mapping + humanized kind labels) and
 * EM-131 (deterministic building slot layout). Pure functions only; no canvas.
 */

import { describe, expect, it } from 'vitest';
import {
  BUILDING_STYLES,
  SLOT_BASE_RADIUS,
  buildingStyle,
  humanizeKind,
  slotLayout,
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
