/**
 * dramaWire scorer (EM-316) — pure-logic tests over a synthetic newest-first
 * history + a world_state projection. Covers: per-kind salience + the
 * modifiers (phantom-only vows, rift-only bonds, renewed-law suppression), the
 * rate-cap (count + sim-tick spacing), the decayed Drama Index, the sparkline
 * shape, and camera fly-to resolution. All viewer-layer — no sim feedback.
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import {
  beatFocus,
  dramaBeats,
  dramaIndex,
  dramaSparkline,
  isDramaWireEnabled,
  scoreEvent,
} from './dramaWire';
import { agent, building, ev, resetSeq, world } from '../test-utils/fixtures';
import type { WorldEvent } from '../types';

beforeEach(() => resetSeq());

/** Newest-first, the useSimulation.history order the scorer documents. */
function newestFirst(events: WorldEvent[]): WorldEvent[] {
  return [...events].sort((a, b) => b.seq - a.seq);
}

describe('scoreEvent — per-kind salience + modifiers', () => {
  it('scores a death and a declared war above a crime', () => {
    expect(scoreEvent(ev({ kind: 'agent_died' }))).toBeGreaterThan(
      scoreEvent(ev({ kind: 'conflict' })),
    );
    expect(scoreEvent(ev({ kind: 'war_declared' }))).toBeGreaterThan(
      scoreEvent(ev({ kind: 'conflict' })),
    );
  });

  it('returns 0 for routine, non-dramatic kinds', () => {
    expect(scoreEvent(ev({ kind: 'agent_speech' }))).toBe(0);
    expect(scoreEvent(ev({ kind: 'agent_moved' }))).toBe(0);
    expect(scoreEvent(ev({ kind: 'reflection' }))).toBe(0);
  });

  it('only a PHANTOM commitment lapse is a betrayed vow', () => {
    expect(
      scoreEvent(ev({ kind: 'commitment_lapsed', payload: { reason: 'phantom' } })),
    ).toBeGreaterThan(0);
    expect(
      scoreEvent(ev({ kind: 'commitment_lapsed', payload: { reason: 'expired' } })),
    ).toBe(0);
  });

  it('only a slide into feud/enemy is a rift', () => {
    expect(
      scoreEvent(ev({ kind: 'relationship_changed', payload: { to_type: 'feud' } })),
    ).toBeGreaterThan(0);
    expect(
      scoreEvent(ev({ kind: 'relationship_changed', payload: { to_type: 'friend' } })),
    ).toBe(0);
  });

  it('a renewed law is not a fresh verdict', () => {
    expect(scoreEvent(ev({ kind: 'rule_passed' }))).toBeGreaterThan(0);
    expect(scoreEvent(ev({ kind: 'rule_passed', payload: { renewed: true } }))).toBe(0);
  });
});

describe('dramaBeats — rate cap', () => {
  it('surfaces breaking beats newest-first with the templated headline', () => {
    const history = newestFirst([
      ev({ kind: 'conflict', tick: 1, text: 'Ada robs Bram', actor_id: 'a1' }),
      ev({ kind: 'agent_died', tick: 10, text: 'Bram has fallen', actor_id: 'a2' }),
    ]);
    const beats = dramaBeats(history);
    expect(beats).toHaveLength(2);
    expect(beats[0].kind).toBe('agent_died'); // newest first
    expect(beats[0].label).toBe('DEATH');
    expect(beats[0].headline).toBe('Bram has fallen');
  });

  it('collapses a same-/near-tick burst to a single card (min-tick spacing)', () => {
    // Three war clashes one tick apart — should not all surface.
    const history = newestFirst([
      ev({ kind: 'war_clash', tick: 20, text: 'clash A' }),
      ev({ kind: 'war_clash', tick: 21, text: 'clash B' }),
      ev({ kind: 'war_clash', tick: 22, text: 'clash C' }),
    ]);
    const beats = dramaBeats(history, { minTickGap: 3 });
    expect(beats).toHaveLength(1);
    expect(beats[0].headline).toBe('clash C'); // the newest wins the slot
  });

  it('honors maxCards even when spacing allows more', () => {
    const history = newestFirst([
      ev({ kind: 'agent_died', tick: 0, text: 'd0' }),
      ev({ kind: 'agent_died', tick: 10, text: 'd1' }),
      ev({ kind: 'agent_died', tick: 20, text: 'd2' }),
      ev({ kind: 'agent_died', tick: 30, text: 'd3' }),
    ]);
    const beats = dramaBeats(history, { maxCards: 2, minTickGap: 3 });
    expect(beats).toHaveLength(2);
  });

  it('drops sub-threshold events entirely', () => {
    const history = newestFirst([
      ev({ kind: 'agent_speech', tick: 5, text: 'hello' }),
      ev({ kind: 'faction_formed', tick: 6, text: 'the Ash form' }),
    ]);
    const beats = dramaBeats(history, { threshold: 40 }); // faction=30 < 40
    expect(beats).toHaveLength(0);
  });
});

