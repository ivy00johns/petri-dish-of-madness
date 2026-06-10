/**
 * storySoFar (EM-094) — the always-on, ZERO-LLM "story so far" digest.
 *
 * A pure selector over the rolling event history + the latest world_state
 * projection (contract frontend-inspector.md §9). It computes:
 *   • the alive/dead roster, with death ticks recovered from agent_died events
 *   • active-rule count + the newest active rule's text
 *   • project/building statuses (W7 buildings)
 *   • a "current drama" heuristic — the most recent of: extinction, conflict,
 *     starvation warning, a death, or a rule vote in progress
 *   • the narrator channel: newest `narrator_summary` event + count (the
 *     OPTIONAL server-side LLM narrator, event-log.md v1.2.0 note 1 — this
 *     selector only reads what already exists; it never asks for a recap)
 *
 * Everything degrades to labeled-empty values (never undefined holes) so the
 * digest block renders in mock mode and on a fresh run alike.
 */

import type { WorldEvent, WorldState } from '../types';

export interface RosterEntry {
  id: string;
  name: string;
}

export interface DeadEntry extends RosterEntry {
  /** Tick of the agent_died event, when it is still inside the history window. */
  deathTick: number | null;
}

export interface ProjectEntry {
  id: string;
  name: string;
  status: string;
  /** 0..100 build progress (meaningful while planned/under_construction). */
  progress: number;
}

export interface DramaEntry {
  /** Short uppercase register for the chip, e.g. "CONFLICT". */
  label: string;
  /** The event's feed line (fallback: its kind). */
  text: string;
  tick: number;
}

export interface StoryDigest {
  aliveCount: number;
  totalCount: number;
  alive: RosterEntry[];
  dead: DeadEntry[];
  activeRuleCount: number;
  /** Text of the newest active rule (by created_tick), or null when none. */
  newestRuleText: string | null;
  /** True while any rule sits in `proposed` (a vote is in progress). */
  ruleVoteInProgress: boolean;
  projects: ProjectEntry[];
  drama: DramaEntry | null;
  /** Newest narrator_summary event in the window (null = none seen). */
  narratorLatest: WorldEvent | null;
  narratorCount: number;
}

/** Drama register: the most recent of these kinds wins (scan is newest-first). */
const DRAMA_LABELS: Record<string, string> = {
  world_extinct: 'EXTINCTION',
  conflict: 'CONFLICT',
  agent_starving: 'STARVATION',
  agent_died: 'DEATH',
  rule_proposed: 'RULE VOTE',
  rule_vote: 'RULE VOTE',
};

/** world.starving_warn_threshold default (EM-070) — payload.threshold wins. */
const STARVING_THRESHOLD_DEFAULT = 25;

/**
 * EM-144 — a STARVATION headline is a claim about CURRENT state, unlike the
 * momentary dramas (a conflict happened; a death happened). Corroborate it
 * against the live world before headlining: an agent who recharged back above
 * the threshold (or died — death is its own drama) makes the event stale, and
 * the scan moves on to the next drama candidate. With no world projection yet
 * (mock boot, pre-first-broadcast) there is nothing to corroborate against,
 * so the event stands.
 */
function isStaleStarvation(
  e: WorldEvent,
  world: WorldState | null,
): boolean {
  // No world projection yet, or no actor on the event — nothing to
  // corroborate against, so the event stands.
  if (e.kind !== 'agent_starving' || world === null || !e.actor_id) return false;
  const agent = world.agents?.find((a) => a.id === e.actor_id);
  if (!agent || !agent.alive) return true;
  const threshold =
    typeof e.payload?.threshold === 'number'
      ? e.payload.threshold
      : STARVING_THRESHOLD_DEFAULT;
  return agent.energy >= threshold;
}

/**
 * Compute the digest. `history` is the standard NEWEST-FIRST rolling window
 * (useSimulation.history); `world` is the latest world_state (or null before
 * the first broadcast — the digest then reports an empty-but-shaped result).
 */
