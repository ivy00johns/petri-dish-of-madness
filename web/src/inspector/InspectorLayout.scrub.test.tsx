/**
 * Wave M (EM-195) — Inspector scrub residuals, at the layout level.
 *
 * The non-projector panels (SocialGraph / GovernanceHistory / DecisionTrace)
 * re-sort + re-fold the scoped slice every scrub tick when `panelEvents` gets a
 * fresh identity each tick. This pins the FIX end-to-end:
 *
 *  • panelEvents identity is STABLE across two identity-equal scrub ticks — a
 *    scrub away and back to the SAME tick hands the panels the SAME `events`
 *    array reference (so the selectors' ascendingCache stops missing).
 *  • The fold output the panels render is unchanged across that round trip
 *    (golden-equal to the scoped fold at that tick).
 *
 * We observe the `events` prop the panels actually receive by mocking
 * SocialGraph to record each `props.events` reference, then drive the scrubber.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ev, resetSeq } from '../test-utils/fixtures';
import type { WorldEvent } from '../types';
import type { PanelProps } from './types';

// Capture every `events` ref SocialGraph is handed, per render.
const receivedEvents: WorldEvent[][] = [];

vi.mock('./SocialGraph', () => ({
  default: (props: PanelProps) => {
    receivedEvents.push(props.events);
    return <div data-testid="social-graph-stub">nodes:{props.events.length}</div>;
  },
}));

import { InspectorLayout } from './InspectorLayout';

beforeEach(() => {
  resetSeq();
  receivedEvents.length = 0;
  // RunBrowser fetches /api/runs on mount; a rejected fetch is fine here.
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** A small multi-tick run, newest-first (the history convention). */
function history(): WorldEvent[] {
  const asc: WorldEvent[] = [];
  for (let tick = 0; tick <= 10; tick++) {
    asc.push(ev({ kind: 'agent_speech', tick, actor_id: 'a1', text: `t${tick}` }));
    asc.push(
      ev({ kind: 'relationship', tick, actor_id: 'a1', target_id: 'a2', payload: { type: 'ally' } }),
    );
  }
  return asc.reverse();
}

function renderAnnex(h: WorldEvent[]) {
  return render(
    <InspectorLayout world={null} history={h} mockMode={true} />,
  );
}

function scrubTo(tick: number) {
  fireEvent.change(screen.getByLabelText('Scrub to tick'), { target: { value: String(tick) } });
}

describe('InspectorLayout — panelEvents identity stable across equal scrubs (EM-195)', () => {
  it('a scrub away and back to the SAME tick hands the panels the SAME events ref', () => {
    renderAnnex(history());
    // Scrub to tick 5 (projecting), then to 6, then BACK to 5 — the two visits
    // to tick 5 are identity-equal scrubs.
    scrubTo(5);
    const after5a = receivedEvents[receivedEvents.length - 1];
    scrubTo(6);
    scrubTo(5);
    const after5b = receivedEvents[receivedEvents.length - 1];

    // Stable identity: same scoped slice reference across the two equal scrubs.
    expect(after5b).toBe(after5a);
  });

  it('the scoped fold the panel renders is unchanged across the round trip', () => {
    renderAnnex(history());
    scrubTo(5);
    const at5a = receivedEvents[receivedEvents.length - 1];
    scrubTo(6);
    scrubTo(5);
    const at5b = receivedEvents[receivedEvents.length - 1];

    // Content stays golden-equal (and only events with tick ≤ 5 are scoped in).
    expect(at5b).toEqual(at5a);
    expect(at5b.every((e) => e.tick <= 5)).toBe(true);
    // The full scoped slice at tick 5: ticks 0..5 × 2 events = 12.
    expect(at5b.length).toBe(12);
  });

  it('a DIFFERENT scrub tick hands a different (correctly scoped) ref', () => {
    renderAnnex(history());
    scrubTo(3);
    const at3 = receivedEvents[receivedEvents.length - 1];
    scrubTo(7);
    const at7 = receivedEvents[receivedEvents.length - 1];
    expect(at7).not.toBe(at3);
    expect(at3.length).toBe(8); // ticks 0..3 × 2
    expect(at7.length).toBe(16); // ticks 0..7 × 2
  });
});
