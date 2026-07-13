/**
 * dramaWire (EM-316) — the Drama Wire salience scorer.
 *
 * A pure, DETERMINISTIC selector over the rolling event history (the same
 * newest-first `useSimulation.history` window `storySoFar` reads). It projects
 * the typed event stream into a live Drama Index and a rate-capped set of
 * "breaking" beats — nothing here mutates sim state, issues a request, or is
 * fed back into the world. It is a DERIVED VIEW ONLY: byte-identical replay is
 * untouched (viewer-layer, no golden — see the 2026-07-11 expansion-ideas
 * constraint sweep, "Determinism / byte-identical replay").
 *
 * Shared infra: this scorer is deliberately UI-free so other consumers (the
 * Storylines Rail EM-312, Moment Cam shot triggers) can score the SAME beats
 * from the SAME weights. Keep it a pure function of (history[, world]).
 */

import type { WorldEvent, WorldState, FocusTarget } from '../types';

/**
 * Base salience weight per typed event kind (0 / absent ⇒ not a drama beat).
 * Values are a deliberate taste pass (the risk the pitch flags): deaths and
 * declared war top the scale; a resolved vote and a crime sit mid; a rift or a
 * new faction just clears the bar. Tuned so the DEFAULT threshold (30) admits
 * genuine beats and drops routine chatter.
 */
export const DRAMA_SALIENCE: Record<string, number> = {
  world_extinct: 100,
  war_declared: 90,
  exiled: 85,
  war_exhausted: 75,
  agent_died: 70,
  peace_signed: 65,
  war_siege: 60,
  war_clash: 55,
  conflict: 50, // crime (EM-240 harm surface)
  rule_passed: 45, // a verdict / vote resolving in favor
  commitment_lapsed: 40, // only when phantom (a betrayed vow) — see scoreEvent
  rule_rejected: 40,
  relationship_changed: 35, // only a rift (→ feud/enemy) — see scoreEvent
  faction_dissolved: 35,
  faction_formed: 30,
};

/** Red BREAKING register (uppercase) per kind. */
export const DRAMA_LABEL: Record<string, string> = {
  world_extinct: 'EXTINCTION',
  war_declared: 'WAR',
  exiled: 'EXILE',
  war_exhausted: 'WAR ENDS',
  agent_died: 'DEATH',
  peace_signed: 'PEACE',
  war_siege: 'SIEGE',
  war_clash: 'CLASH',
  conflict: 'CRIME',
  rule_passed: 'VERDICT',
  commitment_lapsed: 'BROKEN VOW',
  rule_rejected: 'REJECTED',
  relationship_changed: 'RIFT',
  faction_dissolved: 'FACTION',
  faction_formed: 'FACTION',
};

/** Default tuning. Exported so consumers (and tests) can override explicitly. */
export const DRAMA_DEFAULTS = {
  /** Minimum salience for a beat to be a candidate at all. */
  threshold: 30,
  /**
   * Minimum sim-tick gap between two SURFACED breaking cards. Caps the rate so
   * a burst of same-tick war clashes never crowds raw agent chat (the feed-wins
   * rule cuts both ways — the pitch's headline risk).
   */
  minTickGap: 3,
  /** Hard cap on surfaced breaking cards. */
  maxCards: 3,
  /** Per-tick decay applied to a beat's contribution to the live Drama Index. */
  decay: 0.85,
  /** Sparkline resolution (buckets across the visible tick span). */
  sparkBuckets: 28,
} as const;

export interface DramaBeat {
  /** Stable identity (event seq) — safe React key + dedupe. */
  seq: number;
  tick: number;
  kind: string;
  /** Salience (post-modifier) — drives ordering + the header index. */
  score: number;
  /** Red uppercase register, e.g. "VERDICT". */
  label: string;
  /** The templated $0 headline (the event's own line, else a kind fallback). */
  headline: string;
  actorId: string | null;
  targetId: string | null;
  /** A building the beat centers on (war_siege), when the payload names one. */
  buildingId: string | null;
}

/** Read a string payload key defensively (payloads are Record<string,unknown>). */
function payloadStr(e: WorldEvent, key: string): string | null {
  const v = e.payload?.[key];
  return typeof v === 'string' && v.trim() ? v : null;
}

/**
 * The salience of a single event, AFTER kind-specific modifiers. Returns 0 for
 * anything that is not a drama beat (routine chatter, a mundane lapse, a
 * friendly bond shift, a renewed law). Pure — no world, no time.
 */
export function scoreEvent(e: WorldEvent): number {
  const base = DRAMA_SALIENCE[e.kind] ?? 0;
  if (base === 0) return 0;

  switch (e.kind) {
    case 'commitment_lapsed':
      // Only a PHANTOM lapse is a betrayed vow (claimed aloud, never enacted);
      // an ordinary expiry is not news.
      return e.payload?.reason === 'phantom' ? base : 0;
    case 'relationship_changed': {
      // Only a slide INTO conflict (feud/enemy) is a rift worth breaking.
      const to = payloadStr(e, 'to_type');
      return to === 'feud' || to === 'enemy' ? base : 0;
    }
    case 'rule_passed':
      // A renewal of an already-active law is not a fresh verdict.
      return e.payload?.renewed === true ? 0 : base;
    default:
      return base;
  }
}

/** Build a beat from a pre-scored event. */
function toBeat(e: WorldEvent, score: number): DramaBeat {
  const headline =
    (e.text && e.text.trim()) || `[${e.kind}]`;
  return {
    seq: e.seq,
    tick: e.tick,
    kind: e.kind,
    score,
    label: DRAMA_LABEL[e.kind] ?? 'BREAKING',
    headline: headline.trim(),
    actorId: e.actor_id ?? null,
    targetId: e.target_id ?? null,
    buildingId: payloadStr(e, 'building_id'),
  };
}

