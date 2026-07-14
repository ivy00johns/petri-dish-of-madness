/**
 * EM-109/110 feed registration — the settlement + travel kinds render as NORMAL
 * movement cards, in the Actions lane, NEVER in the Errors channel.
 *
 * Each of the three kinds must have an icon and map to EXACTLY ONE category (a
 * missing category silently breaks the inclusion filter — the Wave-E discipline).
 * They carry the actor's profile color (like agent_moved), so no fallback color
 * is required.
 */

import { describe, expect, it } from 'vitest';
import { KIND_ICON, CATEGORIES } from './EventFeed';
import type { EventKind } from '../../types';

const TRAVEL_KINDS: EventKind[] = ['settlement_founded', 'travel_departed', 'travel_arrived'];

describe('EM-109/110 — settlement + travel feed cards', () => {
  it.each(TRAVEL_KINDS)('%s has a movement icon', (kind) => {
    expect(KIND_ICON[kind]).toBeTruthy();
  });

  it.each(TRAVEL_KINDS)('%s maps to exactly ONE category', (kind) => {
    const holders = CATEGORIES.filter((c) => c.kinds.includes(kind));
    expect(holders).toHaveLength(1);
  });

  it('all three live in the Actions lane, beside agent_moved', () => {
    const actions = CATEGORIES.find((c) => c.key === 'actions');
    expect(actions).toBeDefined();
    for (const kind of TRAVEL_KINDS) expect(actions!.kinds).toContain(kind);
    expect(actions!.kinds).toContain('agent_moved');
  });

  it('none of them is filed under Errors (they are normal movement, not failures)', () => {
    const errors = CATEGORIES.find((c) => c.key === 'errors');
    expect(errors).toBeDefined();
    for (const kind of TRAVEL_KINDS) expect(errors!.kinds).not.toContain(kind);
  });
});
