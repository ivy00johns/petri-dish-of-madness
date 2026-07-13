/**
 * The Blind Lineup (EM-309) — pure-logic tests: the flag parse, model-family
 * derivation, lineup extraction, round grading, and the cross-session
 * per-family scorecard accumulation. No DOM.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  accumulate,
  blindLineupEnabled,
  gradeRound,
  lineupFamilies,
  lineupProfiles,
  loadScorecard,
  modelFamily,
  roundScore,
  saveScorecard,
  type Scorecard,
} from './blindLineup';
import { agent, profile, world } from '../test-utils/fixtures';

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('blindLineupEnabled — the flag (default OFF)', () => {
  it('is OFF when VITE_BLIND_LINEUP is unset', () => {
    expect(blindLineupEnabled()).toBe(false);
  });

  it.each(['1', 'true', 'on', 'YES', 'On'])('is ON for %s', (v) => {
    vi.stubEnv('VITE_BLIND_LINEUP', v);
    expect(blindLineupEnabled()).toBe(true);
  });

  it.each(['0', 'false', 'off', 'nope', ''])('is OFF for %s', (v) => {
    vi.stubEnv('VITE_BLIND_LINEUP', v);
    expect(blindLineupEnabled()).toBe(false);
  });
});

describe('modelFamily', () => {
  it.each([
    ['llama-3.3-70b-versatile', 'llama'],
    ['llama-3.1-8b-instant', 'llama'],
    ['qwen-2.5-72b', 'qwen'],
    ['gemini-2.0-flash-exp', 'gemini'],
    ['gemma-2-9b-it', 'gemma'],
    ['mistral-7b-instruct', 'mistral'],
    ['open-mixtral-8x7b', 'mistral'],
    ['claude-haiku-3-5', 'claude'],
    ['deepseek-chat', 'deepseek'],
    ['command-r-plus', 'command-r'],
  ])('maps %s → %s (via model_id)', (model_id, fam) => {
    expect(modelFamily({ name: 'anything', model_id })).toBe(fam);
  });

  it('falls back to the profile name when model_id is unhelpful', () => {
    expect(modelFamily({ name: 'groq-llama', model_id: 'x' })).toBe('llama');
  });

  it('returns other for an unknown model', () => {
    expect(modelFamily({ name: 'zzz', model_id: 'proprietary-secret-9000' })).toBe('other');
  });

  it('never throws on empty input', () => {
    expect(modelFamily({})).toBe('other');
    expect(modelFamily({ name: null, model_id: null })).toBe('other');
  });
});

describe('lineupProfiles / lineupFamilies', () => {
  it('extracts one distinct profile per in-play model, in first-seen order', () => {
    const w = world({
      profiles: [
        profile({ name: 'groq-llama', model_id: 'llama-3.3-70b' }),
        profile({ name: 'gemini-flash', model_id: 'gemini-2.0-flash' }),
        profile({ name: 'unused', model_id: 'qwen-2.5' }),
      ],
      agents: [
        agent({ id: 'a1', name: 'Ada', profile: 'gemini-flash' }),
        agent({ id: 'a2', name: 'Bo', profile: 'groq-llama' }),
        agent({ id: 'a3', name: 'Cy', profile: 'gemini-flash' }), // dup profile
      ],
    });
    const lp = lineupProfiles(w);
    expect(lp.map((p) => p.name)).toEqual(['gemini-flash', 'groq-llama']); // 'unused' excluded
    expect(lineupFamilies(lp)).toEqual(['gemini', 'llama']); // sorted
  });

  it('synthesizes a profile when the agent runs a model not in world.profiles', () => {
    const w = world({
      profiles: [],
      agents: [agent({ id: 'a1', name: 'Ada', profile: 'mystery-mistral', profile_color: '#abc123' })],
    });
    const lp = lineupProfiles(w);
    expect(lp).toHaveLength(1);
    expect(lp[0].name).toBe('mystery-mistral');
    expect(lp[0].color).toBe('#abc123');
    expect(modelFamily(lp[0])).toBe('mistral');
  });

  it('returns [] for a null world', () => {
    expect(lineupProfiles(null)).toEqual([]);
  });
});

describe('gradeRound / roundScore', () => {
  const profiles = [
    profile({ name: 'groq-llama', model_id: 'llama-3.3-70b' }),
    profile({ name: 'gemini-flash', model_id: 'gemini-2.0-flash' }),
  ];

  it('marks each slot correct/incorrect against the guessed family', () => {
    const results = gradeRound(profiles, { 'groq-llama': 'llama', 'gemini-flash': 'qwen' });
    expect(results).toEqual([
      { profileName: 'groq-llama', actualFamily: 'llama', guessedFamily: 'llama', correct: true },
      { profileName: 'gemini-flash', actualFamily: 'gemini', guessedFamily: 'qwen', correct: false },
    ]);
    expect(roundScore(results)).toEqual({ correct: 1, answered: 2, total: 2 });
  });

  it('leaves unanswered slots uncounted toward accuracy', () => {
    const results = gradeRound(profiles, { 'groq-llama': 'llama' });
    expect(results[1].guessedFamily).toBeNull();
    expect(results[1].correct).toBe(false);
    expect(roundScore(results)).toEqual({ correct: 1, answered: 1, total: 2 });
  });
});

describe('scorecard — cross-session accumulation (localStorage)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('accumulate folds only answered slots, keyed by ACTUAL family', () => {
    const profiles = [
      profile({ name: 'groq-llama', model_id: 'llama-3.3-70b' }),
      profile({ name: 'gemini-flash', model_id: 'gemini-2.0-flash' }),
    ];
    const round1 = gradeRound(profiles, { 'groq-llama': 'llama', 'gemini-flash': 'llama' });
    const sc1 = accumulate({}, round1);
    // llama slot guessed llama (correct); gemini slot guessed llama (wrong)
    expect(sc1).toEqual({
      llama: { seen: 1, correct: 1 },
      gemini: { seen: 1, correct: 0 },
    });

    // Second round, gemini guessed right this time; llama unanswered (uncounted).
    const round2 = gradeRound(profiles, { 'gemini-flash': 'gemini' });
    const sc2 = accumulate(sc1, round2);
    expect(sc2).toEqual({
      llama: { seen: 1, correct: 1 },
      gemini: { seen: 2, correct: 1 },
    });
  });

  it('accumulate does not mutate the previous scorecard', () => {
    const prev: Scorecard = { llama: { seen: 1, correct: 1 } };
    const profiles = [profile({ name: 'g', model_id: 'gemini-2.0' })];
    accumulate(prev, gradeRound(profiles, { g: 'gemini' }));
    expect(prev).toEqual({ llama: { seen: 1, correct: 1 } });
  });

  it('save then load round-trips', () => {
    const sc: Scorecard = { llama: { seen: 3, correct: 2 }, gemini: { seen: 1, correct: 0 } };
    saveScorecard(sc);
    expect(loadScorecard()).toEqual(sc);
  });

  it('load returns {} on empty / garbage storage', () => {
    expect(loadScorecard()).toEqual({});
    localStorage.setItem('em.blindLineup.scorecard.v1', 'not json{');
    expect(loadScorecard()).toEqual({});
  });
});
