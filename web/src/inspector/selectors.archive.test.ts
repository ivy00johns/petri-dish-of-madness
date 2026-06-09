/**
 * archiveAgents (W11a EM-086, frontend-inspector.md §8) — the archive-mode
 * roster reconstructed purely from a past run's events + the RunRow
 * config_summary roster. Pure-logic tests: config seeding, event-sweep
 * discovery, death/location/profile attribution, turn_start-anchored economy
 * (via agentEconomyAt), profile-color resolution by name, and the
 * human-agents-only rule.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { archiveAgents } from './selectors';
import { ev, profile, resetSeq } from '../test-utils/fixtures';

beforeEach(() => resetSeq());

const PROFILES = [
  profile({ name: 'model-a', color: '#11aa22' }),
  profile({ name: 'model-b', color: '#3344ff' }),
];

describe('archiveAgents — config_summary seeding', () => {
  it('returns the config roster (name doubles as id) for an empty run', () => {
    const out = archiveAgents([], [
      { name: 'Ada', profile: 'model-a' },
      { name: 'Bram', profile: null },
    ], PROFILES);

    expect(out.map((a) => a.id)).toEqual(['Ada', 'Bram']);
    const ada = out[0];
    expect(ada.name).toBe('Ada');
    expect(ada.profile).toBe('model-a');
    expect(ada.profile_color).toBe('#11aa22');
    expect(ada.alive).toBe(true);
    const bram = out[1];
    expect(bram.profile).toBe('');
    expect(bram.profile_color).toBeUndefined();
  });

  it('tolerates an empty run AND empty roster (returns [])', () => {
    expect(archiveAgents([], [], [])).toEqual([]);
  });
});

describe('archiveAgents — event sweep', () => {
  it('discovers agents from events, attributing profile + color by name', () => {
    const events = [
      ev({ kind: 'turn_start', actor_id: 'Cleo', actor_type: 'human_agent',
           profile: 'model-b', tick: 1, payload: { energy: 70, credits: 30 } }),
    ];
    const out = archiveAgents(events, [], PROFILES);
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe('Cleo');
    expect(out[0].profile).toBe('model-b');
    expect(out[0].profile_color).toBe('#3344ff');
  });

  it('flips alive on agent_died and tracks location from agent_moved', () => {
    const events = [
      ev({ kind: 'agent_moved', actor_id: 'Ada', actor_type: 'human_agent',
           tick: 2, payload: { place: 'market' } }),
      ev({ kind: 'agent_moved', actor_id: 'Ada', actor_type: 'human_agent',
           tick: 5, payload: { place: 'forest' } }),
      ev({ kind: 'agent_died', actor_id: 'Ada', actor_type: 'human_agent', tick: 9 }),
    ];
    const out = archiveAgents(events, [{ name: 'Ada', profile: 'model-a' }], PROFILES);
    expect(out[0].alive).toBe(false);
    expect(out[0].location).toBe('forest'); // the LATEST move wins
  });

  it('excludes animal/system/god actors from the human roster', () => {
    const events = [
      ev({ kind: 'animal_action', actor_id: 'animal_cat', actor_type: 'animal', tick: 1 }),
      ev({ kind: 'narrator_summary', actor_id: 'narrator', actor_type: 'system', tick: 2 }),
      ev({ kind: 'random_event', actor_id: 'god_hand', actor_type: 'god', tick: 3 }),
      ev({ kind: 'turn_start', actor_id: 'Ada', actor_type: 'human_agent', tick: 4,
           payload: { energy: 50, credits: 10 } }),
    ];
    const out = archiveAgents(events, [], PROFILES);
    expect(out.map((a) => a.id)).toEqual(['Ada']);
  });

  it('tolerates a missing actor_type on kinds that imply an agent actor', () => {
    const events = [
      ev({ kind: 'agent_speech', actor_id: 'Ada', tick: 1 }), // no actor_type (old rows)
    ];
    expect(archiveAgents(events, [], []).map((a) => a.id)).toEqual(['Ada']);
  });
});

describe('archiveAgents — economy from turn_start samples', () => {
  it('anchors energy/credits on the latest turn_start and folds own deltas', () => {
    const events = [
      ev({ kind: 'turn_start', actor_id: 'Ada', actor_type: 'human_agent',
           tick: 1, payload: { energy: 80, credits: 20 } }),
      ev({ kind: 'action_resolved', actor_id: 'Ada', actor_type: 'human_agent',
           tick: 1, payload: { outcome: 'ok', state_deltas: { energy: -10, credits: 5 } } }),
      ev({ kind: 'turn_start', actor_id: 'Ada', actor_type: 'human_agent',
           tick: 6, payload: { energy: 55, credits: 31 } }), // later sample re-anchors
      ev({ kind: 'action_resolved', actor_id: 'Ada', actor_type: 'human_agent',
           tick: 6, payload: { outcome: 'ok', state_deltas: { credits: -1 } } }),
    ];
    const out = archiveAgents(events, [], PROFILES);
    expect(out[0].energy).toBe(55);
    expect(out[0].credits).toBe(30); // 31 - 1
  });

  it('keeps zero defaults for roster agents that never acted', () => {
    const out = archiveAgents([], [{ name: 'Idle', profile: 'model-a' }], PROFILES);
    expect(out[0].energy).toBe(0);
    expect(out[0].credits).toBe(0);
  });
});
