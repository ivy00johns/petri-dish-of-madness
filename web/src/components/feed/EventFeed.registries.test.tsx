/**
 * Wave E (contracts/wave-e.md B6 item 1) — event-kind registration. Every one
 * of the 8 new social-city kinds must appear in ALL THREE feed registries:
 * KIND_ICON, KIND_FALLBACK_COLOR, and CATEGORIES (exactly ONE category — a
 * missing entry silently breaks the inclusion filter). New colors must be CSS
 * token var() references, never hex-in-JS (design-token-guard).
 */
import { describe, expect, it } from 'vitest';
import { KIND_ICON, KIND_FALLBACK_COLOR, CATEGORIES } from './EventFeed';
import type { EventKind } from '../../types';

const WAVE_E_KINDS: EventKind[] = [
  'relationship_changed',
  'child_spawned',
  'faction_formed',
  'faction_joined',
  'faction_left',
  'faction_dissolved',
  'god_miracle',
  'miracle_expired',
];

describe('Wave-E kinds — all three feed registries (B6 item 1)', () => {
  it.each(WAVE_E_KINDS)('%s has an icon', (kind) => {
    expect(KIND_ICON[kind]).toBeTruthy();
  });

  it.each(WAVE_E_KINDS)('%s has a fallback color, declared as a token var()', (kind) => {
    const color = KIND_FALLBACK_COLOR[kind];
    expect(color).toBeTruthy();
    expect(color).toMatch(/^var\(--[a-z-]+\)$/);
  });

  it.each(WAVE_E_KINDS)('%s maps to exactly ONE category', (kind) => {
    const holders = CATEGORIES.filter((c) => c.kinds.includes(kind));
    expect(holders).toHaveLength(1);
  });

  it('relationship/faction/birth kinds land in the social category', () => {
    const social = CATEGORIES.find((c) => c.key === 'social');
    expect(social).toBeDefined();
    for (const kind of [
      'relationship_changed',
      'child_spawned',
      'faction_formed',
      'faction_joined',
      'faction_left',
      'faction_dissolved',
    ] as EventKind[]) {
      expect(social!.kinds).toContain(kind);
    }
  });

  it('miracle kinds land in the system (world-lever) category', () => {
    const system = CATEGORIES.find((c) => c.key === 'system');
    expect(system).toBeDefined();
    expect(system!.kinds).toContain('god_miracle');
    expect(system!.kinds).toContain('miracle_expired');
  });

  it('the 👶 birth icon reads on child_spawned (B6 item 6)', () => {
    expect(KIND_ICON['child_spawned']).toBe('👶');
  });
});
