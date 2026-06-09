/**
 * useReplayMaterials (EM-069, frontend-inspector.md v1.1.0 §2) — the deep-
 * replay fetch behind the inspector scrub.
 *
 * When the user seeks to a tick the client-side history can't faithfully
 * project (backfill still loading, or the memory cap dropped older events),
 * this hook fetches GET /api/replay?tick=T. Per api.openapi.yaml v1.2.0 the
 * response is `base` (nearest prior snapshot — state AFTER all tick-base.tick
 * events) plus a DELTA-ONLY `events` array (base.tick < e.tick <= T, strict on
 * the left), which the caller folds onto base.state through the SAME
 * `replayStateAt` selector the rolling history uses.
 *
 * Degrades gracefully: with no backend (mock mode / older backend) the fetch
 * resolves to empty materials and the panels keep projecting from the rolling
 * history. Stale responses are dropped (request-id guard), seeks are debounced
 * (a slider drag fires many ticks), and a small per-tick cache avoids
 * re-fetching while stepping around the same neighborhood.
 */

import { useEffect, useRef, useState } from 'react';
import { inspectorApi, eventRowToWorldEvent } from './api';
import type { ReplayMaterials } from './api';
import type { WorldEvent } from '../types';
import type { ReplaySnapshot } from './selectors';

/** Replay materials lifted into the shapes the selectors consume. */
export interface ReplayTickMaterials {
  /** The tick the materials were fetched for. */
  tick: number;
  /** base.state lifted into the `replayStateAt` snapshot shape (null = none). */
  snapshot: ReplaySnapshot | null;
  /** The strict-left delta (base.tick < e.tick <= tick), as WorldEvents. */
  events: WorldEvent[];
}

const DEBOUNCE_MS = 150;
const CACHE_MAX = 64;

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

function str(v: unknown): string | null {
  return typeof v === 'string' ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/**
 * Lift /api/replay `base` into the ReplaySnapshot the fold consumes. Open,
 * defensive parsing — the snapshot state is the backend's world serialization;
 * we only need agent positions/liveness and place coords, and tolerate absence.
 */
export function materialsToSnapshot(m: ReplayMaterials): ReplaySnapshot | null {
  if (!m.base) return null;
  const state = m.base.state;
  const snapshot: ReplaySnapshot = { tick: m.base.tick };

  const agentsRaw = state['agents'];
  if (Array.isArray(agentsRaw)) {
    const agents: NonNullable<ReplaySnapshot['agents']> = [];
    for (const raw of agentsRaw) {
      if (!isObj(raw)) continue;
      const id = str(raw['id']);
      const location = str(raw['location']);
      if (!id || !location) continue;
      agents.push({
        id,
        location,
        profile: str(raw['profile']),
        alive: typeof raw['alive'] === 'boolean' ? raw['alive'] : undefined,
      });
    }
    if (agents.length > 0) snapshot.agents = agents;
  }

  const placesRaw = state['places'];
  if (Array.isArray(placesRaw)) {
    const places: NonNullable<ReplaySnapshot['places']> = [];
    for (const raw of placesRaw) {
      if (!isObj(raw)) continue;
      const id = str(raw['id']);
      const x = num(raw['x']);
      const y = num(raw['y']);
      if (!id || x === null || y === null) continue;
      places.push({ id, x, y });
    }
    if (places.length > 0) snapshot.places = places;
  }

  // W10 / audit C7: building state rides the snapshot (world.to_snapshot
  // serializes `buildings`), giving the replay fold an authoritative base for
  // status/progress at base.tick. Every field is optional-tolerant.
  const buildingsRaw = state['buildings'];
  if (Array.isArray(buildingsRaw)) {
    const buildings: NonNullable<ReplaySnapshot['buildings']> = [];
    for (const raw of buildingsRaw) {
      if (!isObj(raw)) continue;
      const id = str(raw['id']);
      if (!id) continue;
      buildings.push({
        id,
        name: str(raw['name']) ?? undefined,
        kind: str(raw['kind']) ?? undefined,
        location: str(raw['location']) ?? undefined,
        status: str(raw['status']) ?? undefined,
        progress: num(raw['progress']) ?? undefined,
      });
    }
    if (buildings.length > 0) snapshot.buildings = buildings;
  }

  // W10 / audit D4: the animal roster rides the snapshot too — the only
  // tick-faithful position source (animal moves are not evented with a place).
  const animalsRaw = state['animals'];
  if (Array.isArray(animalsRaw)) {
    const animals: NonNullable<ReplaySnapshot['animals']> = [];
    for (const raw of animalsRaw) {
      if (!isObj(raw)) continue;
      const id = str(raw['id']);
      const location = str(raw['location']);
      if (!id || !location) continue;
      animals.push({
        id,
        location,
        name: str(raw['name']) ?? undefined,
        species: str(raw['species']) ?? undefined,
        alive: typeof raw['alive'] === 'boolean' ? raw['alive'] : undefined,
      });
    }
    if (animals.length > 0) snapshot.animals = animals;
  }

  return snapshot;
}

/**
 * Fetch replay materials for `tick` while `enabled`. Returns the latest
 * materials (or null when disabled / not yet fetched) and a fetching flag the
 * layout surfaces as a labeled notice.
 *
 * W11a (EM-086): an optional `runId` scopes the /api/replay call to a past run
 * (archive mode). The per-tick cache is keyed by (runId, tick), so toggling
 * live ⇄ archive can never serve one run's snapshot for another.
 */
export function useReplayMaterials(
  enabled: boolean,
  tick: number,
  runId?: number | null,
): { materials: ReplayTickMaterials | null; fetching: boolean } {
  const [materials, setMaterials] = useState<ReplayTickMaterials | null>(null);
  const [fetching, setFetching] = useState(false);
  const reqRef = useRef(0);
  const cacheRef = useRef(new Map<string, ReplayTickMaterials>());
  const lastRunRef = useRef<number | null>(runId ?? null);

  useEffect(() => {
    // Crossing a run boundary DROPS the held materials immediately — another
    // run's snapshot must never be folded while the new fetch is in flight
    // (EM-086 "no stale data bleeding in"). Within a run, the previous tick's
    // materials are intentionally kept for scrub smoothness.
    if ((runId ?? null) !== lastRunRef.current) {
      lastRunRef.current = runId ?? null;
      setMaterials(null);
    }
    if (!enabled) {
      setMaterials(null);
      setFetching(false);
      return;
    }
    const cacheKey = `${runId ?? 'live'}:${tick}`;
    const cached = cacheRef.current.get(cacheKey);
    if (cached) {
      setMaterials(cached);
      setFetching(false);
      return;
    }
    const req = ++reqRef.current;
    let alive = true;
    const timer = setTimeout(() => {
      setFetching(true);
      void inspectorApi.replay(tick, runId ?? undefined).then((m) => {
        if (!alive || req !== reqRef.current) return;
        const out: ReplayTickMaterials = {
          tick,
          snapshot: materialsToSnapshot(m),
          events: m.events.map(eventRowToWorldEvent),
        };
        // Only cache useful materials so a transient failure retries later.
        if (out.snapshot !== null || out.events.length > 0) {
          cacheRef.current.set(cacheKey, out);
          if (cacheRef.current.size > CACHE_MAX) {
            const oldest = cacheRef.current.keys().next().value;
            if (oldest !== undefined) cacheRef.current.delete(oldest);
          }
        }
        setMaterials(out);
        setFetching(false);
      });
    }, DEBOUNCE_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [enabled, tick, runId]);

  return { materials: enabled ? materials : null, fetching: enabled && fetching };
}
