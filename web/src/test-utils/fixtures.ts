/**
 * Shared test fixtures (EM-043) — tiny builders that fill the contract-shaped
 * defaults so each test states ONLY what it asserts about. Pure data, no DOM.
 */
import type {
  Agent,
  Animal,
  Building,
  EventKind,
  ModelProfile,
  WorldEvent,
  WorldState,
} from '../types';

let autoSeq = 0;

/** Reset the auto-incrementing seq between tests (call in beforeEach). */
export function resetSeq(): void {
  autoSeq = 0;
}

/** A WorldEvent with contract defaults; pass `seq` to control ordering. */
export function ev(partial: Partial<WorldEvent> & { kind: EventKind }): WorldEvent {
  autoSeq += 1;
  return {
    type: 'event',
    seq: autoSeq,
    tick: 0,
    ...partial,
  };
}

export function agent(partial: Partial<Agent> & { id: string }): Agent {
  return {
    name: partial.id,
    personality: 'curious',
    profile: 'model-a',
    location: 'plaza',
    energy: 100,
    credits: 100,
    mood: 'fine',
    alive: true,
    zero_energy_turns: 0,
    beliefs: [],
    relationships: {},
    ...partial,
  };
}

export function animal(partial: Partial<Animal> & { id: string }): Animal {
  return {
    species: 'cat',
    name: partial.id,
    location: 'plaza',
    energy: 100,
    mood: 'feral',
    alive: true,
    ...partial,
  };
}

export function building(partial: Partial<Building> & { id: string }): Building {
  return {
    name: partial.id,
    kind: 'garden',
    location: 'plaza',
    owner_id: null,
    status: 'operational',
    health: 100,
    condition_label: 'pristine',
    progress: 100,
    funds_committed: 0,
    funds_required: 0,
    contributors: [],
    function: '+forage',
    ...partial,
  };
}

export function profile(partial: Partial<ModelProfile> & { name: string }): ModelProfile {
  return {
    adapter: 'freellmapi',
    model_id: partial.name,
    color: '#c8ff00',
    available: true,
    ...partial,
  };
}

export function world(partial: Partial<WorldState> = {}): WorldState {
  return {
    type: 'world_state',
    seq: 1,
    tick: 0,
    day: 0,
    running: true,
    tick_interval_seconds: 2,
    places: [],
    agents: [],
    rules: [],
    profiles: [],
    ...partial,
  };
}

/** The standard three-place test map (logical [0..1000] coords). */
export const PLACES = [
  { id: 'plaza', x: 100, y: 100 },
  { id: 'forest', x: 900, y: 900 },
  { id: 'home', x: 500, y: 200 },
];
