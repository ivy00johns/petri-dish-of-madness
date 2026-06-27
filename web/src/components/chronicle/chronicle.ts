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
  /** Server-stamped chaos facts (EM-201 follow-on). Present only when the backend
   *  generated the chapter with chronicler_version >= 2 (or whichever version added
   *  the chaos stamp). When absent, ChaosPanel falls back to client chaosFacts(). */
  chaos?: ChaosFacts;
  /** CHRONICLER_VERSION at generation time, stamped server-side. */
  chroniclerVersion?: number;
  /** Actual model the proxy served (may differ from profile when the profile
   *  routes to an alias or fallback). */
  routedVia?: string;
  /** EM-225 — the chapter MODE. 'deepdive' marks a richer one-off saga built
   *  from a multi-pass per-dimension review → synthesis (POST /api/chronicle/
   *  deepdive); absent for ordinary single-pass chapters. */
  mode?: 'deepdive';
  /** EM-225 — per-dimension study notes the deep dive synthesised from
   *  (governance / chat / growth), stamped server-side. Present only on a
   *  deep-dive chapter. */
  dimensions?: Record<string, string>;
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
// parseChaosFacts — defensive deserialiser for server-stamped payload
// ============================================================

/** Parse a raw payload.chaos object into a well-typed ChaosFacts, tolerating
 *  missing or wrongly-typed fields (future-proofs against partial stamps). */
function parseChaosFacts(raw: Record<string, unknown>): ChaosFacts {
  const toStrArray = (v: unknown, cap: number): string[] => {
    if (!Array.isArray(v)) return [];
    return (v as unknown[])
      .filter((x): x is string => typeof x === 'string')
      .slice(0, cap);
  };

  const rawQuotes = Array.isArray(raw['quotes']) ? (raw['quotes'] as unknown[]) : [];
  const quotes = rawQuotes
    .filter(
      (q): q is { speaker: string; said: string } =>
        q !== null &&
        typeof q === 'object' &&
        typeof (q as Record<string, unknown>)['speaker'] === 'string' &&
        typeof (q as Record<string, unknown>)['said'] === 'string',
    )
    .slice(0, 3)
    .map((q) => ({ speaker: q.speaker, said: q.said }));

  const rawCounts =
    raw['counts'] && typeof raw['counts'] === 'object'
      ? (raw['counts'] as Record<string, unknown>)
      : {};
  const toInt = (v: unknown): number =>
    typeof v === 'number' ? Math.floor(v) : 0;

  return {
    cast: toStrArray(raw['cast'], 8),
    quotes,
    laws: toStrArray(raw['laws'], 5),
    conflicts: toStrArray(raw['conflicts'], 5),
    deaths: toStrArray(raw['deaths'], 5),
    counts: {
      spoken: toInt(rawCounts['spoken']),
      laws: toInt(rawCounts['laws']),
      clashes: toInt(rawCounts['clashes']),
      deaths: toInt(rawCounts['deaths']),
    },
  };
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
    .map((e) => {
      const rawChaos = e.payload?.['chaos'];
      const chaos: ChaosFacts | undefined =
        rawChaos && typeof rawChaos === 'object'
          ? parseChaosFacts(rawChaos as Record<string, unknown>)
          : undefined;
      const chroniclerVersion =
        typeof e.payload?.['chronicler_version'] === 'number'
          ? (e.payload['chronicler_version'] as number)
          : undefined;
      const routedVia =
        typeof e.payload?.['routed_via'] === 'string'
          ? (e.payload['routed_via'] as string)
          : undefined;
      // EM-225 — a deep-dive chapter is marked mode="deepdive" and carries the
      // per-dimension notes it was synthesised from.
      const mode =
        e.payload?.['mode'] === 'deepdive' ? ('deepdive' as const) : undefined;
      const rawDims = e.payload?.['dimensions'];
      const dimensions =
        rawDims && typeof rawDims === 'object' && !Array.isArray(rawDims)
          ? Object.fromEntries(
              Object.entries(rawDims as Record<string, unknown>).filter(
                (entry): entry is [string, string] => typeof entry[1] === 'string',
              ),
            )
          : undefined;
      return {
        seq: typeof e.seq === 'number' ? e.seq : 0,
        text: (e.text || '').trim(),
        fromTick: Number(e.payload?.['from_tick'] ?? e.tick ?? 0),
        toTick: Number(e.payload?.['to_tick'] ?? e.tick ?? 0),
        profile: typeof e.profile === 'string' ? e.profile : undefined,
        chaos,
        chroniclerVersion,
        routedVia,
        mode,
        dimensions,
      };
    });

  // Dedupe by (mode, fromTick, toTick) keeping the HIGHEST-seq version of each
  // window. Order-INDEPENDENT (not array position): a re-narrated chapter is
  // emitted later → higher seq → wins, even though the live runtime history
  // arrives newest-first (useSimulation prepends + sorts seq desc). This is what
  // makes the `rebuild` re-narrate actually replace the old chapter in the live
  // UI. EM-225 — the mode is part of the key so a whole-run DEEP DIVE coexists
  // with an ordinary chapter that happens to share its tick window.
  const windowMap = new Map<string, typeof summaries[number]>();
  for (const s of summaries) {
    const key = `${s.mode ?? ''}:${s.fromTick}:${s.toTick}`;
    const existing = windowMap.get(key);
    if (!existing || s.seq >= existing.seq) windowMap.set(key, s);
  }

  return Array.from(windowMap.values())
    .map((s): Chapter => ({
      text: s.text,
      fromTick: s.fromTick,
      toTick: s.toTick,
      profile: s.profile,
      chaos: s.chaos,
      chroniclerVersion: s.chroniclerVersion,
      routedVia: s.routedVia,
      mode: s.mode,
      dimensions: s.dimensions,
      title: chapterTitle(s.text),
    }))
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