describe('dramaIndex — decayed salience', () => {
  it('is 0 for an empty or drama-free history', () => {
    expect(dramaIndex([])).toBe(0);
    expect(dramaIndex(newestFirst([ev({ kind: 'agent_speech', tick: 3 })]))).toBe(0);
  });

  it('a fresh beat weighs more than the same beat long ago', () => {
    const fresh = dramaIndex(
      newestFirst([
        ev({ kind: 'agent_died', tick: 100 }),
        ev({ kind: 'agent_speech', tick: 100 }),
      ]),
    );
    const stale = dramaIndex(
      newestFirst([
        ev({ kind: 'agent_died', tick: 1 }),
        ev({ kind: 'agent_speech', tick: 100 }),
      ]),
    );
    expect(fresh).toBeGreaterThan(stale);
  });

  it('clamps to 100', () => {
    const many = Array.from({ length: 40 }, (_, i) =>
      ev({ kind: 'world_extinct', tick: 100 - 0 * i }),
    );
    expect(dramaIndex(newestFirst(many))).toBe(100);
  });
});

describe('dramaSparkline', () => {
  it('is a flat zero series with no history', () => {
    const s = dramaSparkline([], 8);
    expect(s).toHaveLength(8);
    expect(s.every((v) => v === 0)).toBe(true);
  });

  it('places the newest beat in the rightmost bucket', () => {
    const s = dramaSparkline(
      newestFirst([
        ev({ kind: 'agent_speech', tick: 0 }),
        ev({ kind: 'agent_died', tick: 100 }),
      ]),
      10,
    );
    expect(s[s.length - 1]).toBeGreaterThan(0);
    expect(s[0]).toBe(0);
  });
});

describe('beatFocus — camera fly-to resolution (zero sim feedback)', () => {
  const w = world({
    agents: [
      agent({ id: 'a1', name: 'Ada', location: 'market' }),
      agent({ id: 'a2', name: 'Bram', location: 'plaza' }),
    ],
    buildings: [building({ id: 'b1', location: 'forge' })],
  });

  it('prefers a named building (siege) over the actor location', () => {
    const [beat] = dramaBeats(
      newestFirst([
        ev({ kind: 'war_siege', tick: 5, actor_id: 'a1', payload: { building_id: 'b1' } }),
      ]),
    );
    expect(beatFocus(beat, w)).toEqual({ type: 'place', id: 'b1' });
  });

  it("falls back to the actor's current location place", () => {
    const [beat] = dramaBeats(
      newestFirst([ev({ kind: 'agent_died', tick: 5, actor_id: 'a1' })]),
    );
    expect(beatFocus(beat, w)).toEqual({ type: 'place', id: 'market' });
  });

  it('returns null when nothing resolves (card renders, fly-to disabled)', () => {
    const [beat] = dramaBeats(
      newestFirst([ev({ kind: 'world_extinct', tick: 5 })]),
    );
    expect(beatFocus(beat, w)).toBeNull();
    expect(beatFocus(beat, null)).toBeNull();
  });
});

describe('isDramaWireEnabled — flag defaults OFF', () => {
  afterEach(() => vi.unstubAllEnvs());

  it('defaults OFF when unset', () => {
    expect(isDramaWireEnabled()).toBe(false);
  });

  it('is ON for 1/true/on (case-insensitive)', () => {
    for (const v of ['1', 'true', 'on', 'ON', 'True']) {
      vi.stubEnv('VITE_DRAMA_WIRE', v);
      expect(isDramaWireEnabled()).toBe(true);
    }
  });

  it('stays OFF for other values', () => {
    vi.stubEnv('VITE_DRAMA_WIRE', '0');
    expect(isDramaWireEnabled()).toBe(false);
  });
});
