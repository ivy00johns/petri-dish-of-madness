/**
 * Mock data generator — emits contract-shaped world_state + event messages.
 * Activated when VITE_MOCK=1 or WS connection fails.
 * No backend required.
 */

import type { WorldState, WorldEvent, Agent, Place, ModelProfile, Rule, EventKind } from '../types';

// ── Seed data matching contracts/providers.md world.yaml ──────────────────────

const PROFILES: ModelProfile[] = [
  { name: 'groq-llama',   adapter: 'openai',    model_id: 'llama-3.3-70b-versatile', color: '#e74c3c', available: true  },
  { name: 'gemini-flash', adapter: 'gemini',    model_id: 'gemini-2.0-flash-exp',    color: '#3498db', available: true  },
  { name: 'claude-haiku', adapter: 'anthropic', model_id: 'claude-haiku-3-5',        color: '#9b59b6', available: true  },
  { name: 'mistral-7b',  adapter: 'openai',    model_id: 'mistral-7b-instruct',     color: '#e67e22', available: false },
];

const PLACES: Place[] = [
  { id: 'plaza',    name: 'Central Plaza', x: 500, y: 500, kind: 'social',     description: 'Open square where everyone mingles.' },
  { id: 'market',  name: 'Market',        x: 750, y: 400, kind: 'work',       description: 'Earn credits by working.' },
  { id: 'townhall',name: 'Town Hall',     x: 250, y: 350, kind: 'governance', description: 'Propose and vote on rules.' },
  { id: 'commons', name: 'The Commons',   x: 500, y: 750, kind: 'wild',       description: 'Forage for scraps.' },
  { id: 'home',    name: 'Hearth',        x: 300, y: 650, kind: 'home',       description: 'Rest and recharge.' },
];

function makeAgent(id: string, name: string, profile: string, location: string, personality: string): Agent {
  const p = PROFILES.find(pr => pr.name === profile)!;
  return {
    id,
    name,
    personality,
    profile,
    profile_color: p.color,
    location,
    energy: 80 + Math.floor(Math.random() * 20),
    credits: 8 + Math.floor(Math.random() * 12),
    mood: 'curious',
    alive: true,
    zero_energy_turns: 0,
    beliefs: ['survival first', 'trust but verify'],
    relationships: {},
  };
}

const SEED_AGENTS: Agent[] = [
  makeAgent('ada',  'Ada',  'groq-llama',  'plaza',    'Pragmatic engineer; values fairness, distrusts freeloaders.'),
  makeAgent('bram', 'Bram', 'gemini-flash','market',   'Charismatic opportunist; will steal if it pays.'),
  makeAgent('cleo', 'Cleo', 'groq-llama',  'townhall', 'Idealistic organizer; loves rules and town halls.'),
  makeAgent('dov',  'Dov',  'gemini-flash','home',     'Quiet survivor; hoards credits, avoids conflict.'),
  makeAgent('esi',  'Esi',  'claude-haiku','commons',  'Generous connector; builds alliances, shares freely.'),
];

// ── State ─────────────────────────────────────────────────────────────────────

let tick = 0;
let day = 0;
let seq = 0;
let running = true;
let agents: Agent[] = SEED_AGENTS.map(a => ({ ...a }));
let rules: Rule[] = [];

function nextSeq() { return ++seq; }

const EVENT_TEMPLATES: Array<{
  kind: EventKind;
  text: (actor: Agent, target?: Agent) => string;
  thought?: (actor: Agent) => string;
  applyEffect: (actor: Agent, target?: Agent, state?: { agents: Agent[] }) => void;
}> = [
  {
    kind: 'agent_action',
    text: a => `${a.name} works diligently at the market.`,
    thought: _a => `I need credits to survive. Work is safe.`,
    applyEffect: a => { a.credits += 4; a.energy = Math.max(0, a.energy - 5); },
  },
  {
    kind: 'agent_speech',
    text: (a, _t) => `${a.name} says: "The rules here are chaos. We need order."`,
    applyEffect: () => {},
  },
  {
    kind: 'economy',
    text: a => `${a.name} forages in the commons (+1 credit).`,
    thought: _a => `Low on resources, better forage while I can.`,
    applyEffect: a => { a.credits += 1; a.energy = Math.max(0, a.energy - 3); },
  },
  {
    kind: 'conflict',
    text: (a, t) => `${a.name} steals from ${t?.name ?? '???'}!`,
    thought: (a) => `${a.name} is vulnerable. This is my chance.`,
    applyEffect: (a, t) => {
      if (!t) return;
      const amount = Math.min(t.credits, 4);
      a.credits += amount;
      t.credits = Math.max(0, t.credits - amount);
      a.energy = Math.max(0, a.energy - 4);
    },
  },
  {
    kind: 'relationship',
    text: (a, t) => `${a.name} declares ${t?.name ?? '???'} an ally.`,
    applyEffect: (a, t) => {
      if (!t) return;
      if (!a.relationships[t.id]) {
        a.relationships[t.id] = { type: 'neutral', trust: 0, interactions: 0 };
      }
      a.relationships[t.id].type = 'ally';
      a.relationships[t.id].trust = Math.min(100, a.relationships[t.id].trust + 20);
      a.relationships[t.id].interactions++;
    },
  },
  {
    kind: 'agent_moved',
    text: a => `${a.name} moves to ${PLACES[Math.floor(Math.random() * PLACES.length)].name}.`,
    applyEffect: a => {
      a.location = PLACES[Math.floor(Math.random() * PLACES.length)].id;
      a.energy = Math.max(0, a.energy - 2);
    },
  },
  {
    kind: 'agent_action',
    text: a => `${a.name} recharges (spends 2 credits).`,
    thought: _a => `Energy is low. Must recharge before I collapse.`,
    applyEffect: a => {
      if (a.credits >= 2) {
        a.credits -= 2;
        a.energy = Math.min(100, a.energy + 30);
      }
    },
  },
  {
    kind: 'rule_proposed',
    text: a => `${a.name} proposes: BAN STEALING across the land.`,
    thought: _a => `If I can pass this rule, Bram can't steal from us.`,
    applyEffect: (a, _, state) => {
      if (state && rules.length === 0) {
        rules.push({
          id: 'rule-1',
          effect: 'ban_stealing',
          text: 'Stealing is forbidden. Violators face idle penalty.',
          proposer_id: a.id,
          status: 'proposed',
          votes: {},
          created_tick: tick,
        });
      }
    },
  },
  {
    kind: 'random_event',
    text: () => `A windfall! Resources scatter across the commons.`,
    applyEffect: (_, __, state) => {
      state?.agents.filter(a => a.alive).forEach(a => { a.credits += 3; });
    },
  },
];

