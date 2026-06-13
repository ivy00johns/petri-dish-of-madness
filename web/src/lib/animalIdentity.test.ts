/**
 * animalIdentity (EM-043 / EM-089) — the critters' model identity comes ONLY
 * from animal llm_call events (agent calls excluded), and the 🧠 marker is a
 * pure turn_id correlation between an animal_action and an animal llm_call.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { animalModelMap, llmDecidedAnimalTurns, isLlmDecidedAction, animalModelByTurn } from './animalIdentity';
import { animal, ev, profile, resetSeq } from '../test-utils/fixtures';

beforeEach(resetSeq);

const ANIMALS = [animal({ id: 'cat-1' }), animal({ id: 'dog-1', species: 'dog' })];
const PROFILES = [profile({ name: 'gemini-flash', color: '#ff00ff' })];

describe('animalModelMap', () => {
  it('maps an animal to its model from its animal llm_call (with profile color)', () => {
    const events = [
      ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal', profile: 'gemini-flash' }),
    ];
    const map = animalModelMap(events, ANIMALS, PROFILES);
    expect(map.get('cat-1')).toEqual({ profile: 'gemini-flash', color: '#ff00ff' });
    expect(map.has('dog-1')).toBe(false);
  });

  it('EXCLUDES agent llm_calls — even ones whose actor_id matches an animal', () => {
    const events = [
      // Same actor id, but actor_type is not "animal" → must not count.
      ev({ kind: 'llm_call', actor_id: 'dog-1', actor_type: 'human_agent', profile: 'model-a' }),
      ev({ kind: 'llm_call', actor_id: 'dog-1', profile: 'model-a' }), // absent actor_type
    ];
    expect(animalModelMap(events, ANIMALS, PROFILES).size).toBe(0);
  });

  it('takes the LATEST call per animal (events arrive newest-first)', () => {
    const events = [
      // newest first: gemini-flash is the current identity…
      ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal', profile: 'gemini-flash' }),
      // …an older call on a different profile must not win.
      ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal', profile: 'old-model' }),
    ];
    expect(animalModelMap(events, ANIMALS, PROFILES).get('cat-1')?.profile).toBe('gemini-flash');
  });

  it('falls back to payload gen_ai.request.model when top-level profile is missing', () => {
    const events = [
      ev({
        kind: 'llm_call',
        actor_id: 'cat-1',
        actor_type: 'animal',
        payload: { 'gen_ai.request.model': 'gemini-flash' },
      }),
    ];
    expect(animalModelMap(events, ANIMALS, PROFILES).get('cat-1')?.profile).toBe('gemini-flash');
  });
});

describe('llmDecidedAnimalTurns + isLlmDecidedAction', () => {
  it('marks an animal_action sharing an animal llm_call turn_id as LLM-decided', () => {
    const events = [
      ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal', turn_id: 'at-1' }),
      ev({ kind: 'animal_action', actor_id: 'cat-1', actor_type: 'animal', turn_id: 'at-1' }),
      ev({ kind: 'animal_action', actor_id: 'dog-1', actor_type: 'animal', turn_id: 'at-2' }),
    ];
    const turns = llmDecidedAnimalTurns(events);
    expect(turns).toEqual(new Set(['at-1']));
    expect(isLlmDecidedAction(events[1], turns)).toBe(true); // shares at-1
    expect(isLlmDecidedAction(events[2], turns)).toBe(false); // reflex turn
  });

  it('never marks non-animal_action kinds or turnless actions', () => {
    const llm = ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal', turn_id: 'at-1' });
    const turns = llmDecidedAnimalTurns([llm]);
    expect(isLlmDecidedAction(llm, turns)).toBe(false); // not an animal_action
    const turnless = ev({ kind: 'animal_action', actor_id: 'cat-1', actor_type: 'animal' });
    expect(isLlmDecidedAction(turnless, turns)).toBe(false);
  });

  it('agent llm_calls contribute no turns', () => {
    const events = [ev({ kind: 'llm_call', actor_id: 'a1', turn_id: 'ht-1' })];
    expect(llmDecidedAnimalTurns(events).size).toBe(0);
  });
});

describe('animalModelByTurn', () => {
  it('maps an animal turn_id to the model from its sibling animal llm_call', () => {
    const events = [
      ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal',
           turn_id: 'at-1', profile: 'gemini-flash' }),
      ev({ kind: 'animal_action', actor_id: 'cat-1', actor_type: 'animal', turn_id: 'at-1' }),
    ];
    expect(animalModelByTurn(events).get('at-1')).toBe('gemini-flash');
  });

  it('excludes agent llm_calls and turnless animal calls', () => {
    const events = [
      ev({ kind: 'llm_call', actor_id: 'a1', turn_id: 'ht-1', profile: 'model-a' }), // human
      ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal', profile: 'gemini-flash' }), // no turn_id
    ];
    expect(animalModelByTurn(events).size).toBe(0);
  });

  it('falls back to payload gen_ai.request.model when top-level profile is missing', () => {
    const events = [
      ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal', turn_id: 'at-1',
           payload: { 'gen_ai.request.model': 'gemini-flash' } }),
    ];
    expect(animalModelByTurn(events).get('at-1')).toBe('gemini-flash');
  });

  it('keeps the FIRST (newest) call per turn (events arrive newest-first)', () => {
    const events = [
      ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal',
           turn_id: 'at-1', profile: 'gemini-flash' }),
      ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal',
           turn_id: 'at-1', profile: 'old-model' }),
    ];
    expect(animalModelByTurn(events).get('at-1')).toBe('gemini-flash');
  });
});