export interface DramaBeatsOptions {
  threshold?: number;
  minTickGap?: number;
  maxCards?: number;
}

/**
 * The rate-capped breaking beats, NEWEST-FIRST. From the scored candidates
 * (score ≥ threshold) we greedily surface the newest, then skip any beat within
 * `minTickGap` ticks of the last surfaced one (so a same-tick or near-tick burst
 * collapses to a single card), up to `maxCards`. Deterministic: a pure function
 * of the history window + the (fixed) tuning.
 *
 * `history` is the standard newest-first window; the function re-sorts by seq
 * defensively so callers can pass any order.
 */
export function dramaBeats(
  history: WorldEvent[],
  opts: DramaBeatsOptions = {},
): DramaBeat[] {
  const threshold = opts.threshold ?? DRAMA_DEFAULTS.threshold;
  const minTickGap = opts.minTickGap ?? DRAMA_DEFAULTS.minTickGap;
  const maxCards = opts.maxCards ?? DRAMA_DEFAULTS.maxCards;

  const scored: DramaBeat[] = [];
  for (const e of history) {
    const s = scoreEvent(e);
    if (s >= threshold) scored.push(toBeat(e, s));
  }
  // Newest-first by seq (client-synthesized events can carry negative seqs, so
  // a numeric sort on seq is the stable identity order).
  scored.sort((a, b) => b.seq - a.seq);

  const out: DramaBeat[] = [];
  for (const b of scored) {
    if (out.length >= maxCards) break;
    const last = out[out.length - 1];
    // last.tick ≥ b.tick (newest-first) — skip anything too close in sim-time.
    if (last && last.tick - b.tick < minTickGap) continue;
    out.push(b);
  }
  return out;
}

/**
 * The live Drama Index (0..100): every scored beat contributes its salience
 * decayed by its age in ticks relative to the newest event in the window, then
 * clamped. A quiet town reads ~0; a fresh death/verdict spikes it. Deterministic.
 */
export function dramaIndex(
  history: WorldEvent[],
  decay: number = DRAMA_DEFAULTS.decay,
): number {
  if (history.length === 0) return 0;
  let now = -Infinity;
  for (const e of history) if (e.tick > now) now = e.tick;
  let acc = 0;
  for (const e of history) {
    const s = scoreEvent(e);
    if (s <= 0) continue;
    const age = Math.max(0, now - e.tick);
    acc += s * Math.pow(decay, age);
  }
  return Math.min(100, Math.round(acc));
}

/**
 * A deterministic sparkline series (length `buckets`) of drama heat across the
 * visible tick span — oldest bucket left, newest right. Each scored beat lands
 * in the bucket for its tick; empty history reads flat. Presentation-only.
 */
export function dramaSparkline(
  history: WorldEvent[],
  buckets: number = DRAMA_DEFAULTS.sparkBuckets,
): number[] {
  const arr = new Array<number>(Math.max(1, buckets)).fill(0);
  if (history.length === 0) return arr;
  let minT = Infinity;
  let maxT = -Infinity;
  for (const e of history) {
    if (e.tick < minT) minT = e.tick;
    if (e.tick > maxT) maxT = e.tick;
  }
  const span = Math.max(1, maxT - minT);
  for (const e of history) {
    const s = scoreEvent(e);
    if (s <= 0) continue;
    const idx = Math.min(
      arr.length - 1,
      Math.max(0, Math.floor(((e.tick - minT) / span) * arr.length)),
    );
    arr[idx] += s;
  }
  return arr;
}

/**
 * Resolve where the camera should fly for a beat, using the current world to
 * turn actor/target ids into a PLACE the shipped zoom-to-place controls
 * understand (EM-095: a `place` focus id may be a Place OR a Building id — the
 * CozyWorld resolver checks both). Preference: a named building (siege) → the
 * actor's current location → the target's location. Returns null when nothing
 * resolves (the card still renders; the fly-to is simply disabled).
 *
 * Pure: reads the world snapshot, never writes it — ZERO sim feedback.
 */
export function beatFocus(
  beat: DramaBeat,
  world: WorldState | null,
): FocusTarget | null {
  if (!world) return null;
  if (beat.buildingId && (world.buildings ?? []).some((b) => b.id === beat.buildingId)) {
    return { type: 'place', id: beat.buildingId };
  }
  const agents = world.agents ?? [];
  const actor = beat.actorId ? agents.find((a) => a.id === beat.actorId) : undefined;
  if (actor?.location) return { type: 'place', id: actor.location };
  const target = beat.targetId ? agents.find((a) => a.id === beat.targetId) : undefined;
  if (target?.location) return { type: 'place', id: target.location };
  return null;
}

/**
 * VITE_DRAMA_WIRE — the feature flag. DEFAULT OFF: absent/empty ⇒ the whole
 * Drama Wire renders nothing and the feed is byte-identical to today. Set to
 * "1" / "true" / "on" (case-insensitive) to enable. Evaluated at call-time (not
 * module-init) so vi.stubEnv works in tests — mirrors Header's VITE_COFFEE_BUTTON.
 */
export function isDramaWireEnabled(): boolean {
  const v = import.meta.env.VITE_DRAMA_WIRE;
  if (v === undefined || v === null) return false;
  return ['1', 'true', 'on'].includes(String(v).toLowerCase());
}
