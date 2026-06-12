/**
 * projections.ts (wave F, EM-194) — incremental scrub-time projectors.
 *
 * Dragging the inspector scrubber used to re-run the full O(n) selector folds
 * (agentEconomyAt, replayStateAt) over the ENTIRE history on every tick
 * change. At long-session scale (50k events in memory) that froze the annex.
 *
 * These projectors keep a CURSOR — the fold state advanced to the last
 * projected tick — and on a forward scrub step fold ONLY the events in
 * (lastTick, newTick]. Jumping backward restores the nearest cached
 * checkpoint ≤ the target (bounded LRU) and folds forward from there, or
 * reseeds from the snapshot/zero state when none fits.
 *
 * Equality guarantee: the projectors advance the SAME fold-step functions the
 * plain selectors run (economyFoldStep / replayFoldSeed / replayFoldStep /
 * replayFoldFinalize, exported by selectors.ts), so a projection at ANY tick
 * is equal to the full fold by construction — and pinned by the golden test
 * (projections.test.ts) comparing both paths over a fixture run.
 *
 * Precondition: the pointer walk assumes tick is NON-DECREASING in seq order
 * (true of the append-only event log). The projectors verify this once per
 * events array; non-monotone data (e.g. mock-mode synthetic negative seqs)
 * falls back to the plain full-fold selectors — still exact, just not
 * incremental.
 */

import type { Agent, Animal, Building, WorldEvent } from '../types';
import type { ReplayFrame } from './types';
import {
  agentEconomyAt,
  economyFoldStep,
  nearestSnapshot,
  replayFoldFinalize,
  replayFoldSeed,
  replayFoldStep,
  replayStateAt,
  sortedBySeqAsc,
} from './selectors';
import type {
  AgentEconomySample,
  ReplayFoldInputs,
  ReplayFoldPostWindow,
  ReplayFoldState,
  ReplaySnapshot,
} from './selectors';

/** Checkpoint LRU bound — plenty for scrub gestures, bounded memory. */
const CHECKPOINT_LIMIT = 32;

/** Structural-perf instrumentation (asserted by projections.test.ts). */
export interface ProjectorStats {
  /** Fold steps executed by the LAST at() call (events actually processed). */
  lastFoldSteps: number;
  /** Cold rebuilds (events-ref change or no usable checkpoint on a back-jump). */
  resets: number;
}

function str(v: unknown): string | null {
  return typeof v === 'string' ? v : null;
}

/** True when tick is non-decreasing across the seq-ascending array. */
function ticksMonotone(asc: WorldEvent[]): boolean {
  for (let i = 1; i < asc.length; i++) {
    if (asc[i].tick < asc[i - 1].tick) return false;
  }
  return true;
}

/** First index whose tick is > t (asc sorted by seq, tick monotone). */
function firstIndexAfterTick(asc: WorldEvent[], t: number): number {
  let lo = 0;
  let hi = asc.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (asc[mid].tick > t) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

/** First index whose tick is >= t (asc sorted by seq, tick monotone). */
function firstIndexAtTick(asc: WorldEvent[], t: number): number {
  let lo = 0;
  let hi = asc.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (asc[mid].tick >= t) hi = mid;
    else lo = mid + 1;
  }
  return lo;
}

/** Evict the oldest entries of an insertion-ordered Map down to the bound. */
function evictLru<K, V>(map: Map<K, V>): void {
  while (map.size > CHECKPOINT_LIMIT) {
    const oldest = map.keys().next().value;
    if (oldest === undefined) return;
    map.delete(oldest);
  }
}

// ── Economy projector (agentEconomyAt, incremental) ──────────────────────────

export interface EconomyProjector {
  /**
   * Per-agent {energy, credits} at `tick`, equal to
   * agentEconomyAt(events.filter(e => e.tick <= tick)).
   */
  at(events: WorldEvent[], tick: number): Map<string, AgentEconomySample>;
  readonly stats: ProjectorStats;
}

type EconomyState = Map<string, AgentEconomySample>;

function cloneEconomy(s: EconomyState): EconomyState {
  const out: EconomyState = new Map();
  for (const [k, v] of s) out.set(k, { ...v });
  return out;
}

