/**
 * The Blind Lineup (EM-309, Layer 1) — pure logic for the spectator
 * model-taste-test game mode.
 *
 * A "session mode" that hides every model chip behind ??? and turns model
 * identity into a guessing game: the viewer matches each colored slot to a
 * model family, then hits REVEAL and the chips flip to their real models while
 * a per-model-family accuracy scorecard grades the round.
 *
 * This module has ZERO sim coupling. It reads only the model-profile display
 * data the frontend already holds (world.profiles + agent.profile), derives a
 * coarse model FAMILY from a profile/model_id, and grades viewer guesses. The
 * whole game — guesses, reveal, the accumulated scorecard — lives entirely in
 * the browser (React state + localStorage) and NEVER touches the sim, the event
 * log, or the replay surface. It adds no agent-facing signal, so it can't leak
 * routing metadata into perception. See BlindLineupContext for the wiring.
 *
 * Flag: `blind_lineup.enabled`, surfaced to the build as the Vite env
 * `VITE_BLIND_LINEUP`. Default OFF (mirrors Header's VITE_COFFEE_BUTTON
 * call-time parse). When OFF the feature never mounts and the live view is
 * byte-identical to today.
 */

import type { Agent, ModelProfile, WorldState } from '../types';

/** The masked placeholder shown wherever a model name would appear while blind. */
export const MASK = '???';

/**
 * blind_lineup.enabled — read the Vite env VITE_BLIND_LINEUP. Default OFF.
 * Truthy values: "1" | "true" | "on" | "yes" (case-insensitive). Evaluated at
 * call-time (not module-init) so vi.stubEnv works in tests.
 */
export function blindLineupEnabled(): boolean {
  const v = import.meta.env.VITE_BLIND_LINEUP;
  if (v === undefined || v === null) return false;
  return ['1', 'true', 'on', 'yes'].includes(String(v).toLowerCase());
}

// ── Model-family derivation ───────────────────────────────────────────────────
// Matched against the lowercased "<model_id> <profile name>" haystack, most
// specific first. Unknown → 'other'. Deliberately coarse: the game asks "which
// FAMILY", not "which exact checkpoint", so llama-3.1 and llama-3.3 both read
// 'llama'. Keep patterns distinctive to avoid cross-family false hits.
const FAMILY_PATTERNS: Array<[RegExp, string]> = [
  [/\bllama\b|llama-?\d/, 'llama'],
  [/qwen/, 'qwen'],
  [/gemma/, 'gemma'],
  [/gemini/, 'gemini'],
  [/mixtral|mistral|ministral|codestral/, 'mistral'],
  [/claude|haiku|sonnet|opus/, 'claude'],
  [/deepseek/, 'deepseek'],
  [/command-?r|cohere/, 'command-r'],
  [/nemotron/, 'nemotron'],
  [/\bphi-?\d|\bphi\b/, 'phi'],
  [/\bgpt\b|gpt-?\d|openai\/gpt/, 'gpt'],
  [/grok/, 'grok'],
  [/\bglm\b|glm-?\d/, 'glm'],
  [/\byi-?\d|\byi\b/, 'yi'],
];

/**
 * Derive the coarse model family for a profile. Looks at model_id first (most
 * reliable) then the profile name. Never throws; unknown ⇒ 'other'.
 */
export function modelFamily(
  profile: { name?: string | null; model_id?: string | null },
): string {
  const hay = `${profile.model_id ?? ''} ${profile.name ?? ''}`.toLowerCase();
  for (const [re, fam] of FAMILY_PATTERNS) {
    if (re.test(hay)) return fam;
  }
  return 'other';
}

// ── The lineup ────────────────────────────────────────────────────────────────

/**
 * The set of profiles actually in play — one per distinct `agent.profile`,
 * resolved to its ModelProfile (for model_id + color) where possible, else
 * synthesized from the agent's own profile_color. Ordered by first appearance
 * so the "slots" are stable across renders within a round. Dead agents count:
 * the model they ran is still part of the lineup to guess.
 */
