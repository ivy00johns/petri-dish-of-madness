/**
 * animalIdentity (EM-089) — surface the critters' LLM identity.
 *
 * Animals are LLM-driven on a roll (config `animals.model_profile`,
 * `llm_chance`; reflex otherwise) but the UI never showed it. Two pure
 * projections over the event history:
 *
 *   • `animalModelMap` — which model profile each animal consults. The
 *     world_state Animal shape does NOT carry the profile (backend
 *     `Animal.to_dict` omits it — confirmed), so the source of truth here is
 *     the latest animal `llm_call` event: it carries top-level `profile` plus
 *     OTel `gen_ai.request.model` in the payload (animals/runtime.py). An
 *     animal that has never consulted the LLM (or whose llm_call fell out of
 *     the loaded window) is simply absent — callers omit the chip.
 *
 *   • `llmDecidedAnimalTurns` — the turn_ids of animal LLM decisions. Every
 *     animal turn gets its OWN turn_id (W9/B1), and the runtime emits an
 *     `llm_call` (actor_type:"animal") in the same turn as the `animal_action`
 *     it produced — so an animal_action sharing a turn_id with one of these is
 *     an LLM decision (🧠); anything else was a zero-cost reflex. The
 *     animal_action payload carries NO tier/llm marker (confirmed), so the
 *     turn_id correlation is the only signal; degrade = no marker.
 *
 * Both degrade gracefully when the data isn't there (pre-W8 backends, sparse
 * mock histories): empty map / empty set, never a fake identity.
 */

import type { Animal, ModelProfile, WorldEvent } from '../types';

export interface AnimalModelId {
  /** Model profile name (e.g. "gemini-flash"). */
  profile: string;
  /** The profile's color, when the profiles list knows it. */
  color?: string;
}

function isAnimalLlmCall(e: WorldEvent): boolean {
  return e.kind === 'llm_call' && e.actor_type === 'animal' && !!e.actor_id;
}

function profileOfLlmCall(e: WorldEvent): string | null {
  if (typeof e.profile === 'string' && e.profile.length > 0) return e.profile;
  const req = e.payload?.['gen_ai.request.model'];
  return typeof req === 'string' && req.length > 0 ? req : null;
}

/**
 * animalId → the model identity it last consulted, from the LATEST animal
 * llm_call per animal. `events` newest-first (the standard history order);
 * the scan early-exits once every living animal is resolved.
 */
export function animalModelMap(
  events: WorldEvent[],
  animals: Animal[],
  profiles: ModelProfile[],
): Map<string, AnimalModelId> {
  const out = new Map<string, AnimalModelId>();
  if (animals.length === 0) return out;
  const wanted = new Set(animals.map((a) => a.id));
  const colorByProfile = new Map(profiles.map((p) => [p.name, p.color]));
  for (const e of events) {
    if (!isAnimalLlmCall(e)) continue;
    const id = e.actor_id as string;
    if (!wanted.has(id) || out.has(id)) continue;
    const profile = profileOfLlmCall(e);
    if (!profile) continue;
    out.set(id, { profile, color: colorByProfile.get(profile) });
    if (out.size === wanted.size) break;
  }
  return out;
}

/** turn_ids of animal LLM decisions present in `events` (any order). */
export function llmDecidedAnimalTurns(events: WorldEvent[]): Set<string> {
  const out = new Set<string>();
  for (const e of events) {
    if (isAnimalLlmCall(e) && e.turn_id) out.add(e.turn_id);
  }
  return out;
}

/** True when this animal_action was an LLM decision (shares an animal
 *  llm_call's turn_id). Reflex actions (and missing data) return false. */
export function isLlmDecidedAction(e: WorldEvent, llmTurns: Set<string>): boolean {
  return e.kind === 'animal_action' && !!e.turn_id && llmTurns.has(e.turn_id);
}
