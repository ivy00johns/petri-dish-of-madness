/**
 * storylines (EM-312) — the ZERO-LLM deterministic drama scorer behind the
 * Storylines Rail. A pure selector over the rolling event history + the latest
 * world_state projection; it promotes recurring pairs and single-agent power
 * plays into NAMED, persistent threads (RIVALRY / REDEMPTION / POWER GRAB) and
 * assembles each thread's "story so far" VERBATIM from the event log.
 *
 * This is VIEWER/FEED chrome only. It never mutates sim state, never calls an
 * LLM, and (like storySoFar.ts) recomputes live from what already exists — so
 * it stays strictly OFF the replay surface with zero sim feedback.
 *
 * ── The generic container ──────────────────────────────────────────────────
 * A `Storyline` is deliberately kind-agnostic: an open `kind` + a stable
 * container `id` + `principals` + verbatim `beats`. v1 ships three detectors
 * (dyad rivalry/redemption, single-agent power-grab). EM-259's organized-war
 * lane later slots in as one more detector that mints `kind:'WAR'` storylines
 * from world.wars into this SAME container/rail — NOT a parallel one-off (see
 * the war seam note on `scoreStorylines`).
 *
 * ── Anti-spam ──────────────────────────────────────────────────────────────
 * Two independent guards keep the rail from flapping on comic false positives:
 *   1. A RECURRENCE gate — a thread needs ≥ MIN_EVENTS qualifying events across
 *      ≥ MIN_TICKS distinct ticks before it can exist at all.
 *   2. HYSTERESIS + a hard CAP — `applyHysteresis` promotes a NEW thread only
 *      at `promote`, but keeps an already-active one until it decays below the
 *      lower `demote`, then caps the visible set. The two thresholds stop a
 *      thread hovering at the line from blinking in and out.
 */

import type { WorldEvent, WorldState } from '../types';

// ── The container type ────────────────────────────────────────────────────

/** Named thread archetype. Open union — WAR (EM-259) and future kinds slot in. */
export type StorylineKind = 'RIVALRY' | 'REDEMPTION' | 'POWER_GRAB' | (string & {});

/** One verbatim beat lifted straight from the event log — never paraphrased. */
export interface StorylineBeat {
  seq: number;
  tick: number;
  /** The event's own `text`, verbatim (fallback: a bracketed kind). */
  text: string;
  kind: string;
}

/** A promoted, named, persistent thread — the generic rail container. */
export interface Storyline {
  /**
   * STABLE container key, independent of the current `kind`, so a pair that
   * evolves RIVALRY → REDEMPTION stays ONE thread (and hysteresis/selection
   * track it across the arc). `dyad:a~b` (sorted ids) / `grab:actor`.
   */
  id: string;
  kind: StorylineKind;
  /** Display title, e.g. "Ada v. Vesper II" / "Ada & Vesper II" / "Mara's Power Grab". */
  title: string;
  /** Escalation register for the status chip, e.g. TENSION / FEUD / RECONCILED. */
  status: string;
  /** Cumulative drama weight — ranking + promote/demote input. */
  score: number;
  /** Agent ids driving the thread (feed filter + 3-D tether endpoints). */
  principals: string[];
  /** Resolved display names, index-aligned with `principals`. */
  principalNames: string[];
  /** Verbatim beats, NEWEST-FIRST, capped at BEATS_CAP. */
  beats: StorylineBeat[];
  /** Recency + span (ticks). */
  firstTick: number;
  lastTick: number;
}

// ── Tunables (documented; determinism-safe — pure functions of the log) ─────

/** A thread needs at least this many qualifying events to exist. */
export const MIN_EVENTS = 3;
/** …spread across at least this many distinct ticks (kills one-tick bursts). */
export const MIN_TICKS = 2;
/** Score a NEW thread must reach to be promoted onto the rail. */
export const PROMOTE_SCORE = 6;
/** Score an ALREADY-ACTIVE thread may decay to before it drops (hysteresis). */
export const DEMOTE_SCORE = 4;
/** Hard cap on visible threads (the rail never becomes a wall). */
export const MAX_STORYLINES = 5;
/** Verbatim beats kept per thread. */
export const BEATS_CAP = 6;
/** A RIVALRY at or above this heat reads FEUD rather than TENSION. */
export const FEUD_BAND = 12;
/** A POWER GRAB at or above this reads ASCENDANT rather than MANEUVERING. */
export const ASCENDANT_BAND = 9;

