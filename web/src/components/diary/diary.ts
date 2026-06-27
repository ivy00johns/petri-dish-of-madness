/**
 * diary.ts (EM-215) — the per-agent inner-life grouping logic.
 *
 * The live feed already treats reflections as a Diary category (EventFeed
 * CATEGORIES `diary` = reflection + commitment_made + commitment_lapsed +
 * plan_revised). The dedicated DiaryView narrows that to the pure inner-life
 * channel — `reflection` events — and re-organises them by AUTHOR, the
 * individual cousin to the town Chronicle.
 *
 * History arrives newest-first from the simulation hook; a diary reads
 * oldest→newest, so each agent's entries are sorted ascending by (tick, seq).
 */
import type { WorldEvent } from '../../types';

/** A single diary line: an agent's `reflection` event, attribution intact. */
export interface DiaryEntry {
  seq: number;
  tick: number;
  text: string;
  /** The model that authored this reflection (event-stamped). */
  profile?: string | null;
  profile_color?: string | null;
  ts?: string;
}

/** One agent's diary: identity key + their reflections, chronological. */
export interface DiaryGroup {
  actorId: string;
  entries: DiaryEntry[];
}

/** The pure inner-life channel — only `reflection` events (cf. EM-215 §3). */
export function isDiaryReflection(e: WorldEvent): boolean {
  return e.kind === 'reflection' && !!e.actor_id;
}

/**
 * Group reflection events by author and order each agent's entries
 * chronologically (oldest→newest). Reflections with no `actor_id` cannot be
 * attributed to a diary and are dropped. Agent order is stable: first
 * appearance in the input scan.
 */
export function groupReflectionsByAgent(history: WorldEvent[]): DiaryGroup[] {
  const byActor = new Map<string, DiaryEntry[]>();

  for (const e of history) {
    if (!isDiaryReflection(e)) continue;
    const actorId = e.actor_id as string;
    // Prefer the payload body (the raw inner-life text) when present; fall back
    // to the rendered prose, then a placeholder so a row never renders blank.
    const payloadText =
      typeof e.payload?.text === 'string' ? (e.payload.text as string) : undefined;
    const text = (payloadText ?? e.text ?? '').trim() || '(wordless thought)';
    const entry: DiaryEntry = {
      seq: e.seq,
      tick: e.tick,
      text,
      profile: e.profile,
      profile_color: e.profile_color,
      ts: e.ts,
    };
    const list = byActor.get(actorId);
    if (list) list.push(entry);
    else byActor.set(actorId, [entry]);
  }

  const groups: DiaryGroup[] = [];
  for (const [actorId, entries] of byActor) {
    // Oldest→newest: ascending by tick, seq as the stable tiebreaker (the
    // simulation hands events back newest-first, so an in-place sort is needed).
    entries.sort((a, b) => (a.tick - b.tick) || (a.seq - b.seq));
    groups.push({ actorId, entries });
  }
  return groups;
}
