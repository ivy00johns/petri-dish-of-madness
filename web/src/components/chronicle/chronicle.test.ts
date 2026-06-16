/**
 * chronicle.test.ts — unit tests for every pure helper in chronicle.ts.
 * Tests: chapterTitle, toRoman, readChapters (incl. dedupe), chaosFacts.
 */
import { describe, expect, it } from 'vitest';
import { chaosFacts, chapterTitle, readChapters, toRoman } from './chronicle';
import { ev } from '../../test-utils/fixtures';

// ============================================================
// toRoman
// ============================================================
describe('toRoman', () => {
  it('converts basic numbers', () => {
    expect(toRoman(1)).toBe('I');
    expect(toRoman(4)).toBe('IV');
    expect(toRoman(9)).toBe('IX');
    expect(toRoman(14)).toBe('XIV');
    expect(toRoman(40)).toBe('XL');
    expect(toRoman(90)).toBe('XC');
    expect(toRoman(400)).toBe('CD');
    expect(toRoman(900)).toBe('CM');
    expect(toRoman(1994)).toBe('MCMXCIV');
    expect(toRoman(2024)).toBe('MMXXIV');
  });

  it('returns String(n) for n <= 0', () => {
    expect(toRoman(0)).toBe('0');
    expect(toRoman(-5)).toBe('-5');
  });

  it('returns String(n) for non-finite', () => {
    expect(toRoman(Infinity)).toBe('Infinity');
    expect(toRoman(NaN)).toBe('NaN');
  });
});

// ============================================================
// chapterTitle
// ============================================================
describe('chapterTitle', () => {
  it('takes first sentence, up to 8 words, strips trailing punctuation', () => {
    const text = 'The mayor declared war on the bakery. Nobody was surprised.';
    expect(chapterTitle(text)).toBe('The mayor declared war on the bakery');
  });

  it('appends ellipsis when sentence exceeds 8 words', () => {
    const text =
      'Once upon a time in a small dusty town the clocks all stopped at noon.';
    const result = chapterTitle(text);
    expect(result).toMatch(/…$/);
    expect(result.split(/\s+/).length).toBeLessThanOrEqual(9); // 8 words + ellipsis attached
  });

  it('capitalizes first letter', () => {
    expect(chapterTitle('the town breathed.')).toBe('The town breathed');
  });

  it('collapses whitespace', () => {
    const text = '  a  quiet  morning.   it rained.';
    expect(chapterTitle(text)).toBe('A quiet morning');
  });

  it('returns Untitled for empty/whitespace text', () => {
    expect(chapterTitle('')).toBe('Untitled');
    expect(chapterTitle('   ')).toBe('Untitled');
  });

  it('handles text with no sentence terminator', () => {
    const result = chapterTitle('A short phrase');
    expect(result).toBe('A short phrase');
  });
});