/** Hostile relationship registers (relationship_changed → to_type). */
const HOSTILE_RELATIONS = new Set(['rival', 'enemy', 'feud']);
/** Warm relationship registers. */
const WARM_RELATIONS = new Set(['ally', 'friend', 'partner', 'family', 'mentor']);

/**
 * Hostile dyad kinds → weight. `conflict`/`crime_committed` can target a
 * BUILDING; those are filtered out by the both-endpoints-are-agents guard, so
 * only agent-on-agent instances score here.
 */
const HOSTILE_DYAD_WEIGHT: Record<string, number> = {
  conflict: 3,
  crime_committed: 3,
  accusation: 2,
  detained: 3,
  jailed: 3,
};

/** Warm dyad kinds → weight. `released` is the mercy beat a redemption turns on. */
const WARM_DYAD_WEIGHT: Record<string, number> = {
  cooperation_formed: 2,
  co_built: 2,
  recruited: 1,
  released: 1,
};

/**
 * Single-agent power-consolidation kinds → weight. `rule_proposed` alone is
 * routine civic chatter (weight 1); real consolidation (a faction, a
 * settlement, a master plan, a recruit) is what pushes an actor over PROMOTE.
 */
const GRAB_WEIGHT: Record<string, number> = {
  rule_proposed: 1,
  constitution_amended: 3,
  faction_formed: 3,
  settlement_founded: 3,
  master_plan_adopted: 3,
  recruited: 2,
};

// ── Internal accumulators ──────────────────────────────────────────────────

interface PairAcc {
  a: string;
  b: string;
  hostile: number;
  warm: number;
  ticks: Set<number>;
  firstTick: number;
  lastTick: number;
  /** Chronology of hostile/warm turns (tick-ordered) for the arc detector. */
  hostileTicks: number[];
  warmTicks: number[];
  /** All qualifying beats (hostile + warm), collected then sorted newest-first. */
  beats: StorylineBeat[];
}

interface GrabAcc {
  actor: string;
  score: number;
  ticks: Set<number>;
  firstTick: number;
  lastTick: number;
  /** Distinct secondary agents pulled in (recruited targets) for filter/tether. */
  allies: string[];
  beats: StorylineBeat[];
}

/** Sorted, `~`-joined key for an unordered agent pair (stable container id). */
function pairKey(x: string, y: string): { key: string; a: string; b: string } {
  const [a, b] = x < y ? [x, y] : [y, x];
  return { key: `${a}~${b}`, a, b };
}

function beatOf(e: WorldEvent): StorylineBeat {
  return {
    seq: e.seq,
    tick: e.tick,
    text: (e.text && e.text.trim()) ? e.text : `[${e.kind}]`,
    kind: e.kind,
  };
}

/**
 * Build the set of known AGENT ids — world.agents (living AND dead) plus any
 * history actor explicitly typed `actor_type:"human_agent"`. Used to reject
 * events whose target is a building/place, so a dyad is only ever agent-on-agent.
 */
function agentIdSet(history: WorldEvent[], world: WorldState | null): Set<string> {
  const ids = new Set<string>();
  for (const a of world?.agents ?? []) ids.add(a.id);
  for (const e of history) {
    if (e.actor_type === 'human_agent' && e.actor_id) ids.add(e.actor_id);
  }
  return ids;
}

// ── Scoring ────────────────────────────────────────────────────────────────

/**
 * Score the log into candidate storylines. Returns every candidate that clears
 * the RECURRENCE gate and floors at DEMOTE_SCORE (hysteresis then decides which
 * are actually promoted). Pure + deterministic: same (history, world) ⇒ byte-
 * identical output, regardless of the input order.
 *
 * ── War seam (EM-259) ──
 * The organized-war lane slots in HERE as one more detector: read world.wars /
 * world.grievances, mint `kind:'WAR'` Storylines (id `war:{warId}`, principals
 * = belligerent faction members, beats = the verbatim war_* lines), and append
 * them to `candidates` before the return. No rail/hysteresis change needed —
 * the container already carries an open `kind`.
 */
