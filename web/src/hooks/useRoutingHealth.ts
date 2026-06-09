/**
 * useRoutingHealth (EM-072) — detect a silently-collapsed model A/B.
 *
 * The lab's marquee experiment is model-vs-model. Audit A4 caught a run where
 * all "different model" profiles were silently routed to ONE upstream model
 * (`routed_via` identical everywhere) — the comparison data was invalid and
 * nothing said so. This hook computes, from live data only:
 *
 *   degraded ⇔ ≥2 distinct assigned profiles among LIVING agents
 *              AND every recent routed_via (latest per living agent, from
 *              event payload `routed_via` / `gen_ai.response.model`)
 *              resolves to the SAME single model
 *              AND those samples cover ≥2 distinct profiles
 *              (one profile's samples alone can't condemn the run).
 *
 * Pure projection — works identically in mock and live mode; with no routed
 * samples yet it stays quiet (absence of evidence isn't degradation).
 */

import { useMemo } from 'react';
import type { WorldState, WorldEvent } from '../types';

export interface RoutingHealth {
  /** True when the multi-model comparison has collapsed to one model. */
  degraded: boolean;
  /** The single model serving everything (when degraded). */
  model: string | null;
  /** Distinct assigned profiles among living agents. */
  profileCount: number;
}

const HEALTHY: RoutingHealth = { degraded: false, model: null, profileCount: 0 };

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

/** Pure routing-health projection over the world + event history. */
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

export function useRoutingHealth(
  world: WorldState | null,
  events: WorldEvent[],
): RoutingHealth {
  return useMemo(() => computeRoutingHealth(world, events), [world, events]);
}
