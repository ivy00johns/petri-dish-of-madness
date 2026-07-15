/**
 * Wave O (EM-251–255) — the culture narrative in the live feed. The 13 culture
 * kinds must (a) register in all three feed registries (KIND_ICON,
 * KIND_FALLBACK_COLOR as a token var(), and exactly ONE category — a missing
 * entry silently breaks the inclusion filter), (b) land in their OWN Culture
 * lane, and (c) actually render their lines in the default view. Mirrors
 * EventFeed.war.test.tsx + EventFeed.registries.test.tsx.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventFeed, KIND_ICON, KIND_FALLBACK_COLOR, CATEGORIES } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';
import type { EventKind } from '../../types';

const CULTURE_KINDS: EventKind[] = [
  'meme_created',
  'meme_adopted',
  'rumor_spread',
  'meme_mutated',
  'letter_sent',
  'letter_read',
  'meme_canonized',
  'meme_dominant',
  'meme_died',
  'culture_camp_formed',
  'culture_camp_joined',
  'culture_camp_left',
  'culture_camp_dissolved',
];

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the feed persists its filter focus
});

describe('Wave-O culture kinds — all three feed registries', () => {
  it.each(CULTURE_KINDS)('%s has an icon', (kind) => {
    expect(KIND_ICON[kind]).toBeTruthy();
  });

  it.each(CULTURE_KINDS)('%s has a fallback color, declared as a token var()', (kind) => {
    const color = KIND_FALLBACK_COLOR[kind];
    expect(color).toBeTruthy();
    expect(color).toMatch(/^var\(--[a-z-]+\)$/);
  });

  it.each(CULTURE_KINDS)('%s maps to exactly ONE category', (kind) => {
    const holders = CATEGORIES.filter((c) => c.kinds.includes(kind));
    expect(holders).toHaveLength(1);
  });

  it('every culture kind lands in the dedicated Culture lane', () => {
    const culture = CATEGORIES.find((c) => c.key === 'culture');
    expect(culture).toBeDefined();
    for (const kind of CULTURE_KINDS) expect(culture!.kinds).toContain(kind);
  });

  it('the whole culture narrative reads in the mint faction-tint register', () => {
    for (const kind of CULTURE_KINDS) {
      expect(KIND_FALLBACK_COLOR[kind]).toBe('var(--faction-tint)');
    }
  });

  it('the 🧬 mutation glyph marks a drift; the ⭐ marks canonization', () => {
    expect(KIND_ICON['meme_mutated']).toBe('🧬');
    expect(KIND_ICON['meme_canonized']).toBe('⭐');
  });
});

describe('EventFeed — the culture narrative renders live', () => {
  it('shows the create → spread → drift → canonize arc in the default view', () => {
    render(
      <EventFeed
        events={[
          ev({ kind: 'meme_created', tick: 4, actor_id: 'a1',
               text: '💡 Ada coins the notion that "a fox in a crown" rules the town.' }),
          ev({ kind: 'rumor_spread', tick: 6, actor_id: 'a2',
               text: '🗣 Bram carries the fox-crown rumor to the market.' }),
          ev({ kind: 'meme_mutated', tick: 9, actor_id: 'a3',
               text: '🧬 The fox-crown idea drifts into "a fox in a paper crown".' }),
          ev({ kind: 'meme_canonized', tick: 14, actor_id: 'a1', actor_type: 'system',
               text: '⭐ The town canonizes the fox in a crown as its motif.' }),
        ]}
      />,
    );
    expect(screen.getByText(/coins the notion/)).toBeInTheDocument();
    expect(screen.getByText(/carries the fox-crown rumor/)).toBeInTheDocument();
    expect(screen.getByText(/drifts into/)).toBeInTheDocument();
    expect(screen.getByText(/canonizes the fox/)).toBeInTheDocument();
  });
});
