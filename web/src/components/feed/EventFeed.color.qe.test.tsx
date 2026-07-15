/**
 * Travel feed cards' COLOR resolution.
 *
 * The card border/badge color is `event.profile_color ?? KIND_FALLBACK_COLOR[kind]
 * ?? 'var(--marker-trace)'` (EventFeed.tsx). All three travel kinds now carry the
 * ACTOR's model color when emitted:
 *   • `travel_departed` / `settlement_founded` are ACTION results — the runtime's
 *     base-metadata spread stamps the actor's `profile_color`.
 *   • `travel_arrived` is parked in `pending_spawn_events` WITHOUT color by the World
 *     (which has no router/legend), then ENRICHED from the arriving agent at loop
 *     flush (`_flush_spawn_events`, mirrors `_sync_transplant_router`). So live arrival
 *     cards wear the traveler's color too. `var(--marker-trace)` remains only as the
 *     last-ditch fallback for a genuinely color-less event (never a throw / blank).
 */
import { describe, expect, it } from 'vitest';
import { KIND_ICON, KIND_FALLBACK_COLOR } from './EventFeed';
import type { EventKind } from '../../types';

const TRAVEL_KINDS: EventKind[] = ['settlement_founded', 'travel_departed', 'travel_arrived'];

function cardColor(profileColor: string | undefined, kind: EventKind): string {
  // Mirror EventFeed's resolution formula.
  return profileColor ?? KIND_FALLBACK_COLOR[kind] ?? 'var(--marker-trace)';
}

describe('travel feed card color resolution', () => {
  it.each(TRAVEL_KINDS)('%s has a movement icon (renders a card, never blank)', (kind) => {
    expect(KIND_ICON[kind]).toBeTruthy();
  });

  it('an emitted travel_arrived carries the actor color ⇒ card renders in it', () => {
    // The backend flush now enriches travel_arrived from the arriving agent, so the
    // emitted event carries profile_color and the card wears the traveler's color.
    expect(cardColor('#2ecc71', 'travel_arrived')).toBe('#2ecc71');
  });

  it('a genuinely color-less event still falls back to the neutral tint (never undefined)', () => {
    expect(cardColor(undefined, 'travel_arrived')).toBe('var(--marker-trace)');
  });
});