export function scoreStorylines(
  history: WorldEvent[],
  world: WorldState | null,
): Storyline[] {
  const agentIds = agentIdSet(history, world);
  const nameById = new Map<string, string>();
  for (const a of world?.agents ?? []) nameById.set(a.id, a.name);
  const nameOf = (id: string) => nameById.get(id) ?? id;

  const pairs = new Map<string, PairAcc>();
  const grabs = new Map<string, GrabAcc>();

  // Single O(n) pass, order-independent: every accumulator is commutative
  // (sums, set adds, min/max tick extremes), and beats are seq-sorted below —
  // so no upfront sort is needed (the input arrives newest-first). This keeps
  // the live cost on par with the StorySoFar scan at the 50k-event ceiling.
  for (const e of history) {
    const actor = e.actor_id ?? null;

    // ── Dyad drama (both endpoints must be agents) ──
    const target = e.target_id ?? null;
    if (actor && target && actor !== target && agentIds.has(actor) && agentIds.has(target)) {
      let hostileW = HOSTILE_DYAD_WEIGHT[e.kind] ?? 0;
      let warmW = WARM_DYAD_WEIGHT[e.kind] ?? 0;
      if (e.kind === 'relationship_changed') {
        const to = typeof e.payload?.to_type === 'string' ? e.payload.to_type : '';
        if (HOSTILE_RELATIONS.has(to)) hostileW = 2;
        else if (WARM_RELATIONS.has(to)) warmW = 2;
      }
      if (hostileW > 0 || warmW > 0) {
        const { key, a, b } = pairKey(actor, target);
        let acc = pairs.get(key);
        if (!acc) {
          acc = {
            a, b, hostile: 0, warm: 0, ticks: new Set(),
            firstTick: e.tick, lastTick: e.tick, hostileTicks: [], warmTicks: [], beats: [],
          };
          pairs.set(key, acc);
        }
        acc.hostile += hostileW;
        acc.warm += warmW;
        acc.ticks.add(e.tick);
        acc.firstTick = Math.min(acc.firstTick, e.tick);
        acc.lastTick = Math.max(acc.lastTick, e.tick);
        if (hostileW > 0) acc.hostileTicks.push(e.tick);
        if (warmW > 0) acc.warmTicks.push(e.tick);
        acc.beats.push(beatOf(e));
      }
    }

    // ── Power grab (single-actor consolidation) ──
    const grabW = actor && agentIds.has(actor) ? (GRAB_WEIGHT[e.kind] ?? 0) : 0;
    if (actor && grabW > 0) {
      let g = grabs.get(actor);
      if (!g) {
        g = { actor, score: 0, ticks: new Set(), firstTick: e.tick, lastTick: e.tick, allies: [], beats: [] };
        grabs.set(actor, g);
      }
      g.score += grabW;
      g.ticks.add(e.tick);
      g.firstTick = Math.min(g.firstTick, e.tick);
      g.lastTick = Math.max(g.lastTick, e.tick);
      if (target && agentIds.has(target) && target !== actor && !g.allies.includes(target)) {
        g.allies.push(target);
      }
      g.beats.push(beatOf(e));
    }
  }

  const out: Storyline[] = [];

  // ── Classify dyads → RIVALRY or REDEMPTION ──
  for (const [key, acc] of pairs) {
    if (acc.beats.length < MIN_EVENTS || acc.ticks.size < MIN_TICKS) continue;
    const score = acc.hostile + acc.warm;
    if (score < DEMOTE_SCORE) continue;

    // Redemption = real hostility EARLY, then a warm turn AFTER it, with the
    // most recent beat being warm (they are, right now, mending). Otherwise a
    // net-hostile recurring pair is a RIVALRY. A purely warm pair is a
    // friendship, not drama — it is not named.
    const firstHostile = acc.hostileTicks.length ? Math.min(...acc.hostileTicks) : Infinity;
    const lastWarm = acc.warmTicks.length ? Math.max(...acc.warmTicks) : -Infinity;
    const beatsNewestFirst = [...acc.beats].sort((x, y) => y.seq - x.seq).slice(0, BEATS_CAP);
    const latestIsWarm = acc.beats.length > 0 &&
      WARM_KIND(beatsNewestFirst[0].kind, beatsNewestFirst[0]);

    const names = [nameOf(acc.a), nameOf(acc.b)];
    const base = {
      id: `dyad:${key}`,
      score,
      principals: [acc.a, acc.b],
      principalNames: names,
      beats: beatsNewestFirst,
      firstTick: acc.firstTick,
      lastTick: acc.lastTick,
    };

    const isRedemption =
      acc.hostile >= 3 && acc.warm >= 2 && lastWarm > firstHostile && latestIsWarm;

    if (isRedemption) {
      out.push({
        ...base,
        kind: 'REDEMPTION',
        title: `${names[0]} & ${names[1]}`,
        status: acc.warm >= acc.hostile ? 'RECONCILED' : 'MENDING',
      });
    } else if (acc.hostile >= 3 && acc.hostile >= acc.warm) {
      out.push({
        ...base,
        kind: 'RIVALRY',
        title: `${names[0]} v. ${names[1]}`,
        status: score >= FEUD_BAND ? 'FEUD' : 'TENSION',
      });
    }
    // else: warm-dominant or too mild → not a named drama.
  }

  // ── Classify grabs → POWER_GRAB ──
  for (const [, g] of grabs) {
    if (g.beats.length < MIN_EVENTS || g.ticks.size < MIN_TICKS) continue;
    if (g.score < DEMOTE_SCORE) continue;
    const name = nameOf(g.actor);
    out.push({
      id: `grab:${g.actor}`,
      kind: 'POWER_GRAB',
      title: `${name}'s Power Grab`,
      status: g.score >= ASCENDANT_BAND ? 'ASCENDANT' : 'MANEUVERING',
      score: g.score,
      principals: [g.actor, ...g.allies.slice(0, 2)],
      principalNames: [name, ...g.allies.slice(0, 2).map(nameOf)],
      beats: [...g.beats].sort((x, y) => y.seq - x.seq).slice(0, BEATS_CAP),
      firstTick: g.firstTick,
      lastTick: g.lastTick,
    });
  }

  // Deterministic ranking: heat, then recency, then stable id.
  out.sort((x, y) =>
    y.score - x.score || y.lastTick - x.lastTick || (x.id < y.id ? -1 : x.id > y.id ? 1 : 0),
  );
  return out;
}