// ============================================================
// readChapters
// ============================================================
describe('readChapters', () => {
  it('gathers narrator_summary chapters in window order; skips non-chapters + empties', () => {
    const history = [
      ev({ kind: 'narrator_summary', text: 'Chapter two.', tick: 200,
           payload: { from_tick: 100, to_tick: 200 } }),
      ev({ kind: 'agent_speech', text: 'just chatter' }),
      ev({ kind: 'narrator_summary', text: '   ', tick: 50 }), // empty → skipped
      ev({ kind: 'narrator_summary', text: 'Chapter one.', tick: 100,
           payload: { from_tick: 0, to_tick: 100 } }),
    ];
    expect(readChapters(history).map((c) => c.text)).toEqual([
      'Chapter one.', 'Chapter two.',
    ]);
  });

  it('includes a derived title on each chapter', () => {
    const history = [
      ev({ kind: 'narrator_summary', text: 'The sun rose over the quiet hills.', tick: 100,
           payload: { from_tick: 0, to_tick: 100 } }),
    ];
    const [ch] = readChapters(history);
    expect(ch.title).toBeTruthy();
    expect(typeof ch.title).toBe('string');
    expect(ch.title).not.toBe('Untitled');
  });

  it('deduplicates by (fromTick, toTick) window, keeping the LAST occurrence', () => {
    // Simulates the resume-fork bug: same window 3700-3800 chronicled twice
    const history = [
      ev({ kind: 'narrator_summary', text: 'First attempt at 3700-3800.', tick: 3800,
           payload: { from_tick: 3700, to_tick: 3800 } }),
      ev({ kind: 'narrator_summary', text: 'Unique window 3800-3900.', tick: 3900,
           payload: { from_tick: 3800, to_tick: 3900 } }),
      // Same 3700-3800 window, arrives later in history — should win
      ev({ kind: 'narrator_summary', text: 'Better retelling of 3700-3800.', tick: 3850,
           payload: { from_tick: 3700, to_tick: 3800 } }),
    ];
    const chapters = readChapters(history);
    // Should have exactly 2 chapters (dedupe removed the first 3700-3800)
    expect(chapters).toHaveLength(2);
    // The 3700-3800 window should be the LATER occurrence
    const ch3700 = chapters.find((c) => c.fromTick === 3700 && c.toTick === 3800);
    expect(ch3700?.text).toBe('Better retelling of 3700-3800.');
    // The other window is intact
    const ch3800 = chapters.find((c) => c.fromTick === 3800 && c.toTick === 3900);
    expect(ch3800?.text).toBe('Unique window 3800-3900.');
  });

  it('rebuild wins when history is newest-first: higher seq wins, not array position', () => {
    // Live runtime history arrives newest-first (useSimulation prepends new
    // events + sorts seq desc). After a `rebuild` re-narrate, the rebuilt
    // chapter has the HIGHER seq but sits at the FRONT of the array while the
    // original sits later. Dedupe must keep the rebuilt one (higher seq), not
    // the last-in-array (which would be the stale original).
    const history = [
      ev({ kind: 'narrator_summary', text: 'Rebuilt 0-100 (newer).', tick: 5000, seq: 99,
           payload: { from_tick: 0, to_tick: 100 } }),
      ev({ kind: 'narrator_summary', text: 'Original 0-100 (older).', tick: 100, seq: 10,
           payload: { from_tick: 0, to_tick: 100 } }),
    ];
    const chapters = readChapters(history);
    expect(chapters).toHaveLength(1);
    expect(chapters[0].text).toBe('Rebuilt 0-100 (newer).');
  });

  it('falls back to event tick when payload lacks from_tick / to_tick', () => {
    const history = [
      ev({ kind: 'narrator_summary', text: 'Fallback chapter.', tick: 55 }),
    ];
    const [ch] = readChapters(history);
    expect(ch.fromTick).toBe(55);
    expect(ch.toTick).toBe(55);
  });

  it('returns empty array when there are no narrator_summary events', () => {
    const history = [
      ev({ kind: 'agent_speech', text: 'hello' }),
    ];
    expect(readChapters(history)).toHaveLength(0);
  });

  it('maps payload chaos / chronicler_version / routed_via onto the Chapter', () => {
    const payloadChaos = {
      cast: ['Aria', 'Bret'],
      quotes: [{ speaker: 'Aria', said: 'All is lost.' }],
      laws: ['No stealing after dark.'],
      conflicts: ['Aria and Bret clashed.'],
      deaths: [],
      counts: { spoken: 7, laws: 1, clashes: 1, deaths: 0 },
    };
    const history = [
      ev({
        kind: 'narrator_summary',
        text: 'The chapter text.',
        tick: 300,
        profile: 'free',
        payload: {
          from_tick: 200,
          to_tick: 300,
          chronicler_version: 2,
          routed_via: 'gemini-flash',
          chaos: payloadChaos,
        },
      }),
    ];
    const [ch] = readChapters(history);

    expect(ch.chroniclerVersion).toBe(2);
    expect(ch.routedVia).toBe('gemini-flash');
    expect(ch.chaos).toBeDefined();
    expect(ch.chaos!.counts.spoken).toBe(7);
    expect(ch.chaos!.counts.laws).toBe(1);
    expect(ch.chaos!.counts.clashes).toBe(1);
    expect(ch.chaos!.counts.deaths).toBe(0);
    expect(ch.chaos!.cast).toEqual(['Aria', 'Bret']);
    expect(ch.chaos!.quotes[0].said).toBe('All is lost.');
    expect(ch.chaos!.laws[0]).toBe('No stealing after dark.');
  });

  it('tolerates missing/partial chaos payload fields gracefully', () => {
    const history = [
      ev({
        kind: 'narrator_summary',
        text: 'Sparse chapter.',
        tick: 100,
        payload: {
          from_tick: 0,
          to_tick: 100,
          chronicler_version: 3,
          chaos: {
            // counts missing, cast missing, quotes malformed
            laws: ['Law one.'],
          },
        },
      }),
    ];
    const [ch] = readChapters(history);
    expect(ch.chaos).toBeDefined();
    expect(ch.chaos!.cast).toEqual([]);
    expect(ch.chaos!.quotes).toEqual([]);
    expect(ch.chaos!.laws).toEqual(['Law one.']);
    expect(ch.chaos!.counts).toEqual({ spoken: 0, laws: 0, clashes: 0, deaths: 0 });
    expect(ch.chroniclerVersion).toBe(3);
    expect(ch.routedVia).toBeUndefined();
  });

  it('leaves chaos / chroniclerVersion / routedVia undefined when not in payload', () => {
    const history = [
      ev({
        kind: 'narrator_summary',
        text: 'Legacy chapter.',
        tick: 100,
        payload: { from_tick: 0, to_tick: 100 },
      }),
    ];
    const [ch] = readChapters(history);
    expect(ch.chaos).toBeUndefined();
    expect(ch.chroniclerVersion).toBeUndefined();
    expect(ch.routedVia).toBeUndefined();
  });
});

