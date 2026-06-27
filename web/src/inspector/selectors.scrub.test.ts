/**
 * Wave M (EM-195) — Inspector scrub residuals.
 *
 * Two pure-selector guards behind the scrub-residual fix:
 *
 *  1. scopedSlice — the secondary cache keyed by (eventArrayRef, projecting,
 *     currentTick). Two identity-equal scrubs (same key) must return the SAME
 *     array reference, so the layout's panelEvents identity is stable and the
 *     ascendingCache WeakMap stops missing every tick. The slice content must
 *     stay byte-identical to a plain `events.filter(e => e.tick <= T)` so the
 *     non-projector panels' folds are golden-equal to the full scoped fold.
 *
 *  2. mergeNewestFirst — the insert-sorted WS merge. A late event whose seq
 *     lands BEFORE the head must slot into its correct descending-seq position
 *     (never a blind prepend), preserving the newest-first order the scrubber
 *     rail reads and the projectors' seq-ascending monotone precondition needs.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { scopedSlice, mergeNewestFirst, sortedBySeqAsc, governanceTimeline } from './selectors';
import { ev, resetSeq } from '../test-utils/fixtures';
import type { WorldEvent } from '../types';

beforeEach(resetSeq);

describe('scopedSlice — stable identity across identity-equal scrubs (EM-195)', () => {
  function history(): WorldEvent[] {
    // Newest-first, ticks 0..5 (the history convention).
    const asc: WorldEvent[] = [];
    for (let tick = 0; tick <= 5; tick++) {
      asc.push(ev({ kind: 'agent_speech', tick, actor_id: 'a1', text: `t${tick}` }));
    }
    return asc.reverse();
  }

  it('returns the SAME array reference for two identity-equal scrub ticks', () => {
    const events = history();
    const first = scopedSlice(events, true, 3);
    const second = scopedSlice(events, true, 3); // identity-equal scrub
    expect(second).toBe(first); // same reference, not just deep-equal
  });

  it('the cached slice content equals a plain filter (golden-equal scoped slice)', () => {
    const events = history();
    for (const tick of [0, 2, 5]) {
      expect(scopedSlice(events, true, tick)).toEqual(events.filter((e) => e.tick <= tick));
    }
  });

  it('a different tick yields a different slice (the cache is keyed by tick)', () => {
    const events = history();
    const at3 = scopedSlice(events, true, 3);
    const at4 = scopedSlice(events, true, 4);
    expect(at4).not.toBe(at3);
    expect(at3.length).toBe(4); // ticks 0..3
    expect(at4.length).toBe(5); // ticks 0..4
  });

  it('not projecting → returns the events ref UNCHANGED (live-edge passthrough)', () => {
    const events = history();
    expect(scopedSlice(events, false, 3)).toBe(events);
  });

  it('a fresh events array gets its OWN sub-cache (WeakMap keyed by ref)', () => {
    // Two DISTINCT array refs holding the same logical run (slicing the same
    // source twice). The WeakMap keys by ref, so each gets its own cache entry.
    const source = history();
    const a = [...source];
    const b = [...source];
    const sliceA = scopedSlice(a, true, 3);
    const sliceB = scopedSlice(b, true, 3);
    expect(sliceB).not.toBe(sliceA); // different ref ⇒ different cache entry
    expect(sliceB).toEqual(sliceA); // …but identical content
  });

  it('the stable slice HITS the ascendingCache (no re-sort), and the fold is unchanged', () => {
    // The whole point: a stable slice ref lets sortedBySeqAsc / governanceTimeline
    // reuse their cached work instead of re-folding every scrub tick.
    const asc: WorldEvent[] = [];
    asc.push(ev({ kind: 'rule_proposed', tick: 1, actor_id: 'a1', payload: { rule_id: 'r1', effect: 'ubi' }, text: 'p' }));
    asc.push(ev({ kind: 'rule_vote', tick: 2, actor_id: 'a2', payload: { rule_id: 'r1', choice: true } }));
    asc.push(ev({ kind: 'rule_passed', tick: 3, payload: { rule_id: 'r1' } }));
    const events = asc.reverse();

    const slice1 = scopedSlice(events, true, 3);
    const slice2 = scopedSlice(events, true, 3);
    expect(slice2).toBe(slice1);
    // Same ref ⇒ the ascending sort is the SAME cached array both times.
    expect(sortedBySeqAsc(slice2)).toBe(sortedBySeqAsc(slice1));
    // And the governance fold over the stable slice equals the full-fold result.
    expect(governanceTimeline(slice1)).toEqual(governanceTimeline(events.filter((e) => e.tick <= 3)));
  });
});

describe('mergeNewestFirst — insert-sorted out-of-order WS merge (EM-195)', () => {
  function descBySeq(events: WorldEvent[]): boolean {
    for (let i = 1; i < events.length; i++) {
      if (events[i].seq > events[i - 1].seq) return false;
    }
    return true;
  }

  it('an empty incoming list returns the SAME history reference (no-op)', () => {
    const history = [ev({ kind: 'agent_speech', tick: 1 })];
    expect(mergeNewestFirst(history, [])).toBe(history);
  });

  it('all-duplicate incoming returns the SAME history reference (no-op)', () => {
    const e = ev({ kind: 'agent_speech', tick: 1, actor_id: 'a1' });
    const history = [e];
    // Same seq already present ⇒ nothing fresh to merge.
    expect(mergeNewestFirst(history, [{ ...e }])).toBe(history);
  });

  it('a NEWER event prepends (newest-first preserved)', () => {
    const older = ev({ kind: 'agent_speech', tick: 1, actor_id: 'a1' }); // seq 1
    const newer = ev({ kind: 'agent_speech', tick: 2, actor_id: 'a1' }); // seq 2
    const history = [older]; // head seq = 1
    const merged = mergeNewestFirst(history, [newer]);
    expect(merged.map((e) => e.seq)).toEqual([2, 1]);
    expect(descBySeq(merged)).toBe(true);
  });

  it('an OUT-OF-ORDER late event slots into its correct descending-seq position', () => {
    // History holds seq 1,3,5 (newest-first ⇒ [5,3,1]); a late event with seq 4
    // arrives — it must land BETWEEN 5 and 3, never get prepended.
    const e1 = ev({ kind: 'agent_speech', tick: 1 }); // 1
    const e3 = ev({ kind: 'agent_speech', tick: 3 }); // 2 ... force seqs explicitly
    e3.seq = 3;
    const e5 = ev({ kind: 'agent_speech', tick: 5 });
    e5.seq = 5;
    const late = ev({ kind: 'agent_speech', tick: 4 });
    late.seq = 4;
    e1.seq = 1;

    const history = [e5, e3, e1]; // newest-first
    const merged = mergeNewestFirst(history, [late]);
    expect(merged.map((e) => e.seq)).toEqual([5, 4, 3, 1]);
    expect(descBySeq(merged)).toBe(true);
  });

  it('the merged pool sorts seq-ASCENDING into a monotone run (projector precondition)', () => {
    const e1 = ev({ kind: 'turn_start', tick: 1 });
    e1.seq = 1;
    const e5 = ev({ kind: 'turn_start', tick: 5 });
    e5.seq = 5;
    const late = ev({ kind: 'turn_start', tick: 3 });
    late.seq = 3;
    const history = [e5, e1]; // newest-first
    const merged = mergeNewestFirst(history, [late]);
    const asc = sortedBySeqAsc(merged);
    // seq-ascending ⇒ ticks non-decreasing (what the incremental projectors need).
    for (let i = 1; i < asc.length; i++) {
      expect(asc[i].tick).toBeGreaterThanOrEqual(asc[i - 1].tick);
    }
  });

  it('dedupes incoming against history AND within the incoming batch', () => {
    const e1 = ev({ kind: 'agent_speech', tick: 1 });
    e1.seq = 1;
    const e2 = ev({ kind: 'agent_speech', tick: 2 });
    e2.seq = 2;
    const dupOf1 = { ...e1 };
    const fresh = ev({ kind: 'agent_speech', tick: 3 });
    fresh.seq = 3;
    const dupOfFresh = { ...fresh };
    const history = [e2, e1];
    const merged = mergeNewestFirst(history, [dupOf1, fresh, dupOfFresh]);
    // Only seq 3 is fresh; it prepends. No duplicate seq 3.
    expect(merged.map((e) => e.seq)).toEqual([3, 2, 1]);
  });
});
