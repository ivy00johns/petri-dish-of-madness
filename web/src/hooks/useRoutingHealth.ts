/**
 * useRoutingHealth (EM-072) — detect a silently-collapsed model A/B.
 *
 * The lab's marquee experiment is model-vs-model. Audit A4 caught a run where
 * all "different model" profiles were silently routed to ONE upstream model
 * (`routed_via` identical everywhere) — the comparison data was invalid and
 * nothing said so.
 *
 * Raw signal (computeRoutingHealth, kept for tests / instantaneous reads):
 *
 *   degraded ⇔ ≥2 distinct assigned profiles among LIVING agents
 *              AND every recent routed_via (latest per living agent, from
 *              event payload `routed_via` / `gen_ai.response.model`)
 *              resolves to the SAME single model
 *              AND those samples cover ≥2 distinct profiles
 *              (one profile's samples alone can't condemn the run).
 *
 * Smoothed signal (EM-072 follow-up — what the hook RETURNS): the raw signal
 * FLAPS as FreeLLMAPI upstreams hit/clear rate-limit windows (banner appeared,
 * cleared, came back within minutes). Hysteresis, folded deterministically
 * over the routed-sample stream (pure — no wall clock, so a page refresh
 * reconstructs the same state from history):
 *
 *   SHOW  after DEGRADE_CONSECUTIVE consecutive routed samples that all
 *         resolve to one model while spanning ≥2 assigned profiles;
 *   CLEAR only after ≥CLEAR_DIVERSE samples within the last CLEAR_WINDOW
 *         routed samples resolve to a DIFFERENT model (one lucky diverse
 *         call doesn't clear it);
 *   after a clear, re-showing needs a fresh full run of one-model samples.
 *
 * The result means "this run's comparison is durably compromised", not a
 * per-call status light. `recovered` is true transiently (a few seconds)
 * after a clear so the state change is legible instead of silently vanishing.
 *
 * Pure projection + a tiny transient — works identically in mock and live
 * mode; with no routed samples yet it stays quiet (absence of evidence isn't
 * degradation).
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { WorldState, WorldEvent } from '../types';

export interface RoutingHealth {
  /** True when the multi-model comparison has DURABLY collapsed to one model
   *  (smoothed — see the hysteresis rules above). */
  degraded: boolean;
  /** The single model serving everything (when degraded). */
  model: string | null;
  /** Distinct assigned profiles among living agents. */
  profileCount: number;
  /** Transiently true for a few seconds after degraded clears (EM-072
   *  follow-up): "routing recovered", so the banner doesn't just vanish. */
  recovered?: boolean;
}

const HEALTHY: RoutingHealth = { degraded: false, model: null, profileCount: 0 };

// ── Hysteresis tuning ─────────────────────────────────────────────────────────
/** Consecutive one-model samples (spanning ≥2 profiles) required to SHOW. */
const DEGRADE_CONSECUTIVE = 5;
/** Diverse (different-model) samples required to CLEAR … */
const CLEAR_DIVERSE = 2;
/** … within this many of the most recent samples. */
const CLEAR_WINDOW = 5;
/** How long the "routing recovered" transient stays visible (ms). */
const RECOVERED_MS = 6000;

/** The model that actually answered, when an event payload carries it. */
function routedViaOf(e: WorldEvent): string | null {
  const p = e.payload;
  if (!p) return null;
  const via = p['routed_via'];
  if (typeof via === 'string' && via.length > 0) return via;
  const responseModel = p['gen_ai.response.model'];
  if (typeof responseModel === 'string' && responseModel.length > 0) return responseModel;
  return null;
}

/** Pure INSTANTANEOUS routing-health projection (the raw, un-smoothed signal). */
export function computeRoutingHealth(
  world: WorldState | null,
  events: WorldEvent[],
): RoutingHealth {
  if (!world) return HEALTHY;
  const living = world.agents.filter((a) => a.alive);
  const assignedProfiles = new Set(living.map((a) => a.profile).filter(Boolean));
  if (assignedProfiles.size < 2) return { ...HEALTHY, profileCount: assignedProfiles.size };

  // Latest routed_via per living agent (highest seq wins; the history array is
  // only roughly newest-first, so compare seqs instead of trusting order).
  const profileOf = new Map(living.map((a) => [a.id, a.profile]));
  const latestSeq = new Map<string, number>();
  const latestModel = new Map<string, string>();
  for (const e of events) {
    if (!e.actor_id || !profileOf.has(e.actor_id)) continue;
    const via = routedViaOf(e);
    if (!via) continue;
    if ((latestSeq.get(e.actor_id) ?? Number.NEGATIVE_INFINITY) < e.seq) {
      latestSeq.set(e.actor_id, e.seq);
      latestModel.set(e.actor_id, via);
    }
  }

  const coveredProfiles = new Set<string>();
  const models = new Set<string>();
  for (const [agentId, model] of latestModel) {
    const prof = profileOf.get(agentId);
    if (prof) coveredProfiles.add(prof);
    models.add(model);
  }

  if (coveredProfiles.size < 2 || models.size !== 1) {
    return { degraded: false, model: null, profileCount: assignedProfiles.size };
  }
  return {
    degraded: true,
    model: models.values().next().value ?? null,
    profileCount: assignedProfiles.size,
  };
}

