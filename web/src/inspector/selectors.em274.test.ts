/**
 * EM-274 — scopedSlice cache is BOUNDED (offline review 2026-07-01).
 *
 * The EM-195 scrub cache memoizes the filtered slice per (events ref,
 * projecting, tick) so identity-equal scrubs return the SAME array (which then
 * hits the ascendingCache — no re-sort/re-fold). Before this fix the inner
 * per-array map had no eviction: it retained one filtered slice (+ its sorted
 * copy) per DISTINCT tick visited, for the whole lifetime of the (long-lived)
 * events array — a leak that grew with scrub distance. These pins keep the
 * memoization win while proving retention is now bounded.
 */
import { describe, expect, it } from 'vitest';
import { scopedSlice } from './selectors';
import { ev } from '../test-utils/fixtures';
import type { WorldEvent } from '../types';

function run(ticks: number): WorldEvent[] {
  const out: WorldEvent[] = [];
  for (let t = 0; t < ticks; t++) out.push(ev({ kind: 'turn_start', tick: t }));
  return out;
}

describe('scopedSlice — memoization win preserved (EM-195/EM-274)', () => {
  it('not projecting → identity passthrough (the live edge reads the whole pool)', () => {
    const events = run(5);
    expect(scopedSlice(events, false, 3)).toBe(events);
  });

  it('the same (events, tick) key returns the SAME array reference', () => {
    const events = run(10);
    const first = scopedSlice(events, true, 4);
    const second = scopedSlice(events, true, 4);
    expect(second).toBe(first); // stable identity ⇒ downstream caches hit
    expect(first.every((e) => e.tick <= 4)).toBe(true);
    expect(first).toHaveLength(5); // ticks 0..4
  });

  it('an immediately-repeated tick stays a cache hit across a small interleave', () => {
    const events = run(50);
    const ref = scopedSlice(events, true, 20);
    scopedSlice(events, true, 21); // one other tick in between
    expect(scopedSlice(events, true, 20)).toBe(ref);
  });
});

describe('scopedSlice — bounded cache, no unbounded per-tick retention (EM-274)', () => {
  it('evicts the least-recently-used slice once many distinct ticks are visited', () => {
    const events = run(200);
    const firstRef = scopedSlice(events, true, 0);
    // Scrub across far more distinct ticks than any small LRU cap.
    for (let t = 1; t <= 60; t++) scopedSlice(events, true, t);
    // Tick 0 is long-since least-recently-used → evicted → recomputed to a NEW
    // reference (the old slice is no longer retained).
    const afterRef = scopedSlice(events, true, 0);
    expect(afterRef).not.toBe(firstRef);
    // Determinism: the recomputed slice is byte-identical in CONTENT.
    expect(afterRef.map((e) => e.seq)).toEqual(firstRef.map((e) => e.seq));
  });
});
