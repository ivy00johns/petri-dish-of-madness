/**
 * chronicle.ts (EM-201) — pure helpers for the Chronicle reading room.
 * No React, no side effects — all functions are pure projections over WorldEvent[].
 */
import type { WorldEvent } from '../../types';

// ============================================================
// Interfaces
// ============================================================

export interface Chapter {
  text: string;
  fromTick: number;
  toTick: number;
  profile?: string;
  title: string;
}

export interface ChaosFacts {
  cast: string[];
  quotes: { speaker: string; said: string }[];
  laws: string[];
  conflicts: string[];
  deaths: string[];
  counts: { spoken: number; laws: number; clashes: number; deaths: number };
}

// ============================================================
// toRoman
// ============================================================

const ROMAN_MAP: [number, string][] = [
  [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'],
  [100, 'C'],  [90, 'XC'],  [50, 'L'],  [40, 'XL'],
  [10, 'X'],   [9, 'IX'],   [5, 'V'],   [4, 'IV'],
  [1, 'I'],
];

/** Convert a positive integer to standard roman numerals. n<=0 or non-finite → String(n). */
export function toRoman(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return String(n);
  let result = '';
  let remaining = Math.floor(n);
  for (const [value, numeral] of ROMAN_MAP) {
    while (remaining >= value) {
      result += numeral;
      remaining -= value;
    }
  }
  return result;
}

// ============================================================
// chapterTitle
// ============================================================

/** Derive a short display title from the first sentence of chapter text. */
export function chapterTitle(text: string): string {
  if (!text || !text.trim()) return 'Untitled';

  // Collapse whitespace
  const collapsed = text.replace(/\s+/g, ' ').trim();

  // Take up to the first sentence boundary (. ! ?)
  const sentenceMatch = collapsed.match(/^([^.!?]+[.!?])/);
  const sentence = sentenceMatch ? sentenceMatch[1] : collapsed;

  // Take first ~8 words
  const words = sentence.trim().split(/\s+/);
  const truncated = words.length > 8;
  const titleWords = truncated ? words.slice(0, 8) : words;

  // Build the title
  let title = titleWords.join(' ');

  // Strip trailing punctuation
  title = title.replace(/[.!?,;:]+$/, '');

  // Append ellipsis if truncated
  if (truncated) title += '…';

  // Capitalize first letter
  if (title.length > 0) {
    title = title.charAt(0).toUpperCase() + title.slice(1);
  }

  return title || 'Untitled';
}

// ============================================================
// readChapters
// ============================================================

/**
 * Gather narrator_summary chapters from the event history, oldest → newest.
 * DEDUPLICATES by (fromTick, toTick) window keeping the LAST occurrence in
 * history order — fixes the resume-fork bug that generated the same window twice.
 */
export function readChapters(history: WorldEvent[]): Chapter[] {
  const summaries = history
    .filter((e) => e.kind === 'narrator_summary' && Boolean((e.text || '').trim()))
    .map((e) => ({
      text: (e.text || '').trim(),
      fromTick: Number(e.payload?.['from_tick'] ?? e.tick ?? 0),
      toTick: Number(e.payload?.['to_tick'] ?? e.tick ?? 0),
      profile: typeof e.profile === 'string' ? e.profile : undefined,
    }));

  // Dedupe by (fromTick, toTick) keeping the LAST occurrence
  const windowMap = new Map<string, typeof summaries[number]>();
  for (const s of summaries) {
    const key = `${s.fromTick}:${s.toTick}`;
    windowMap.set(key, s); // last write wins
  }

  return Array.from(windowMap.values())
    .map((s) => ({ ...s, title: chapterTitle(s.text) }))
    .sort((a, b) => a.toTick - b.toTick || a.fromTick - b.fromTick);
}

// ============================================================
// chaosFacts
// ============================================================

/**
 * Extract the speaker name from an agent_speech event.
 * Tries: leading text before a speech verb in ev.text, then ev.actor_id, else "—".
 */
function speakerOf(ev: WorldEvent): string {
  if (ev.text) {
    const match = ev.text.match(/^([A-Za-z][A-Za-z '-]*?)\s+(?:says|mutters|shouts|whispers|proclaims|insults|declares|asks|muses|snaps|warns|grumbles|sighs|laughs)\b/i);
    if (match) return match[1].trim();
  }
  if (ev.actor_id) return ev.actor_id;
  return '—';
}

/**
 * Extract the said content from an agent_speech event.
 * Tries payload.said first, then strips the leading "Name verb" prefix off text.
 */
function saidOf(ev: WorldEvent): string {
  if (ev.payload?.['said'] && typeof ev.payload['said'] === 'string') {
    return (ev.payload['said'] as string).trim();
  }
  if (ev.text) {
    // Strip leading "Name says/mutters/... " pattern
    const stripped = ev.text.replace(
      /^[A-Za-z][A-Za-z '-]*?\s+(?:says|mutters|shouts|whispers|proclaims|insults|declares|asks|muses|snaps|warns|grumbles|sighs|laughs)[,:]?\s*/i,
      '',
    );
    return stripped.trim();
  }
  return '';
}

/**
 * Reconstruct chaos facts from events within the [fromTick, toTick] window
 * of the active chapter.
 */
export function chaosFacts(
  history: WorldEvent[],
  fromTick: number,
  toTick: number,
): ChaosFacts {
  const inWindow = history.filter((e) => e.tick >= fromTick && e.tick <= toTick);

  // Speech events
  const speechEvents = inWindow.filter((e) => e.kind === 'agent_speech');

  // Laws / namings
  const lawEvents = inWindow.filter(
    (e) => e.kind === 'rule_passed' || e.kind === 'town_named',
  );

  // Conflict events
  const conflictEvents = inWindow.filter(
    (e) => e.kind === 'conflict' || e.kind === 'commitment_lapsed',
  );

  // Death events
  const deathEvents = inWindow.filter((e) => e.kind === 'agent_died');

  // Cast: distinct speakers (cap 8)
  const speakerSet = new Set<string>();
  for (const e of speechEvents) {
    speakerSet.add(speakerOf(e));
  }
  const cast = Array.from(speakerSet).slice(0, 8);

  // Quotes: top 3 longest
  const allQuotes = speechEvents.map((e) => ({
    speaker: speakerOf(e),
    said: saidOf(e),
  })).filter((q) => q.said.length > 0);
  allQuotes.sort((a, b) => b.said.length - a.said.length);
  const quotes = allQuotes.slice(0, 3);

  // Laws (cap 5)
  const laws = lawEvents
    .map((e) => (e.text || '').trim())
    .filter(Boolean)
    .slice(0, 5);

  // Conflicts (cap 5)
  const conflicts = conflictEvents
    .map((e) => (e.text || '').trim())
    .filter(Boolean)
    .slice(0, 5);

  // Deaths (cap 5)
  const deaths = deathEvents
    .map((e) => (e.text || '').trim())
    .filter(Boolean)
    .slice(0, 5);

  return {
    cast,
    quotes,
    laws,
    conflicts,
    deaths,
    counts: {
      spoken: speechEvents.length,
      laws: lawEvents.length,
      clashes: conflictEvents.length,
      deaths: deathEvents.length,
    },
  };
}