interface RoutedSample {
  profile: string;
  model: string;
}

/**
 * Pure SMOOTHED routing-health projection (the signal the UI consumes).
 * Folds the hysteresis state machine over the routed-sample stream in seq
 * order — deterministic, so the banner state survives a page refresh.
 */
export function computeRoutingHealthSmoothed(
  world: WorldState | null,
  events: WorldEvent[],
): RoutingHealth {
  if (!world) return HEALTHY;
  const living = world.agents.filter((a) => a.alive);
  const assignedProfiles = new Set(living.map((a) => a.profile).filter(Boolean));
  if (assignedProfiles.size < 2) return { ...HEALTHY, profileCount: assignedProfiles.size };

  // The routed-sample stream: every event carrying a routed_via for a living
  // HUMAN agent (animal calls all route to one configured profile by design —
  // they must not condemn the comparison), oldest → newest.
  const profileOf = new Map(living.map((a) => [a.id, a.profile]));
  const samples: Array<RoutedSample & { seq: number }> = [];
  for (const e of events) {
    if (!e.actor_id || e.actor_type === 'animal') continue;
    const profile = profileOf.get(e.actor_id);
    if (!profile) continue;
    const model = routedViaOf(e);
    if (!model) continue;
    samples.push({ profile, model, seq: e.seq });
  }
  samples.sort((a, b) => a.seq - b.seq);

  // Fold the SHOW/CLEAR state machine over the stream.
  let shownModel: string | null = null;
  let preShown: RoutedSample[] = []; // rolling last-N while healthy
  let postShown: RoutedSample[] = []; // rolling last-N while degraded
  for (const s of samples) {
    if (shownModel === null) {
      preShown.push(s);
      if (preShown.length > DEGRADE_CONSECUTIVE) preShown.shift();
      if (preShown.length === DEGRADE_CONSECUTIVE) {
        const models = new Set(preShown.map((r) => r.model));
        const profs = new Set(preShown.map((r) => r.profile));
        if (models.size === 1 && profs.size >= 2) {
          shownModel = s.model;
          postShown = [];
        }
      }
    } else {
      postShown.push(s);
      if (postShown.length > CLEAR_WINDOW) postShown.shift();
      const diverse = postShown.filter((r) => r.model !== shownModel).length;
      if (diverse >= CLEAR_DIVERSE) {
        // Durable recovery: clear, and require a FULL fresh run to re-show.
        shownModel = null;
        preShown = [];
        postShown = [];
      }
    }
  }

  if (shownModel === null) {
    return { degraded: false, model: null, profileCount: assignedProfiles.size };
  }
  return { degraded: true, model: shownModel, profileCount: assignedProfiles.size };
}

export function useRoutingHealth(
  world: WorldState | null,
  events: WorldEvent[],
): RoutingHealth {
  const health = useMemo(() => computeRoutingHealthSmoothed(world, events), [world, events]);

  // "Routing recovered" transient: when the smoothed signal transitions
  // degraded → healthy, surface `recovered` for a few seconds so the banner
  // change is legible instead of the warning silently vanishing.
  const prevDegradedRef = useRef(false);
  const [recovered, setRecovered] = useState(false);
  useEffect(() => {
    const was = prevDegradedRef.current;
    prevDegradedRef.current = health.degraded;
    if (was && !health.degraded) {
      setRecovered(true);
      const t = setTimeout(() => setRecovered(false), RECOVERED_MS);
      return () => clearTimeout(t);
    }
    if (health.degraded && recovered) setRecovered(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [health.degraded]);

  return useMemo(
    () => (recovered ? { ...health, recovered: true } : health),
    [health, recovered],
  );
}