export function createEconomyProjector(): EconomyProjector {
  let eventsRef: WorldEvent[] | null = null;
  let asc: WorldEvent[] = [];
  let monotone = true;
  let cursorTick = -1;
  let cursorIdx = 0;
  let state: EconomyState = new Map();
  const checkpoints = new Map<number, EconomyState>();
  const stats: ProjectorStats = { lastFoldSteps: 0, resets: 0 };

  function at(events: WorldEvent[], tick: number): EconomyState {
    if (events !== eventsRef) {
      eventsRef = events;
      asc = sortedBySeqAsc(events);
      monotone = ticksMonotone(asc);
      cursorTick = -1;
      cursorIdx = 0;
      state = new Map();
      checkpoints.clear();
      stats.resets += 1;
    }
    if (!monotone) {
      // Exact fallback: the pointer-walk precondition fails on this data.
      stats.lastFoldSteps = asc.length;
      return agentEconomyAt(events.filter((e) => e.tick <= tick));
    }
    if (tick < cursorTick) {
      // Backward jump: restore the nearest checkpoint ≤ tick, else zero state.
      let bestTick = -1;
      let best: EconomyState | null = null;
      for (const [t, s] of checkpoints) {
        if (t <= tick && t > bestTick) {
          bestTick = t;
          best = s;
        }
      }
      if (best) {
        state = cloneEconomy(best);
        cursorTick = bestTick;
      } else {
        state = new Map();
        cursorTick = -1;
        stats.resets += 1;
      }
      cursorIdx = cursorTick < 0 ? 0 : firstIndexAfterTick(asc, cursorTick);
    }
    let steps = 0;
    while (cursorIdx < asc.length && asc[cursorIdx].tick <= tick) {
      economyFoldStep(state, asc[cursorIdx]);
      cursorIdx += 1;
      steps += 1;
    }
    cursorTick = tick;
    stats.lastFoldSteps = steps;
    // Checkpoint this tick (LRU-bounded) and return an isolated copy so a
    // caller mutation can never corrupt the cursor or a checkpoint.
    checkpoints.delete(tick);
    checkpoints.set(tick, cloneEconomy(state));
    evictLru(checkpoints);
    return cloneEconomy(state);
  }

  return { at, stats };
}

// ── Replay projector (replayStateAt, incremental) ────────────────────────────

export interface ReplayProjector {
  /** ReplayFrame at `tick`, equal to replayStateAt(events, snapshots, tick, …). */
  at(
    events: WorldEvent[],
    snapshots: ReplaySnapshot[],
    tick: number,
    agents: Agent[],
    places: Array<{ id: string; x: number; y: number }>,
    liveBuildings?: Building[],
    liveAnimals?: Animal[],
  ): ReplayFrame;
  readonly stats: ProjectorStats;
}

interface ReplayCheckpoint {
  fromTick: number;
  tick: number;
  state: ReplayFoldState;
}

function cloneReplayState(s: ReplayFoldState): ReplayFoldState {
  const bld: ReplayFoldState['bld'] = new Map();
  for (const [k, v] of s.bld) bld.set(k, { ...v });
  const ani: ReplayFoldState['ani'] = new Map();
  for (const [k, v] of s.ani) ani.set(k, { ...v });
  return {
    fromTick: s.fromTick,
    // placeXY is static after seeding (events never move places) — share it.
    placeXY: s.placeXY,
    location: new Map(s.location),
    profileOf: new Map(s.profileOf),
    aliveOf: new Map(s.aliveOf),
    bld,
    ani,
  };
}

