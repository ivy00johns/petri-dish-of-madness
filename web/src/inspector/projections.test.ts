/**
 * Wave F (EM-194) — incremental scrub projectors.
 *
 * GOLDEN EQUALITY: the projector result at ANY tick must be deeply equal to
 * the pre-F full fold (agentEconomyAt over the scoped slice / replayStateAt
 * over everything), pinned over a ~500-event fixture run at 25 seeded-random
 * ticks visited in a random (forward AND backward) order.
 *
 * STRUCTURAL PERF: a forward scrub step folds ONLY the events between the two
 * ticks; a backward jump restores a checkpoint and folds forward from it —
 * never the whole history (stats.lastFoldSteps is the witness).
 *
 * Plus the deep-replay engagement rule (cap honesty: a truncated history must
 * engage the snapshot+delta path even after the backfill finishes).
 */
import { describe, expect, it } from 'vitest';
import type { WorldEvent } from '../types';
import { agent, animal, building, ev, resetSeq } from '../test-utils/fixtures';
import { agentEconomyAt, replayStateAt } from './selectors';
import type { ReplaySnapshot } from './selectors';
import {
  createEconomyProjector,
  createReplayProjector,
  shouldEngageReplayMaterials,
} from './projections';

// ── seeded PRNG (mulberry32) — deterministic "random" ticks ─────────────────
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ── fixture: a ~500-event run over 60 ticks, every fold-relevant kind ────────
const AGENT_IDS = ['a1', 'a2', 'a3', 'a4'];
const PLACE_IDS = ['plaza', 'forest', 'home'];

function buildFixture(): WorldEvent[] {
  resetSeq();
  const rand = mulberry32(0xf2f2);
  const asc: WorldEvent[] = [];
  for (let tick = 0; tick <= 60; tick++) {
    for (const id of AGENT_IDS) {
      if (rand() < 0.8) {
        asc.push(
          ev({
            kind: 'turn_start',
            tick,
            actor_id: id,
            turn_id: `t${tick}-${id}`,
            payload: {
              energy: Math.round(rand() * 100),
              credits: Math.round(rand() * 200),
              day: Math.floor(tick / 6),
            },
          }),
        );
        asc.push(
          ev({
            kind: 'action_resolved',
            tick,
            actor_id: id,
            turn_id: `t${tick}-${id}`,
            payload: {
              outcome: 'ok',
              state_deltas: { energy: Math.round(rand() * 10) - 5, credits: Math.round(rand() * 8) - 4 },
            },
          }),
        );
      }
      if (rand() < 0.3) {
        asc.push(
          ev({
            kind: 'agent_moved',
            tick,
            actor_id: id,
            payload: { place: PLACE_IDS[Math.floor(rand() * PLACE_IDS.length)] },
          }),
        );
      }
    }
    if (tick === 10) {
      asc.push(
        ev({
          kind: 'project_proposed',
          tick,
          actor_id: 'a1',
          payload: { building_id: 'bld_2', name: 'Clock Tower', kind: 'monument', location: 'plaza' },
        }),
      );
    }
    if (tick === 25) {
      asc.push(
        ev({
          kind: 'structure_state_changed',
          tick,
          payload: { building_id: 'bld_2', from: 'planned', to: 'under_construction' },
        }),
      );
    }
    if (tick === 35) {
      asc.push(ev({ kind: 'project_built', tick, payload: { building_id: 'bld_2', progress: 60 } }));
    }
    if (tick === 45) {
      asc.push(
        ev({
          kind: 'building_operational',
          tick,
          payload: { building_id: 'bld_2', kind: 'monument', location: 'plaza' },
        }),
      );
    }
    if (tick === 20) {
      asc.push(
        ev({
          kind: 'animal_spawned',
          tick,
          actor_id: 'dog_1',
          actor_type: 'animal',
          payload: { name: 'Biscuit', species: 'dog', location: 'forest' },
        }),
      );
    }
    if (tick === 50) {
      asc.push(ev({ kind: 'animal_died', tick, actor_id: 'dog_1', actor_type: 'animal' }));
    }
    if (tick === 40) {
      asc.push(ev({ kind: 'agent_died', tick, actor_id: 'a3' }));
    }
    if (rand() < 0.4) {
      asc.push(ev({ kind: 'agent_speech', tick, actor_id: AGENT_IDS[Math.floor(rand() * 4)], text: 'hm' }));
    }
  }
  // The history convention is NEWEST-FIRST.
  return [...asc].reverse();
}

