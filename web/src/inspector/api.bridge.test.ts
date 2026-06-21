/**
 * eventRowToWorldEvent bridge (EM-187 fix #28 follow-through) — the EventRow →
 * WorldEvent lift used by the /api/events backfill + /api/replay paths MUST
 * carry `profile_color` through. Regression: the bridge copied `profile` but
 * DROPPED `profile_color`, so the live-feed model chip rendered only on live WS
 * events (stored raw) and vanished for ALL backfilled/replayed history on a page
 * refresh. The backend already serves the derived hex color; this is the seam
 * that previously lost it.
 */
import { describe, expect, it } from 'vitest';
import { eventRowToWorldEvent } from './api';
import type { EventRow } from './api';

function row(overrides: Partial<EventRow> = {}): EventRow {
  return {
    seq: 1,
    run_id: 1,
    tick: 10,
    sim_time: null,
    kind: 'agent_speech' as EventRow['kind'],
    actor_id: 'a1',
    actor_type: 'agent',
    target_id: null,
    profile: 'kimi',
    turn_id: 't1',
    text: 'hi',
    payload: {},
    ts: '2026-06-20T00:00:00Z',
    ...overrides,
  };
}

describe('eventRowToWorldEvent — model-chip color survives the backfill bridge', () => {
  it('carries profile_color through (the chip requires a hex color)', () => {
    const evt = eventRowToWorldEvent(row({ profile: 'kimi', profile_color: '#d4a017' }));
    expect(evt.profile).toBe('kimi');
    expect(evt.profile_color).toBe('#d4a017');
  });

  it('preserves the profile while defaulting a missing color to null', () => {
    const evt = eventRowToWorldEvent(row({ profile: 'kimi', profile_color: undefined }));
    expect(evt.profile).toBe('kimi');
    expect(evt.profile_color).toBeNull();
  });
});