export function createReplayProjector(): ReplayProjector {
  // Reset keys: the projector is valid for ONE combination of input refs.
  let eventsRef: WorldEvent[] | null = null;
  let snapshotsRef: ReplaySnapshot[] | null = null;
  let inputs: ReplayFoldInputs | null = null;

  let asc: WorldEvent[] = [];
  let monotone = true;
  // Per-events indexes serving the finalize post-window in O(log n):
  //   building id → its events (seq-asc; tick monotone within),
  //   animal_spawned events (seq-asc).
  let buildingEvents = new Map<string, WorldEvent[]>();
  let animalSpawns: WorldEvent[] = [];

  let state: ReplayFoldState | null = null;
  let cursorTick = -1;
  let cursorIdx = 0;
  const checkpoints = new Map<string, ReplayCheckpoint>();
  const stats: ProjectorStats = { lastFoldSteps: 0, resets: 0 };

  function rebuildIndexes(): void {
    buildingEvents = new Map();
    animalSpawns = [];
    for (const e of asc) {
      // Mirror of the back-fill's id resolution in replayStateAt: payload
      // building_id, else target_id (any kind — the original scan is open).
      const bid = str(e.payload?.['building_id']) ?? e.target_id;
      if (typeof bid === 'string' && bid.length > 0) {
        const list = buildingEvents.get(bid);
        if (list) list.push(e);
        else buildingEvents.set(bid, [e]);
      }
      if (e.kind === 'animal_spawned' && e.actor_id) animalSpawns.push(e);
    }
  }

  function at(
    events: WorldEvent[],
    snapshots: ReplaySnapshot[],
    tick: number,
    agents: Agent[],
    places: Array<{ id: string; x: number; y: number }>,
    liveBuildings: Building[] = [],
    liveAnimals: Animal[] = [],
  ): ReplayFrame {
    const inputsChanged =
      inputs === null ||
      inputs.agents !== agents ||
      inputs.places !== places ||
      inputs.liveBuildings !== liveBuildings ||
      inputs.liveAnimals !== liveAnimals;
    if (events !== eventsRef || snapshots !== snapshotsRef || inputsChanged) {
      eventsRef = events;
      snapshotsRef = snapshots;
      inputs = { agents, places, liveBuildings, liveAnimals };
      asc = sortedBySeqAsc(events);
      monotone = ticksMonotone(asc);
      if (monotone) rebuildIndexes();
      state = null;
      cursorTick = -1;
      cursorIdx = 0;
      checkpoints.clear();
      stats.resets += 1;
    }
    if (!monotone) {
      // Exact fallback: the pointer-walk precondition fails on this data.
      stats.lastFoldSteps = asc.length;
      return replayStateAt(events, snapshots, tick, agents, places, liveBuildings, liveAnimals);
    }
    // `inputs` is always set by the reset block above; narrow it for TS.
    const foldInputs: ReplayFoldInputs = inputs ?? { agents, places, liveBuildings, liveAnimals };

    const base = nearestSnapshot(snapshots, tick);
    const fromTick = base ? base.tick : -1;

    if (state === null || state.fromTick !== fromTick || tick < cursorTick) {
      // The cursor can't serve this tick (different fold base, or a backward
      // jump): restore the best same-base checkpoint ≤ tick, else reseed.
      let best: ReplayCheckpoint | null = null;
      for (const cp of checkpoints.values()) {
        if (cp.fromTick !== fromTick || cp.tick > tick) continue;
        if (best === null || cp.tick > best.tick) best = cp;
      }
      if (best) {
        state = cloneReplayState(best.state);
        cursorTick = best.tick;
      } else {
        state = replayFoldSeed(base, foldInputs);
        cursorTick = fromTick;
        stats.resets += 1;
      }
      cursorIdx = firstIndexAfterTick(asc, cursorTick);
    }

    let steps = 0;
    while (cursorIdx < asc.length && asc[cursorIdx].tick <= tick) {
      replayFoldStep(state, asc[cursorIdx]);
      cursorIdx += 1;
      steps += 1;
    }
    cursorTick = tick;
    stats.lastFoldSteps = steps;

    const cpKey = `${fromTick}:${tick}`;
    checkpoints.delete(cpKey);
    checkpoints.set(cpKey, { fromTick, tick, state: cloneReplayState(state) });
    evictLru(checkpoints);

    const post: ReplayFoldPostWindow = {
      earliestLaterBuildingEvent: (buildingId) => {
        const list = buildingEvents.get(buildingId);
        if (!list) return null;
        const i = firstIndexAfterTick(list, tick);
        return i < list.length ? list[i] : null;
      },
      spawnsAfterTick: animalSpawns.slice(firstIndexAfterTick(animalSpawns, tick)),
      eventsAtTick: asc.slice(firstIndexAtTick(asc, tick), firstIndexAfterTick(asc, tick)),
    };
    return replayFoldFinalize(state, tick, foldInputs, post);
  }

  return { at, stats };
}

// ── Deep-replay engagement (the EM-069 snapshot+delta path) ──────────────────

/**
 * When the inspector must fetch GET /api/replay materials instead of trusting
 * the in-memory history (extracted pure from InspectorLayout for testability):
 *   • never in mock mode (no backend);
 *   • ALWAYS in archive mode (the run's snapshots are the only geometry);
 *   • live: while scrubbed AND the client history is unfaithful — backfill
 *     still in flight OR truncated at the memory cap (wave F cap-honesty:
 *     pre-cap ticks must engage snapshot+delta, never project from a hole).
 */
export function shouldEngageReplayMaterials(opts: {
  mockMode: boolean;
  archived: boolean;
  scrubbed: boolean;
  historyLoading: boolean;
  historyTruncated: boolean;
}): boolean {
  if (opts.mockMode) return false;
  if (opts.archived) return true;
  return opts.scrubbed && (opts.historyLoading || opts.historyTruncated);
}