const EVENTS = buildFixture();
const AGENTS = AGENT_IDS.map((id) => agent({ id }));
const PLACES = [
  { id: 'plaza', x: 100, y: 100 },
  { id: 'forest', x: 900, y: 900 },
  { id: 'home', x: 500, y: 200 },
];
// bld_1 predates the event window (exercises the live-roster back-fill);
// bld_2 is created by the events above.
const LIVE_BUILDINGS = [building({ id: 'bld_1' }), building({ id: 'bld_2', status: 'operational' })];
const LIVE_ANIMALS = [animal({ id: 'cat_1' })];
// A STABLE empty-snapshots ref: the projector cursor (like the layout's
// useMemo'd replaySnapshots) keys on the array reference — a fresh literal
// per call would be a reset, which is exactly what the layout never does.
const NO_SNAPSHOTS: ReplaySnapshot[] = [];
const SNAPSHOTS: ReplaySnapshot[] = [
  {
    tick: 30,
    agents: [
      { id: 'a1', location: 'forest', profile: 'model-a', alive: true },
      { id: 'a2', location: 'home', profile: 'model-a', alive: true },
    ],
    places: PLACES,
    buildings: [{ id: 'bld_2', name: 'Clock Tower', status: 'under_construction', progress: 30 }],
    animals: [{ id: 'dog_1', name: 'Biscuit', species: 'dog', location: 'forest', alive: true }],
  },
];

/** 25 seeded-random ticks in [0, 60], visited in a scrub-like random walk. */
function randomTicks(seed: number): number[] {
  const rand = mulberry32(seed);
  return Array.from({ length: 25 }, () => Math.floor(rand() * 61));
}

function countBetween(t1: number, t2: number): number {
  return EVENTS.filter((e) => e.tick > t1 && e.tick <= t2).length;
}

describe('economy projector — golden equality with the full fold', () => {
  it('matches agentEconomyAt(scoped) at 25 random ticks (random walk order)', () => {
    const proj = createEconomyProjector();
    for (const tick of randomTicks(0xbeef)) {
      const expected = agentEconomyAt(EVENTS.filter((e) => e.tick <= tick));
      expect(proj.at(EVENTS, tick)).toEqual(expected);
    }
  });

  it('falls back (still exact) on non-monotone tick/seq data', () => {
    // A synthetic client event: negative seq at a HIGH tick (mock reassign).
    const synthetic: WorldEvent = {
      type: 'event',
      seq: -1,
      tick: 55,
      kind: 'turn_start',
      actor_id: 'a1',
      payload: { energy: 1, credits: 2 },
    };
    const events = [synthetic, ...EVENTS];
    const proj = createEconomyProjector();
    for (const tick of [10, 56, 30]) {
      expect(proj.at(events, tick)).toEqual(agentEconomyAt(events.filter((e) => e.tick <= tick)));
    }
  });
});

describe('economy projector — structural perf (scrub-step incrementality)', () => {
  it('a forward step folds ONLY the events between the two ticks', () => {
    const proj = createEconomyProjector();
    proj.at(EVENTS, 30);
    proj.at(EVENTS, 32);
    expect(proj.stats.lastFoldSteps).toBe(countBetween(30, 32));
    expect(proj.stats.lastFoldSteps).toBeLessThan(EVENTS.length / 4);
  });

  it('a backward jump restores a checkpoint, never refolds the whole history', () => {
    const proj = createEconomyProjector();
    proj.at(EVENTS, 20); // checkpoint @20
    proj.at(EVENTS, 50);
    proj.at(EVENTS, 25); // ← restore @20, fold (20, 25] only
    expect(proj.stats.lastFoldSteps).toBe(countBetween(20, 25));
    // And the result is still the exact projection.
    expect(proj.at(EVENTS, 25)).toEqual(agentEconomyAt(EVENTS.filter((e) => e.tick <= 25)));
  });

  it('revisiting the same tick folds nothing', () => {
    const proj = createEconomyProjector();
    proj.at(EVENTS, 40);
    proj.at(EVENTS, 40);
    expect(proj.stats.lastFoldSteps).toBe(0);
  });
});

