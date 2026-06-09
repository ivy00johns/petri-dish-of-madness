/**
 * Extinction / end-of-run projections (EM-071 UI) — pure selector-style
 * functions over the event history + final world state, kept out of the
 * component file so react-refresh stays happy and the math is testable.
 *
 * Detection is belt-and-suspenders: the `world_extinct` event when the W9
 * backend emits it (payload {tick, last_agent_id, auto_paused}, event-log.md
 * v1.1.0 §4), OR zero living human agents in a non-empty world_state — so an
 * older backend (or mock mode) still gets the banner. Never mutates inputs.
 */

import type { WorldState, WorldEvent } from '../types';

export interface ExtinctionInfo {
  extinct: boolean;
  /** Tick of extinction (world_extinct payload/tick, else the last death). */
  tick: number;
  /** True when the engine auto-paused on extinction (or the world is paused). */
  autoPaused: boolean;
}

export interface RunSummary {
  ticksSurvived: number;
  /** Every villager death, in order. */
  deaths: Array<{ name: string; tick: number }>;
  rulesPassed: number;
  rulesRejected: number;
  crimes: number;
  /** Highest credit holder at the end (may well be a corpse). */
  topCreditHolder: { name: string; credits: number } | null;
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

/** Detect extinction from the event log and/or the live world projection. */
export function computeExtinction(
  world: WorldState | null,
  events: WorldEvent[],
): ExtinctionInfo | null {
  // Preferred signal: the W9 `world_extinct` event (latest by seq).
  let extinctEvent: WorldEvent | null = null;
  for (const e of events) {
    if (e.kind !== 'world_extinct') continue;
    if (!extinctEvent || e.seq > extinctEvent.seq) extinctEvent = e;
  }
  // Fallback: a populated world with zero living human agents.
  const humansAllDead =
    world !== null && world.agents.length > 0 && world.agents.every((a) => !a.alive);
  if (!extinctEvent && !humansAllDead) return null;

  let tick = extinctEvent ? num(extinctEvent.payload?.['tick']) ?? extinctEvent.tick : null;
  if (tick === null) {
    // Last villager death tick, else the current world tick.
    let lastDeath: number | null = null;
    for (const e of events) {
      if (e.kind === 'agent_died' && (lastDeath === null || e.tick > lastDeath)) lastDeath = e.tick;
    }
    tick = lastDeath ?? world?.tick ?? 0;
  }

  const autoPaused =
    extinctEvent?.payload?.['auto_paused'] === true || (world !== null && !world.running);

  return { extinct: true, tick, autoPaused };
}

/** End-of-run rollup, projected from the event history + final world state. */
export function computeRunSummary(
  world: WorldState | null,
  events: WorldEvent[],
  extinctionTick: number,
): RunSummary {
  const nameOf = new Map((world?.agents ?? []).map((a) => [a.id, a.name]));

  const deaths = events
    .filter((e) => e.kind === 'agent_died')
    .sort((a, b) => a.tick - b.tick || a.seq - b.seq)
    .map((e) => ({
      name: (e.actor_id && nameOf.get(e.actor_id)) || e.actor_id || 'unknown',
      tick: e.tick,
    }));

  let rulesPassed = 0;
  let rulesRejected = 0;
  let crimes = 0;
  for (const e of events) {
    if (e.kind === 'rule_passed') rulesPassed += 1;
    else if (e.kind === 'rule_rejected') rulesRejected += 1;
    else if (e.kind === 'conflict') crimes += 1;
  }

  let topCreditHolder: RunSummary['topCreditHolder'] = null;
  for (const a of world?.agents ?? []) {
    if (topCreditHolder === null || a.credits > topCreditHolder.credits) {
      topCreditHolder = { name: a.name, credits: a.credits };
    }
  }

  return { ticksSurvived: extinctionTick, deaths, rulesPassed, rulesRejected, crimes, topCreditHolder };
}