/** True when a beat's kind reads as a warm/mercy turn (redemption signal). */
function WARM_KIND(kind: string, beat: StorylineBeat): boolean {
  if (kind in WARM_DYAD_WEIGHT) return true;
  // relationship_changed beats don't carry to_type on the beat; treat the
  // generic bond-shift as warm ONLY when it isn't obviously hostile text.
  if (kind === 'relationship_changed') {
    const t = beat.text.toLowerCase();
    return !/(rival|enemy|feud|betray)/.test(t);
  }
  return false;
}

// ── Hysteresis + cap ───────────────────────────────────────────────────────

/**
 * Decide the visible, capped rail from freshly-scored `candidates` and the set
 * of ids that were active on the PREVIOUS pass. Real two-threshold hysteresis:
 *
 *   • a NEW thread (id ∉ prevActiveIds) must reach `promote` to appear;
 *   • an ALREADY-active thread stays until it decays below `demote`;
 *   • the survivors are capped to `cap` (already score-ranked upstream).
 *
 * Pure. The caller feeds `prevActiveIds` from a ref (display-only state — never
 * sim state), which is what makes the rail sticky instead of flickering.
 */
export function applyHysteresis(
  candidates: Storyline[],
  prevActiveIds: Set<string>,
  opts: { promote?: number; demote?: number; cap?: number } = {},
): Storyline[] {
  const promote = opts.promote ?? PROMOTE_SCORE;
  const demote = opts.demote ?? DEMOTE_SCORE;
  const cap = opts.cap ?? MAX_STORYLINES;
  const kept = candidates.filter((s) =>
    prevActiveIds.has(s.id) ? s.score >= demote : s.score >= promote,
  );
  return kept.slice(0, cap);
}