describe('replay projector — golden equality with the full fold', () => {
  it('matches replayStateAt at 25 random ticks, NO snapshots', () => {
    const proj = createReplayProjector();
    const none: ReplaySnapshot[] = [];
    for (const tick of randomTicks(0xcafe)) {
      const expected = replayStateAt(EVENTS, none, tick, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS);
      expect(proj.at(EVENTS, none, tick, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS)).toEqual(expected);
    }
  });

  it('matches replayStateAt at 25 random ticks WITH a snapshot base (fold base flips at tick 30)', () => {
    const proj = createReplayProjector();
    for (const tick of randomTicks(0xd00d)) {
      const expected = replayStateAt(EVENTS, SNAPSHOTS, tick, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS);
      expect(proj.at(EVENTS, SNAPSHOTS, tick, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS)).toEqual(
        expected,
      );
    }
  });

  it('falls back (still exact) on non-monotone tick/seq data', () => {
    const synthetic: WorldEvent = {
      type: 'event',
      seq: -5,
      tick: 58,
      kind: 'agent_moved',
      actor_id: 'a2',
      payload: { place: 'forest' },
    };
    const events = [synthetic, ...EVENTS];
    const proj = createReplayProjector();
    for (const tick of [59, 12]) {
      expect(proj.at(events, [], tick, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS)).toEqual(
        replayStateAt(events, [], tick, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS),
      );
    }
  });
});

describe('replay projector — structural perf (scrub-step incrementality)', () => {
  it('a forward step folds ONLY the events between the two ticks', () => {
    const proj = createReplayProjector();
    proj.at(EVENTS, NO_SNAPSHOTS, 30, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS);
    proj.at(EVENTS, NO_SNAPSHOTS, 33, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS);
    expect(proj.stats.lastFoldSteps).toBe(countBetween(30, 33));
    expect(proj.stats.lastFoldSteps).toBeLessThan(EVENTS.length / 4);
  });

  it('a backward jump restores a checkpoint, never refolds the whole history', () => {
    const proj = createReplayProjector();
    proj.at(EVENTS, NO_SNAPSHOTS, 20, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS); // cp @20
    proj.at(EVENTS, NO_SNAPSHOTS, 50, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS);
    proj.at(EVENTS, NO_SNAPSHOTS, 24, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS); // (20, 24]
    expect(proj.stats.lastFoldSteps).toBe(countBetween(20, 24));
    expect(proj.at(EVENTS, NO_SNAPSHOTS, 24, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS)).toEqual(
      replayStateAt(EVENTS, [], 24, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS),
    );
  });

  it('per-call finalize never corrupts the cursor (repeat call = same frame)', () => {
    const proj = createReplayProjector();
    const first = proj.at(EVENTS, NO_SNAPSHOTS, 46, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS);
    const second = proj.at(EVENTS, NO_SNAPSHOTS, 46, AGENTS, PLACES, LIVE_BUILDINGS, LIVE_ANIMALS);
    expect(second).toEqual(first);
    expect(proj.stats.lastFoldSteps).toBe(0);
  });
});

describe('shouldEngageReplayMaterials — the EM-069 snapshot+delta gate', () => {
  const base = { mockMode: false, archived: false, scrubbed: true, historyLoading: false, historyTruncated: false };

  it('never engages in mock mode', () => {
    expect(shouldEngageReplayMaterials({ ...base, mockMode: true, historyTruncated: true })).toBe(false);
    expect(shouldEngageReplayMaterials({ ...base, mockMode: true, archived: true })).toBe(false);
  });

  it('always engages in archive mode (snapshots are the only geometry)', () => {
    expect(shouldEngageReplayMaterials({ ...base, archived: true, scrubbed: false })).toBe(true);
  });

  it('CAP HONESTY: a truncated history engages while scrubbed — even after the backfill finished', () => {
    expect(shouldEngageReplayMaterials({ ...base, historyTruncated: true })).toBe(true);
  });

  it('engages while the backfill is still in flight', () => {
    expect(shouldEngageReplayMaterials({ ...base, historyLoading: true })).toBe(true);
  });

  it('does NOT engage when the in-memory history is complete', () => {
    expect(shouldEngageReplayMaterials(base)).toBe(false);
  });

  it('does NOT engage at the live edge (unscrubbed), even truncated', () => {
    expect(shouldEngageReplayMaterials({ ...base, scrubbed: false, historyTruncated: true })).toBe(false);
  });
});
