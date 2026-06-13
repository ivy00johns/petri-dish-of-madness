/**
 * Wave F (EM-194) — 50k-cap honesty in the InspectorLayout status strip.
 *
 * When the in-memory history is truncated at the cap, the strip must say
 * EXACTLY how much of the run is held ("showing the newest N of TOTAL")
 * instead of the vague legacy badge; while the backfill pages in, the strip
 * shows real progress driven by /api/events/stats.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { InspectorLayout } from './InspectorLayout';
import { ev, resetSeq } from '../test-utils/fixtures';
import type { WorldEvent } from '../types';

beforeEach(() => {
  resetSeq();
  // RunBrowser fetches /api/runs on mount; a rejected fetch resolves to the
  // labeled "no backend" state (inspectorApi catches) — fine for this test.
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function history(n: number): WorldEvent[] {
  const out: WorldEvent[] = [];
  for (let i = 0; i < n; i++) out.push(ev({ kind: 'agent_speech', tick: i, text: `e${i}` }));
  return out.reverse();
}

describe('InspectorLayout — cap honesty + backfill progress (wave F)', () => {
  it('truncated history says "showing the newest N of TOTAL"', () => {
    render(
      <InspectorLayout
        world={null}
        history={history(3)}
        historyLoading={false}
        historyTruncated={true}
        historyTotal={99_140}
        mockMode={false}
      />,
    );
    const expected = new RegExp(
      `showing the newest ${(3).toLocaleString()} of ${(99_140).toLocaleString()}`,
      'i',
    );
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it('backfill in flight shows honest progress from stats.total', () => {
    render(
      <InspectorLayout
        world={null}
        history={history(2)}
        historyLoading={true}
        historyTruncated={false}
        historyTotal={99_140}
        mockMode={false}
      />,
    );
    const expected = new RegExp(
      `backfilling ${(2).toLocaleString()} / ${(99_140).toLocaleString()} events`,
      'i',
    );
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it('without stats (pre-F1 backend) the legacy labels still render', () => {
    render(
      <InspectorLayout
        world={null}
        history={history(2)}
        historyLoading={true}
        historyTruncated={true}
        historyTotal={null}
        mockMode={false}
      />,
    );
    expect(screen.getByText(/HISTORY LOADING…/i)).toBeInTheDocument();
    expect(screen.getByText(/HISTORY TRUNCATED — OLDEST EVENTS VIA REPLAY/i)).toBeInTheDocument();
  });
});
