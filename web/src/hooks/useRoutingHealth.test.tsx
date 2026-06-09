/**
 * computeRoutingHealthSmoothed + useRoutingHealth (EM-043 / EM-072) — the
 * hysteresis state machine over the routed-sample stream, pinned to the exact
 * scenarios the implementer smoke-tested: 5-to-show, 2-diverse-to-clear,
 * animal exclusion, single-profile immunity, and the transient `recovered`.
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { computeRoutingHealthSmoothed, useRoutingHealth } from './useRoutingHealth';
import { agent, ev, resetSeq, world } from '../test-utils/fixtures';
import type { WorldEvent } from '../types';

const W = world({
  agents: [agent({ id: 'a1', profile: 'profile-a' }), agent({ id: 'a2', profile: 'profile-b' })],
});

/** One routed sample: an llm_call answered by `model` for `actor`. */
function sample(actor: string, model: string, extra: Partial<WorldEvent> = {}): WorldEvent {
  return ev({ kind: 'llm_call', tick: 1, actor_id: actor, payload: { routed_via: model }, ...extra });
}

/** N collapsed samples (all one model) alternating across both profiles. */
function collapsed(n: number, model = 'm-one'): WorldEvent[] {
  return Array.from({ length: n }, (_, i) => sample(i % 2 === 0 ? 'a1' : 'a2', model));
}

beforeEach(resetSeq);

describe('computeRoutingHealthSmoothed — SHOW threshold', () => {
  it('4 collapsed samples do NOT trip the banner', () => {
    expect(computeRoutingHealthSmoothed(W, collapsed(4)).degraded).toBe(false);
  });

  it('the 5th consecutive collapsed sample trips it', () => {
    const health = computeRoutingHealthSmoothed(W, collapsed(5));
    expect(health.degraded).toBe(true);
    expect(health.model).toBe('m-one');
    expect(health.profileCount).toBe(2);
  });

  it('5 collapsed samples from ONE profile never trip (one profile cannot condemn the run)', () => {
    const events = Array.from({ length: 8 }, () => sample('a1', 'm-one'));
    expect(computeRoutingHealthSmoothed(W, events).degraded).toBe(false);
  });

  it('animal llm_calls are excluded from the sample stream', () => {
    // 3 agent samples + 2 animal-attributed samples: only 3 count → no trip.
    const events = [
      ...collapsed(3),
      sample('a1', 'm-one', { actor_type: 'animal' }),
      sample('a2', 'm-one', { actor_type: 'animal' }),
    ];
    expect(computeRoutingHealthSmoothed(W, events).degraded).toBe(false);
    // …and a pure animal stream of any length stays quiet.
    const animalsOnly = Array.from({ length: 10 }, (_, i) =>
      sample(i % 2 === 0 ? 'a1' : 'a2', 'm-one', { actor_type: 'animal' }),
    );
    expect(computeRoutingHealthSmoothed(W, animalsOnly).degraded).toBe(false);
  });

  it('stays quiet with no routed samples (absence of evidence is not degradation)', () => {
    expect(computeRoutingHealthSmoothed(W, [])).toMatchObject({ degraded: false, model: null });
  });
});

describe('computeRoutingHealthSmoothed — CLEAR threshold', () => {
  it('ONE diverse sample does not clear a shown banner', () => {
    const events = [...collapsed(5), sample('a1', 'm-two')];
    expect(computeRoutingHealthSmoothed(W, events).degraded).toBe(true);
  });

  it('the SECOND diverse sample within the window clears it', () => {
    const events = [...collapsed(5), sample('a1', 'm-two'), sample('a2', 'm-two')];
    expect(computeRoutingHealthSmoothed(W, events).degraded).toBe(false);
  });

  it('after a clear, re-showing needs a fresh FULL run of collapsed samples', () => {
    const cleared = [...collapsed(5), sample('a1', 'm-two'), sample('a2', 'm-two')];
    // 4 more collapsed samples: not enough for a fresh run of 5.
    expect(computeRoutingHealthSmoothed(W, [...cleared, ...collapsed(4)]).degraded).toBe(false);
    // The 5th re-shows.
    expect(computeRoutingHealthSmoothed(W, [...cleared, ...collapsed(5)]).degraded).toBe(true);
  });
});

describe('useRoutingHealth — transient `recovered` flag', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('flags recovered on degraded → healthy, then drops it after the timeout', () => {
    const degraded = collapsed(5);
    const cleared = [...degraded, sample('a1', 'm-two'), sample('a2', 'm-two')];

    const { result, rerender } = renderHook(
      ({ events }: { events: WorldEvent[] }) => useRoutingHealth(W, events),
      { initialProps: { events: degraded } },
    );
    expect(result.current.degraded).toBe(true);
    expect(result.current.recovered).toBeFalsy();

    rerender({ events: cleared });
    expect(result.current.degraded).toBe(false);
    expect(result.current.recovered).toBe(true);

    act(() => {
      vi.advanceTimersByTime(6001);
    });
    expect(result.current.recovered).toBeFalsy();
  });

  it('never flags recovered when the run was healthy all along', () => {
    const { result } = renderHook(() => useRoutingHealth(W, collapsed(3)));
    expect(result.current.degraded).toBe(false);
    expect(result.current.recovered).toBeFalsy();
  });
});