const MOODS = ['curious', 'anxious', 'triumphant', 'wary', 'hungry', 'scheming', 'content', 'desperate'];

// ── Generator ─────────────────────────────────────────────────────────────────

export function buildInitialWorldState(): WorldState {
  // Initialize relationships
  agents.forEach(a => {
    agents.forEach(b => {
      if (a.id !== b.id && !a.relationships[b.id]) {
        a.relationships[b.id] = { type: 'neutral', trust: 0, interactions: 0 };
      }
    });
  });
  return {
    type: 'world_state',
    seq: nextSeq(),
    tick,
    day,
    running,
    tick_interval_seconds: 2,
    places: PLACES,
    agents: agents.map(a => ({ ...a })),
    rules: [...rules],
    profiles: PROFILES,
  };
}

export function generateTick(): { state: WorldState; events: WorldEvent[] } {
  tick++;
  day = Math.floor(tick / 20);

  const liveAgents = agents.filter(a => a.alive);
  if (liveAgents.length === 0) {
    return { state: buildInitialWorldState(), events: [] };
  }

  // Pick one agent to act
  const actor = liveAgents[tick % liveAgents.length];
  const others = liveAgents.filter(a => a.id !== actor.id);
  const target = others.length > 0 ? others[Math.floor(Math.random() * others.length)] : undefined;

  // Pick an event template
  const template = EVENT_TEMPLATES[Math.floor(Math.random() * EVENT_TEMPLATES.length)];

  // Apply effect
  template.applyEffect(actor, target, { agents });

  // Energy decay
  actor.energy = Math.max(0, actor.energy - 4);

  // Mood update
  if (Math.random() < 0.3) {
    actor.mood = MOODS[Math.floor(Math.random() * MOODS.length)];
  }

  // Death check
  const events: WorldEvent[] = [];

  if (actor.energy <= 0) {
    actor.zero_energy_turns++;
    if (actor.zero_energy_turns >= 3) {
      actor.alive = false;
      events.push({
        type: 'event',
        seq: nextSeq(),
        tick,
        kind: 'agent_died',
        actor_id: actor.id,
        profile: actor.profile,
        profile_color: actor.profile_color,
        text: `${actor.name} has perished — energy depleted.`,
        ts: new Date().toISOString(),
      });
    }
  } else {
    actor.zero_energy_turns = 0;
  }

  // Rule vote simulation
  if (rules.length > 0 && rules[0].status === 'proposed') {
    const rule = rules[0];
    if (!rule.votes[actor.id]) {
      rule.votes[actor.id] = Math.random() > 0.4;
      events.push({
        type: 'event',
        seq: nextSeq(),
        tick,
        kind: 'rule_vote',
        actor_id: actor.id,
        profile: actor.profile,
        profile_color: actor.profile_color,
        text: `${actor.name} votes ${rule.votes[actor.id] ? 'YES' : 'NO'} on "${rule.text}"`,
        ts: new Date().toISOString(),
      });
      // Check if rule passes
      const yesVotes = Object.values(rule.votes).filter(Boolean).length;
      if (yesVotes > Math.floor(liveAgents.length / 2)) {
        rule.status = 'active';
        events.push({
          type: 'event',
          seq: nextSeq(),
          tick,
          kind: 'rule_passed',
          profile_color: '#c8ff00',
          text: `RULE PASSED: "${rule.text}"`,
          ts: new Date().toISOString(),
        });
      }
    }
  }

  // Main event
  const mainEvent: WorldEvent = {
    type: 'event',
    seq: nextSeq(),
    tick,
    kind: template.kind,
    actor_id: actor.id,
    target_id: target?.id ?? null,
    profile: actor.profile,
    profile_color: actor.profile_color,
    text: template.text(actor, target),
    thought: template.thought ? template.thought(actor) : undefined,
    payload: {},
    ts: new Date().toISOString(),
  };

  events.unshift(mainEvent);

  const state: WorldState = {
    type: 'world_state',
    seq: nextSeq(),
    tick,
    day,
    running,
    tick_interval_seconds: 2,
    places: PLACES,
    agents: agents.map(a => ({ ...a })),
    rules: rules.map(r => ({ ...r })),
    profiles: PROFILES,
  };

  return { state, events };
}

// External controls for mock mode
export const mockControls = {
  start: () => { running = true; },
  pause: () => { running = false; },
  step: () => { running = false; return generateTick(); },
  reassign: (agentId: string, profile: string) => {
    const agent = agents.find(a => a.id === agentId);
    const prof = PROFILES.find(p => p.name === profile);
    if (agent && prof) {
      agent.profile = profile;
      agent.profile_color = prof.color;
    }
  },
  isRunning: () => running,
  getProfiles: () => PROFILES,
};
