/**
 * Wave O (EM-260–263) — the religion narrative in the live feed. The 15 faith
 * kinds must (a) register in all three feed registries (KIND_ICON,
 * KIND_FALLBACK_COLOR as a token var(), and exactly ONE category — a missing
 * entry silently breaks the inclusion filter), (b) land in their OWN Faith lane,
 * and (c) actually render their lines in the default view. The conflict kinds
 * (excommunicated, faith_hostility_declared) read in the crime-red war register;
 * the rest read in the candle-brass faith register. Mirrors EventFeed.culture.test.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventFeed, KIND_ICON, KIND_FALLBACK_COLOR, CATEGORIES } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';
import type { EventKind } from '../../types';

const FAITH_KINDS: EventKind[] = [
  'faith_founded',
  'faith_consecrated',
  'temple_consecrated',
  'proselytized',
  'proselytize_resisted',
  'worshipped',
  'faith_joined',
  'faith_left',
  'faith_schism',
  'excommunicated',
  'faith_hostility_declared',
  'congregation_formed',
  'congregation_joined',
  'congregation_left',
  'congregation_dissolved',
];

const CONFLICT_KINDS: EventKind[] = ['excommunicated', 'faith_hostility_declared'];
const DEVOTION_KINDS = FAITH_KINDS.filter((k) => !CONFLICT_KINDS.includes(k));

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the feed persists its filter focus
});

describe('Wave-O faith kinds — all three feed registries', () => {
  it.each(FAITH_KINDS)('%s has an icon', (kind) => {
    expect(KIND_ICON[kind]).toBeTruthy();
  });

  it.each(FAITH_KINDS)('%s has a fallback color, declared as a token var()', (kind) => {
    const color = KIND_FALLBACK_COLOR[kind];
    expect(color).toBeTruthy();
    expect(color).toMatch(/^var\(--[a-z-]+\)$/);
  });

  it.each(FAITH_KINDS)('%s maps to exactly ONE category', (kind) => {
    const holders = CATEGORIES.filter((c) => c.kinds.includes(kind));
    expect(holders).toHaveLength(1);
  });

  it('every faith kind lands in the dedicated Faith lane', () => {
    const faith = CATEGORIES.find((c) => c.key === 'faith');
    expect(faith).toBeDefined();
    for (const kind of FAITH_KINDS) expect(faith!.kinds).toContain(kind);
  });

  it('the devotion narrative reads in the candle-brass faith-tint register', () => {
    for (const kind of DEVOTION_KINDS) {
      expect(KIND_FALLBACK_COLOR[kind]).toBe('var(--faith-tint)');
    }
  });

  it('the conflict surface reads in the crime-red war register', () => {
    for (const kind of CONFLICT_KINDS) {
      expect(KIND_FALLBACK_COLOR[kind]).toBe('var(--marker-crime)');
    }
  });

  it('the ✞ founding glyph, the 🕯 conversion, and the ⛔ excommunication read', () => {
    expect(KIND_ICON['faith_founded']).toBe('✞');
    expect(KIND_ICON['proselytized']).toBe('🕯');
    expect(KIND_ICON['excommunicated']).toBe('⛔');
    expect(KIND_ICON['faith_hostility_declared']).toBe('⚔');
  });
});

describe('EventFeed — the religion narrative renders live', () => {
  it('shows the found → convert → congregate → schism → excommunicate arc', () => {
    render(
      <EventFeed
        events={[
          ev({ kind: 'faith_founded', tick: 2, actor_id: 'a1',
               text: '🕯 Ada founds The Ashen Vigil, faith of Vaal.' }),
          ev({ kind: 'proselytized', tick: 5, actor_id: 'a1', target_id: 'a2',
               text: '🕯 Ada brings Bram into The Ashen Vigil.' }),
          ev({ kind: 'congregation_formed', tick: 7, actor_id: 'a1', actor_type: 'system',
               text: "⛪ Ada's Flock gathers as a congregation." }),
          ev({ kind: 'faith_hostility_declared', tick: 9, actor_id: 'a1',
               text: '⚔ Ada declares The Ashen Vigil hostile to The Gilded Dawn.' }),
          ev({ kind: 'excommunicated', tick: 11, actor_id: 'a1', target_id: 'a2',
               text: '⛔ Ada casts Bram out of The Ashen Vigil.' }),
        ]}
      />,
    );
    expect(screen.getByText(/founds The Ashen Vigil/)).toBeInTheDocument();
    expect(screen.getByText(/brings Bram into/)).toBeInTheDocument();
    expect(screen.getByText(/gathers as a congregation/)).toBeInTheDocument();
    expect(screen.getByText(/hostile to The Gilded Dawn/)).toBeInTheDocument();
    expect(screen.getByText(/casts Bram out/)).toBeInTheDocument();
  });
});