// ============================================================
// chaosFacts
// ============================================================
describe('chaosFacts', () => {
  const FROM = 100;
  const TO = 200;

  const inWindow = (kind: Parameters<typeof ev>[0]['kind'], overrides: Partial<Parameters<typeof ev>[0]> = {}) =>
    ev({ kind, tick: 150, ...overrides });

  const outOfWindow = (kind: Parameters<typeof ev>[0]['kind']) =>
    ev({ kind, tick: 50 });

  it('extracts quotes from agent_speech events within the window', () => {
    const history = [
      inWindow('agent_speech', {
        text: 'Aria says A short thing.',
        actor_id: 'aria',
      }),
      inWindow('agent_speech', {
        text: 'Bret mutters A much longer thing that should rank higher in memorable lines.',
        actor_id: 'bret',
      }),
      inWindow('agent_speech', {
        text: 'Cara whispers Medium length utterance for ranking.',
        actor_id: 'cara',
      }),
      // This one is out of window and must NOT appear
      outOfWindow('agent_speech'),
    ];
    const facts = chaosFacts(history, FROM, TO);
    expect(facts.quotes).toHaveLength(3);
    // Sorted by length descending — longest first
    expect(facts.quotes[0].said.length).toBeGreaterThanOrEqual(facts.quotes[1].said.length);
    expect(facts.quotes[1].said.length).toBeGreaterThanOrEqual(facts.quotes[2].said.length);
    // Cast picks up the speakers
    expect(facts.cast).toContain('Aria');
    expect(facts.cast).toContain('Bret');
  });

  it('extracts payload.said when present', () => {
    const history = [
      inWindow('agent_speech', {
        text: 'Agent says blah blah.',
        payload: { said: 'The actual meaningful quote.' },
        actor_id: 'agent1',
      }),
    ];
    const facts = chaosFacts(history, FROM, TO);
    expect(facts.quotes[0].said).toBe('The actual meaningful quote.');
  });

  it('collects laws from rule_passed and town_named events', () => {
    const history = [
      inWindow('rule_passed', { text: 'No stealing after dark.' }),
      inWindow('town_named', { text: 'Henceforth this town is called Madfield.' }),
      outOfWindow('rule_passed'),
    ];
    const facts = chaosFacts(history, FROM, TO);
    expect(facts.laws).toHaveLength(2);
    expect(facts.laws).toContain('No stealing after dark.');
    expect(facts.counts.laws).toBe(2);
  });

  it('collects conflicts from conflict and commitment_lapsed events', () => {
    const history = [
      inWindow('conflict', { text: 'Aria and Bret argued violently.' }),
      inWindow('commitment_lapsed', { text: 'Bret abandoned his promise.' }),
      outOfWindow('conflict'),
    ];
    const facts = chaosFacts(history, FROM, TO);
    expect(facts.conflicts).toHaveLength(2);
    expect(facts.counts.clashes).toBe(2);
  });

  it('collects deaths from agent_died events', () => {
    const history = [
      inWindow('agent_died', { text: 'Old Milo passed away.' }),
      outOfWindow('agent_died'),
    ];
    const facts = chaosFacts(history, FROM, TO);
    expect(facts.deaths).toHaveLength(1);
    expect(facts.counts.deaths).toBe(1);
  });

  it('returns empty facts for a quiet window (no matching events)', () => {
    const history = [
      outOfWindow('agent_speech'),
      outOfWindow('conflict'),
    ];
    const facts = chaosFacts(history, FROM, TO);
    expect(facts.cast).toHaveLength(0);
    expect(facts.quotes).toHaveLength(0);
    expect(facts.laws).toHaveLength(0);
    expect(facts.conflicts).toHaveLength(0);
    expect(facts.deaths).toHaveLength(0);
    expect(facts.counts).toEqual({ spoken: 0, laws: 0, clashes: 0, deaths: 0 });
  });

  it('caps cast at 8, laws/conflicts/deaths at 5, quotes at 3', () => {
    const manySpeeches = Array.from({ length: 15 }, (_, i) =>
      inWindow('agent_speech', {
        text: `Agent${i} says ${'x'.repeat(i + 1)}.`,
        actor_id: `agent${i}`,
      }),
    );
    const manyLaws = Array.from({ length: 8 }, (_, i) =>
      inWindow('rule_passed', { text: `Law ${i}` }),
    );
    const manyConflicts = Array.from({ length: 8 }, (_, i) =>
      inWindow('conflict', { text: `Conflict ${i}` }),
    );
    const manyDeaths = Array.from({ length: 8 }, (_, i) =>
      inWindow('agent_died', { text: `Death ${i}` }),
    );
    const facts = chaosFacts(
      [...manySpeeches, ...manyLaws, ...manyConflicts, ...manyDeaths],
      FROM,
      TO,
    );
    expect(facts.cast.length).toBeLessThanOrEqual(8);
    expect(facts.quotes.length).toBeLessThanOrEqual(3);
    expect(facts.laws.length).toBeLessThanOrEqual(5);
    expect(facts.conflicts.length).toBeLessThanOrEqual(5);
    expect(facts.deaths.length).toBeLessThanOrEqual(5);
  });

  it('uses actor_id as speaker fallback when text lacks a speech verb prefix', () => {
    const history = [
      inWindow('agent_speech', {
        text: 'Some text without a verb pattern.',
        actor_id: 'fallback-agent',
      }),
    ];
    const facts = chaosFacts(history, FROM, TO);
    expect(facts.cast).toContain('fallback-agent');
  });
});
