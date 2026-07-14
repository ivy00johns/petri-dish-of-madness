/**
 * QE (cosmetic, non-blocking) — the travel feed cards' COLOR resolution.
 *
 * The card border/badge color is `event.profile_color ?? KIND_FALLBACK_COLOR[kind]
 * ?? 'var(--marker-trace)'` (EventFeed.tsx). So a card is drawn in the ACTOR's model
 * color only when the backend event carries `profile_color`.
 *
 *   • `travel_departed` / `settlement_founded` are ACTION results — the runtime's
 *     base-metadata spread stamps the actor's `profile_color`, so they render in
 *     the actor color.
 *   • `travel_arrived` is parked in `pending_spawn_events` and flushed via
 *     `_emit_event`, which reads `evt.get("profile_color")` (None here — the world
 *     resolver never sets it) and does NOT resolve it from `actor_id`. With no
 *     `KIND_FALLBACK_COLOR` entry either, the card falls back to the neutral
 *     `var(--marker-trace)`.
 *
 * This is COSMETIC: the card still renders (never throws, never an error lane) —
 * it just wears the generic trace tint instead of the traveler's color. This test
 * PINS that state so a future "arrivals should wear the actor color" fix is a
 * conscious change, not an accident.
 */
import { describe, expect, it } from 'vitest';
import { KIND_ICON, KIND_FALLBACK_COLOR } from './EventFeed';
import type { EventKind } from '../../types';

const TRAVEL_KINDS: EventKind[] = ['settlement_founded', 'travel_departed', 'travel_arrived'];

describe('QE — travel feed card color resolution (cosmetic)', () => {
  it.each(TRAVEL_KINDS)('%s has a movement icon (renders a card, never blank)', (kind) => {
    expect(KIND_ICON[kind]).toBeTruthy();
  });

  it('none of the travel kinds has a KIND_FALLBACK_COLOR entry', () => {
    // They rely on the emitted profile_color; absent it, the card uses the
    // neutral var(--marker-trace) — documented, non-blocking.
    for (const kind of TRAVEL_KINDS) {
      expect(KIND_FALLBACK_COLOR[kind]).toBeUndefined();
    }
  });

  it('the card color formula never yields undefined for travel_arrived (no throw)', () => {
    // Mirror EventFeed's resolution with NO profile_color (the backend arrival path):
    const profileColor: string | undefined = undefined;
    const kind: EventKind = 'travel_arrived';
    const color = profileColor ?? KIND_FALLBACK_COLOR[kind] ?? 'var(--marker-trace)';
    expect(color).toBe('var(--marker-trace)'); // neutral fallback, not the actor color
  });
});