export function storySoFar(
  history: WorldEvent[],
  world: WorldState | null,
): StoryDigest {
  const agents = world?.agents ?? [];

  // Death ticks: first (newest) agent_died per actor in the window. Deaths
  // older than the window simply have no tick — the UI labels that, it never
  // shows a lone "?".
  const deathTickById = new Map<string, number>();
  let narratorLatest: WorldEvent | null = null;
  let narratorCount = 0;
  let drama: DramaEntry | null = null;

  for (const e of history) {
    if (e.kind === 'agent_died' && e.actor_id && !deathTickById.has(e.actor_id)) {
      deathTickById.set(e.actor_id, e.tick);
    }
    if (e.kind === 'narrator_summary') {
      narratorCount++;
      if (!narratorLatest) narratorLatest = e;
    }
    if (!drama) {
      const label = DRAMA_LABELS[e.kind];
      if (label && !isStaleStarvation(e, world)) {
        drama = { label, text: e.text ?? `[${e.kind}]`, tick: e.tick };
      }
    }
  }

  const alive: RosterEntry[] = [];
  const dead: DeadEntry[] = [];
  for (const a of agents) {
    if (a.alive) {
      alive.push({ id: a.id, name: a.name });
    } else {
      dead.push({ id: a.id, name: a.name, deathTick: deathTickById.get(a.id) ?? null });
    }
  }
  // Dead roster reads chronologically (unknown-tick deaths last).
  dead.sort((x, y) => (x.deathTick ?? Number.MAX_SAFE_INTEGER) - (y.deathTick ?? Number.MAX_SAFE_INTEGER));

  const rules = world?.rules ?? [];
  const activeRules = rules.filter((r) => r.status === 'active');
  const newestActive = activeRules.reduce<typeof activeRules[number] | null>(
    (best, r) => (best === null || r.created_tick > best.created_tick ? r : best),
    null,
  );
  const ruleVoteInProgress = rules.some((r) => r.status === 'proposed');

  const projects: ProjectEntry[] = (world?.buildings ?? []).map((b) => ({
    id: b.id,
    name: b.name,
    status: b.status,
    progress: b.progress,
  }));

  return {
    aliveCount: alive.length,
    totalCount: agents.length,
    alive,
    dead,
    activeRuleCount: activeRules.length,
    newestRuleText: newestActive?.text ?? null,
    ruleVoteInProgress,
    projects,
    drama,
    narratorLatest,
    narratorCount,
  };
}

// ──────────────────────────────────────────────────────────────────────────────
// EM-139 — bounded project readout.
//
// A long-lived world accumulates dozens of finished/ruined projects (a day-197
// run carried ~50 destroyed ones); enumerating every building turned the
// digest's PROJECTS line into a wall of text that made the feed unscrollable.
// LIVE projects (planned / under_construction) are listed by name with their
// progress, capped; everything settled (operational/damaged/offline/abandoned/
// destroyed) aggregates to status counts. Zero-LLM, pure presentation.
// ──────────────────────────────────────────────────────────────────────────────

/** How many live (planned/building) projects are named before "+N more". */
export const PROJECTS_LISTED_CAP = 3;

/** Settled statuses in display order; anything novel surfaces after these. */
const SETTLED_STATUS_ORDER = [
  'operational', 'damaged', 'offline', 'abandoned', 'destroyed',
] as const;

export function projectReadout(projects: ProjectEntry[]): string {
  const live = projects.filter(
    (p) => p.status === 'planned' || p.status === 'under_construction',
  );
  const parts: string[] = live
    .slice(0, PROJECTS_LISTED_CAP)
    .map((p) =>
      `${p.name} ${p.progress}% ${p.status === 'planned' ? 'planned' : 'building'}`,
    );
  if (live.length > PROJECTS_LISTED_CAP) {
    parts.push(`+${live.length - PROJECTS_LISTED_CAP} more in progress`);
  }

  const counts = new Map<string, number>();
  for (const p of projects) {
    if (p.status === 'planned' || p.status === 'under_construction') continue;
    counts.set(p.status, (counts.get(p.status) ?? 0) + 1);
  }
  for (const status of SETTLED_STATUS_ORDER) {
    const n = counts.get(status);
    if (n) parts.push(`${n} ${status}`);
    counts.delete(status);
  }
  for (const [status, n] of counts) parts.push(`${n} ${status}`); // future-proof

  return parts.join(' · ');
}