export function lineupProfiles(world: WorldState | null): ModelProfile[] {
  if (!world) return [];
  const byName = new Map<string, ModelProfile>();
  for (const p of world.profiles ?? []) byName.set(p.name, p);

  const out: ModelProfile[] = [];
  const seen = new Set<string>();
  for (const a of world.agents ?? []) {
    const name = a.profile;
    if (!name || seen.has(name)) continue;
    seen.add(name);
    const known = byName.get(name);
    if (known) {
      out.push(known);
    } else {
      // Synthesize a minimal profile from what the agent carries.
      out.push({
        name,
        adapter: 'unknown',
        model_id: name,
        color: (a as Agent).profile_color ?? '#888888',
      });
    }
  }
  return out;
}

/** Distinct model families present in the lineup, sorted — the guess options. */
export function lineupFamilies(profiles: ModelProfile[]): string[] {
  const s = new Set<string>();
  for (const p of profiles) s.add(modelFamily(p));
  return [...s].sort();
}

// ── Grading ───────────────────────────────────────────────────────────────────

export interface RowResult {
  profileName: string;
  actualFamily: string;
  guessedFamily: string | null;
  correct: boolean;
}

/**
 * Grade a round: for each lineup slot, compare the viewer's guessed family to
 * the slot's actual family. A slot with no guess is neither correct nor counted
 * toward accuracy (it just reads "no guess" on reveal).
 */
export function gradeRound(
  profiles: ModelProfile[],
  guesses: Record<string, string>,
): RowResult[] {
  return profiles.map((p) => {
    const actualFamily = modelFamily(p);
    const guessedFamily = guesses[p.name] ?? null;
    return {
      profileName: p.name,
      actualFamily,
      guessedFamily,
      correct: guessedFamily != null && guessedFamily === actualFamily,
    };
  });
}

/** Session tally: answered slots and how many matched. */
export function roundScore(results: RowResult[]): { correct: number; answered: number; total: number } {
  let correct = 0;
  let answered = 0;
  for (const r of results) {
    if (r.guessedFamily != null) answered += 1;
    if (r.correct) correct += 1;
  }
  return { correct, answered, total: results.length };
}

// ── The accumulated scorecard (localStorage; cross-session) ────────────────────
// Keyed by ACTUAL family: "when the model in this slot was really an llama, how
// often did you guess llama?" This is the free human-perception dataset the
// pitch calls out — which models are actually distinguishable from behavior.

export interface FamilyTally {
  seen: number;
  correct: number;
}
export type Scorecard = Record<string, FamilyTally>;

const SCORE_KEY = 'em.blindLineup.scorecard.v1';

export function loadScorecard(): Scorecard {
  try {
    const raw = localStorage.getItem(SCORE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return {};
    const out: Scorecard = {};
    for (const [fam, t] of Object.entries(parsed as Record<string, unknown>)) {
      if (t && typeof t === 'object') {
        const seen = Number((t as FamilyTally).seen);
        const correct = Number((t as FamilyTally).correct);
        if (Number.isFinite(seen) && Number.isFinite(correct)) {
          out[fam] = { seen: Math.max(0, seen), correct: Math.max(0, correct) };
        }
      }
    }
    return out;
  } catch {
    return {};
  }
}

export function saveScorecard(sc: Scorecard): void {
  try {
    localStorage.setItem(SCORE_KEY, JSON.stringify(sc));
  } catch {
    /* ignore — the game is chrome; storage failure must never break the view */
  }
}

/**
 * Fold a graded round into the running per-family scorecard (only answered
 * slots count). Pure: returns a new object, never mutates `prev`.
 */
export function accumulate(prev: Scorecard, results: RowResult[]): Scorecard {
  const next: Scorecard = {};
  for (const [k, v] of Object.entries(prev)) next[k] = { ...v };
  for (const r of results) {
    if (r.guessedFamily == null) continue; // unanswered slots don't count
    const fam = r.actualFamily;
    const t = next[fam] ?? { seen: 0, correct: 0 };
    next[fam] = { seen: t.seen + 1, correct: t.correct + (r.correct ? 1 : 0) };
  }
  return next;
}
