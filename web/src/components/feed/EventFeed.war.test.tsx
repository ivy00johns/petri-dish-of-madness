/**
 * Wave O (EM-256–259) — the war narrative in the live feed. The 8 war kinds
 * must (a) register in all three feed registries (KIND_ICON, KIND_FALLBACK_COLOR
 * as a token var(), and exactly ONE category — a missing entry silently breaks
 * the inclusion filter), (b) land in the SAME social/conflict lane the crime
 * `conflict` kind lives in, and (c) actually render their ⚔ / 🕊 lines in the
 * default view. Mirrors EventFeed.registries.test.tsx + EventFeed.test.tsx.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventFeed, KIND_ICON, KIND_FALLBACK_COLOR, CATEGORIES } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';
import type { EventKind } from '../../types';

const WAR_KINDS: EventKind[] = [
  'war_declared',
  'grievance_accrued',
  'war_band_joined',
  'war_clash',
  'war_siege',
  'peace_signed',
  'war_exhausted',
  'exiled',
];

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the feed persists its filter focus
});

describe('Wave-O war kinds — all three feed registries', () => {
  it.each(WAR_KINDS)('%s has an icon', (kind) => {
    expect(KIND_ICON[kind]).toBeTruthy();
  });

  it.each(WAR_KINDS)('%s has a fallback color, declared as a token var()', (kind) => {
    const color = KIND_FALLBACK_COLOR[kind];
    expect(color).toBeTruthy();
    expect(color).toMatch(/^var\(--[a-z-]+\)$/);
  });

  it.each(WAR_KINDS)('%s maps to exactly ONE category', (kind) => {
    const holders = CATEGORIES.filter((c) => c.kinds.includes(kind));
    expect(holders).toHaveLength(1);
  });

  it('every war kind lands in the social (red conflict) lane, beside crime `conflict`', () => {
    const social = CATEGORIES.find((c) => c.key === 'social');
    expect(social).toBeDefined();
    expect(social!.kinds).toContain('conflict'); // the crime lane we extend
    for (const kind of WAR_KINDS) expect(social!.kinds).toContain(kind);
  });

  it('the aggressive war kinds read crime-red; peace answers in the faction tint', () => {
    for (const kind of [
      'war_declared',
      'grievance_accrued',
      'war_band_joined',
      'war_clash',
      'war_siege',
      'war_exhausted',
      'exiled',
    ] as EventKind[]) {
      expect(KIND_FALLBACK_COLOR[kind]).toBe('var(--marker-crime)');
    }
    expect(KIND_FALLBACK_COLOR['peace_signed']).toBe('var(--faction-tint)');
  });

  it('the ⚔ crossed-swords glyph prefixes a clash; the 🕊 dove marks peace', () => {
    expect(KIND_ICON['war_clash']).toBe('⚔');
    expect(KIND_ICON['peace_signed']).toBe('🕊');
  });
});

describe('EventFeed — the war narrative renders live', () => {
  it('shows the grievance → declare → clash → peace arc in the default view', () => {
    render(
      <EventFeed
        events={[
          ev({ kind: 'grievance_accrued', tick: 8, actor_id: 'a1', actor_type: 'system',
               text: '⚔ The Ashen Pact nurses a grievance against the Bram Collective (theft; heat 55).' }),
          ev({ kind: 'war_declared', tick: 10, actor_id: 'a1', actor_type: 'system',
               text: '⚔ The Ashen Pact declares WAR on the Bram Collective!' }),
          ev({ kind: 'war_clash', tick: 12, actor_id: 'a1', target_id: 'b1', actor_type: 'system',
               text: '⚔ Ada clashes with Bram — Ada prevails; Bram retreats to forest!' }),
          ev({ kind: 'peace_signed', tick: 20, actor_id: 'b1', actor_type: 'system',
               text: '🕊 The Bram Collective sues for peace with the Ashen Pact — the war is over (12 credits in reparations).' }),
        ]}
      />,
    );
    expect(screen.getByText(/nurses a grievance/)).toBeInTheDocument();
    expect(screen.getByText(/declares WAR/)).toBeInTheDocument();
    expect(screen.getByText(/clashes with Bram/)).toBeInTheDocument();
    expect(screen.getByText(/sues for peace/)).toBeInTheDocument();
  });
});
