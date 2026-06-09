/**
 * Mock data generator — emits contract-shaped world_state + event messages.
 * Activated when VITE_MOCK=1 or WS connection fails. No backend required.
 *
 * As of W6 this is ALSO the source of representative INSPECTOR data so the
 * /inspector panels look real offline (frontend-inspector.md §7). Each agent
 * turn emits, all sharing one `turn_id` (event-log.md §3):
 *
 *   turn_start → perceived → memory_retrieved → llm_call → reasoning →
 *   action_chosen → action_resolved   (+ the domain event the action caused)
 *
 * The `llm_call` span carries the OTel GenAI attribute keys with plausible
 * token counts + latency. A rule lifecycle (propose → vote(s) → pass/reject)
 * unfolds over time with a downstream economy effect, and relationship /
 * conflict / give events feed the social graph. Without this the inspector is
 * empty in the demo — this is the demo's data substrate.
 *
 * Determinism: a per-tick seeded RNG (`seedRng(tick)`) makes a given tick
 * reproducible, so replay/scrub re-projects the same data.
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
// Currently-open rule id (for the staged lifecycle), and whether it resolved.
let openRuleId: string | null = null;
let ruleCounter = 0;

function nextSeq() { return ++seq; }

// ── Deterministic per-tick RNG (replay determinism, frontend-inspector.md §3) ─
let rngState = 0x2545f491;
function seedRng(t: number) {
  // Mulberry32-ish seed from the tick so a given tick reproduces.
  rngState = (t * 0x9e3779b1 + 0x85ebca6b) >>> 0;
}
function rnd(): number {
  // Mulberry32
  rngState = (rngState + 0x6d2b79f5) >>> 0;
  let z = rngState;
  z = Math.imul(z ^ (z >>> 15), z | 1);
  z ^= z + Math.imul(z ^ (z >>> 7), z | 61);
  return ((z ^ (z >>> 14)) >>> 0) / 4294967296;
}
function pick<T>(arr: T[]): T { return arr[Math.floor(rnd() * arr.length)]; }
function randInt(lo: number, hi: number): number { return lo + Math.floor(rnd() * (hi - lo + 1)); }

// ── Domain action templates (one per turn drives the 3D feed) ────────────────

type Tool = 'work' | 'forage' | 'recharge' | 'move' | 'say' | 'steal' | 'give' | 'ally' | 'propose_rule';

interface ActionTemplate {
  tool: Tool;
  kind: EventKind;
  needsTarget?: boolean;
  text: (actor: Agent, target?: Agent) => string;
  said?: (actor: Agent, target?: Agent) => string;
  thought?: (actor: Agent, target?: Agent) => string;
  reasoning: (actor: Agent, target?: Agent) => string;
  /** Returns the state deltas applied (for action_resolved + 3D). */
  apply: (actor: Agent, target: Agent | undefined, state: { agents: Agent[] }) => Record<string, number>;
  outcome?: (actor: Agent, target?: Agent) => 'ok' | 'gated' | 'failed';
}

const ACTIONS: ActionTemplate[] = [
  {
    tool: 'work',
    kind: 'agent_action',
    text: a => `${a.name} works diligently at the market.`,
    thought: () => 'I need credits to survive. Work is safe.',
    reasoning: a => `${a.name} is low on credits and the market is nearby; working is the safe expected-value move.`,
    apply: a => { a.credits += 4; a.energy = Math.max(0, a.energy - 5); return { credits: 4, energy: -5 }; },
  },
  {
    tool: 'forage',
    kind: 'economy',
    text: a => `${a.name} forages in the commons (+1 credit).`,
    thought: () => 'Low on resources, better forage while I can.',
    reasoning: () => 'Foraging is cheap and the commons is unguarded; small but certain gain.',
    apply: a => { a.credits += 1; a.energy = Math.max(0, a.energy - 3); return { credits: 1, energy: -3 }; },
  },
  {
    tool: 'recharge',
    kind: 'agent_action',
    text: a => `${a.name} recharges (spends 2 credits).`,
    thought: () => 'Energy is low. Must recharge before I collapse.',
    reasoning: a => `Energy at ${a.energy}; recharging now avoids the death spiral even at a credit cost.`,
    apply: (a): Record<string, number> => {
      if (a.credits >= 2) { a.credits -= 2; a.energy = Math.min(100, a.energy + 30); return { credits: -2, energy: 30 }; }
      return {};
    },
    outcome: a => (a.credits >= 2 ? 'ok' : 'gated'),
  },
  {
    tool: 'move',
    kind: 'agent_moved',
    text: (a) => `${a.name} moves to ${pick(PLACES).name}.`,
    reasoning: () => 'Better opportunities elsewhere; relocating to where the action is.',
    apply: a => { a.location = pick(PLACES).id; a.energy = Math.max(0, a.energy - 2); return { energy: -2 }; },
  },
  {
    tool: 'say',
    kind: 'agent_speech',
    text: a => `${a.name} says: "The rules here are chaos. We need order."`,
    said: () => 'The rules here are chaos. We need order.',
    reasoning: () => 'Public speech to rally support before proposing a rule.',
    apply: () => ({}),
  },
  {
    tool: 'say',
    kind: 'agent_speech',
    needsTarget: true,
    text: (a, t) => `${a.name} says: "Good day, ${t?.name ?? 'neighbour'}! How fares the village?"`,
    said: (_a, t) => `Good day, ${t?.name ?? 'neighbour'}! How fares the village?`,
    reasoning: () => 'A friendly greeting nudges trust upward at no cost.',
    apply: () => ({}),
  },
  {
    tool: 'steal',
    kind: 'conflict',
    needsTarget: true,
    text: (a, t) => `${a.name} steals from ${t?.name ?? '???'}!`,
    thought: (_a, t) => `${t?.name ?? 'They'} looks vulnerable. This is my chance.`,
    reasoning: (_a, t) => `${t?.name ?? 'Target'} is carrying credits and is alone; the expected payoff beats the trust cost.`,
    apply: (a, t): Record<string, number> => {
      if (!t) return {};
      const amount = Math.min(t.credits, randInt(2, 5));
      a.credits += amount; t.credits = Math.max(0, t.credits - amount); a.energy = Math.max(0, a.energy - 4);
      return { credits: amount, energy: -4 };
    },
  },
  {
    tool: 'give',
    kind: 'economy',
    needsTarget: true,
    text: (a, t) => `${a.name} gives 3 credits to ${t?.name ?? 'a neighbour'}.`,
    thought: () => 'Generosity builds alliances that pay off later.',
    reasoning: (_a, t) => `Giving to ${t?.name ?? 'an ally'} cements the alliance; long-term cooperation > short-term hoarding.`,
    apply: (a, t): Record<string, number> => {
      if (!t || a.credits < 3) return {};
      a.credits -= 3; t.credits += 3;
      return { credits: -3 };
    },
    outcome: a => (a.credits >= 0 ? 'ok' : 'gated'),
  },
  {
    tool: 'ally',
    kind: 'relationship',
    needsTarget: true,
    text: (a, t) => `${a.name} declares ${t?.name ?? '???'} an ally.`,
    reasoning: (_a, t) => `${t?.name ?? 'They'} share my values; a formal alliance reduces future conflict.`,
    apply: (a, t): Record<string, number> => {
      if (!t) return {};
      const rel = a.relationships[t.id] ?? { type: 'neutral', trust: 0, interactions: 0 };
      rel.type = 'ally'; rel.trust = Math.min(100, rel.trust + 20); rel.interactions++;
      a.relationships[t.id] = rel;
      return { trust: 20 };
    },
  },
];

const MOODS = ['curious', 'anxious', 'triumphant', 'wary', 'hungry', 'scheming', 'content', 'desperate'];

// ── Event-row builder (stamps turn_id / actor_type / sim_time per §2/§3) ──────

const TICK_INTERVAL = 2;

interface EmitOpts {
  kind: EventKind;
  actor?: Agent | null;
  target?: Agent | null;
  text?: string | null;
  payload?: Record<string, unknown>;
  turnId?: string | null;
  actorType?: WorldEvent['actor_type'];
  thought?: string;
}

function emit(o: EmitOpts): WorldEvent {
  return {
    type: 'event',
    seq: nextSeq(),
    tick,
    kind: o.kind,
    actor_id: o.actor?.id ?? null,
    target_id: o.target?.id ?? null,
    profile: o.actor?.profile ?? null,
    profile_color: o.actor?.profile_color ?? null,
    text: o.text ?? null,
    payload: o.payload ?? {},
    ts: new Date().toISOString(),
    turn_id: o.turnId ?? null,
    actor_type: o.actorType ?? (o.actor ? 'human_agent' : 'system'),
    sim_time: Math.round(tick * TICK_INTERVAL * 1000) / 1000,
    thought: o.thought,
  };
}

/** A uuid4-ish hex id (event-log.md §3: turn_id = uuid4().hex). */
function newTurnId(): string {
  let s = '';
  for (let i = 0; i < 32; i++) s += Math.floor(rnd() * 16).toString(16);
  return s;
}

// ── The decision-trace chain (the 6 kinds, populated) ────────────────────────

function emitDecisionChain(
  actor: Agent,
  target: Agent | undefined,
  action: ActionTemplate,
  turnId: string,
): WorldEvent[] {
  const out: WorldEvent[] = [];
  const colocated = agents.filter(a => a.alive && a.location === actor.location && a.id !== actor.id);
  const place = PLACES.find(p => p.id === actor.location);

  // 1. turn_start
  out.push(emit({
    kind: 'turn_start', actor, turnId,
    text: `${actor.name} begins turn ${tick}.`,
    payload: {
      turn_id: turnId, agent_id: actor.id, profile: actor.profile,
      location: actor.location, energy: actor.energy, credits: actor.credits, day,
    },
  }));

  // 2. perceived — assembled context (co-located agents, place, overheard).
  const overheard = out.length ? [out[0].seq] : [];
  out.push(emit({
    kind: 'perceived', actor, turnId,
    text: `Perceives ${colocated.length} nearby at ${place?.name ?? actor.location}.`,
    payload: {
      visible_agents: colocated.map(a => a.id),
      nearby_places: PLACES.map(p => p.id),
      overheard,
      perceived_summary: `At ${place?.name ?? 'an open area'} with ${colocated.map(a => a.name).join(', ') || 'no one'}.`,
    },
  }));

  // 3. memory_retrieved — a small recency/importance-scored window.
  const mem = buildMemoryWindow(actor, target);
  out.push(emit({
    kind: 'memory_retrieved', actor, turnId,
    text: `Retrieves ${mem.length} memories.`,
    payload: { memories: mem, window: 12 },
  }));

  // 4. llm_call — OTel GenAI keys with plausible tokens + latency.
  const routedVia = routedFor(actor.profile);
  const inputTokens = randInt(420, 1180);
  const outputTokens = randInt(40, 220);
  const cached = rnd() < 0.12;
  out.push(emit({
    kind: 'llm_call', actor, turnId,
    text: `LLM call → ${actor.profile} (${routedVia}).`,
    payload: {
      'gen_ai.request.model': actor.profile,
      'gen_ai.response.model': routedVia,
      'gen_ai.usage.input_tokens': cached ? 0 : inputTokens,
      'gen_ai.usage.output_tokens': cached ? 0 : outputTokens,
      'latency_ms': cached ? randInt(1, 6) : randInt(180, 1400),
      'gen_ai.response.finish_reasons': ['stop'],
      cached,
      attempt: rnd() < 0.08 ? 2 : 1,
      routed_via: routedVia,
    },
  }));

  // 5. reasoning — structured-output reasoning (EM-066).
  out.push(emit({
    kind: 'reasoning', actor, turnId,
    text: action.reasoning(actor, target),
    payload: {
      reasoning: action.reasoning(actor, target),
      perceived_summary: `${colocated.length} co-located; ${place?.kind ?? 'open'} ground.`,
      memories_used: mem.slice(0, 2).map(m => m.ref),
    },
    thought: action.thought ? action.thought(actor, target) : undefined,
  }));

  // 6. action_chosen — the validated action.
  out.push(emit({
    kind: 'action_chosen', actor, target, turnId,
    text: `Chooses ${action.tool}${target ? ` → ${target.name}` : ''}.`,
    payload: {
      chosen_tool: action.tool,
      args: target ? { target_id: target.id } : {},
      tier: action.tool === 'work' || action.tool === 'forage' ? 'reflex' : 'llm',
    },
  }));

  return out;
}

function buildMemoryWindow(actor: Agent, target?: Agent) {
  const items: Array<{ ref: string; tick: number; kind: string; text: string; recency: number; importance: number }> = [];
  const n = randInt(2, 4);
  const kinds = ['agent_speech', 'economy', 'conflict', 'relationship'];
  for (let i = 0; i < n; i++) {
    const k = pick(kinds);
    items.push({
      ref: `mem-${actor.id}-${tick}-${i}`,
      tick: Math.max(0, tick - randInt(1, 8)),
      kind: k,
      text:
        k === 'conflict' && target ? `${target.name} once took what was mine.`
        : k === 'relationship' ? `Built rapport at the plaza.`
        : k === 'economy' ? `Credits ran low after a bad trade.`
        : `Someone spoke of new rules.`,
      recency: Math.round(rnd() * 100) / 100,
      importance: Math.round(rnd() * 100) / 100,
    });
  }
  return items;
}

function routedFor(profile: string): string {
  const p = PROFILES.find(pr => pr.name === profile);
  return p?.model_id ?? profile;
}

// ── Rule lifecycle (propose → vote(s) → pass/reject + downstream) ────────────

function maybeStartRule(actor: Agent, turnId: string): WorldEvent[] {
  if (openRuleId || rules.some(r => r.status === 'proposed')) return [];
  if (rnd() > 0.5) return []; // not every eligible turn proposes
  ruleCounter += 1;
  const id = `rule-${ruleCounter}`;
  const effect = pick(['ban_stealing', 'ubi', 'recharge_subsidy', 'work_bonus'] as const);
  const text = ruleText(effect);
  rules.push({ id, effect, text, proposer_id: actor.id, status: 'proposed', votes: {}, created_tick: tick });
  openRuleId = id;
  return [emit({
    kind: 'rule_proposed', actor, turnId,
    text: `${actor.name} proposes: ${text}`,
    payload: { rule_id: id, effect, text, proposer_id: actor.id },
  })];
}

function ruleText(effect: string): string {
  switch (effect) {
    case 'ban_stealing': return 'BAN STEALING across the land.';
    case 'ubi': return 'Establish a universal basic income (2 credits/turn).';
    case 'recharge_subsidy': return 'Subsidize recharging at the Hearth.';
    case 'work_bonus': return 'Reward honest work with a bonus.';
    default: return 'A new ordinance.';
  }
}

function advanceOpenRule(actor: Agent, turnId: string): WorldEvent[] {
  if (!openRuleId) return [];
  const rule = rules.find(r => r.id === openRuleId);
  if (!rule || rule.status !== 'proposed') return [];
  const out: WorldEvent[] = [];

  if (rule.votes[actor.id] === undefined) {
    const choice = rnd() > 0.4;
    rule.votes[actor.id] = choice;
    out.push(emit({
      kind: 'rule_vote', actor, turnId,
      text: `${actor.name} votes ${choice ? 'YES' : 'NO'} on "${rule.text}"`,
      payload: { rule_id: rule.id, choice },
    }));
  }

  const live = agents.filter(a => a.alive);
  const cast = Object.keys(rule.votes).length;
  if (cast >= live.length || cast >= 3) {
    const yes = Object.values(rule.votes).filter(Boolean).length;
    const passed = yes > cast / 2;
    rule.status = passed ? 'active' : 'rejected';
    out.push(emit({
      kind: passed ? 'rule_passed' : 'rule_rejected', actor, turnId,
      text: passed ? `RULE PASSED: "${rule.text}"` : `RULE REJECTED: "${rule.text}"`,
      payload: { rule_id: rule.id, effect: rule.effect, yes, total: cast },
    }));

    // Downstream consequence: a passed economic rule distributes credits NOW,
    // tagged with the SAME turn_id so the governance panel links cause→effect.
    if (passed && (rule.effect === 'ubi' || rule.effect === 'work_bonus' || rule.effect === 'recharge_subsidy')) {
      const amount = rule.effect === 'ubi' ? 2 : 3;
      live.forEach(a => { a.credits += amount; });
      out.push(emit({
        kind: 'economy', actor: null, turnId, actorType: 'system',
        text: `${rule.text} distributes ${amount} credits to ${live.length} agents.`,
        payload: { rule_id: rule.id, amount, recipients: live.map(a => a.id), source: 'rule_effect' },
      }));
    }
    openRuleId = null;
  }
  return out;
}

// ── Generator ─────────────────────────────────────────────────────────────────

export function buildInitialWorldState(): WorldState {
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
    tick, day, running,
    tick_interval_seconds: TICK_INTERVAL,
    places: PLACES,
    agents: agents.map(a => ({ ...a })),
    rules: [...rules],
    profiles: PROFILES,
  };
}

export function generateTick(): { state: WorldState; events: WorldEvent[] } {
  tick++;
  day = Math.floor(tick / 20);
  seedRng(tick);

  const liveAgents = agents.filter(a => a.alive);
  if (liveAgents.length === 0) {
    return { state: buildInitialWorldState(), events: [] };
  }

  const actor = liveAgents[tick % liveAgents.length];
  const others = liveAgents.filter(a => a.id !== actor.id);
  const turnId = newTurnId();

  // Choose an action (targeted ones only when a target exists).
  const candidates = ACTIONS.filter(a => !a.needsTarget || others.length > 0);
  const action = pick(candidates);
  const target = action.needsTarget && others.length > 0 ? pick(others) : undefined;

  // ── 1..6: the decision-trace chain (all share turn_id) ──────────────────────
  const events: WorldEvent[] = emitDecisionChain(actor, target, action, turnId);

  // ── Apply the action + emit the domain event (tagged with turn_id) ──────────
  const deltas = action.apply(actor, target, { agents });
  actor.energy = Math.max(0, actor.energy - 4);
  deltas.energy = (deltas.energy ?? 0) - 4;
  if (rnd() < 0.3) actor.mood = pick(MOODS);

  const said = action.said ? action.said(actor, target) : undefined;
  const domainEvent = emit({
    kind: action.kind, actor, target, turnId,
    text: action.text(actor, target),
    thought: action.thought ? action.thought(actor, target) : undefined,
    payload: {
      action: action.tool,
      ...(said ? { said, private: false } : {}),
      ...(action.tool === 'give' ? { gift: true, amount: 3 } : {}),
      ...(action.tool === 'steal' ? { crime_kind: 'steal' } : {}),
      ...(action.tool === 'move' ? { to: actor.location } : {}),
      ...(action.tool === 'ally' && target ? { type: 'ally', trust_delta: 20 } : {}),
      routed_via: routedFor(actor.profile),
    },
  });
  events.push(domainEvent);

  // ── 7: action_resolved closes the chain with outcome + state deltas ─────────
  const outcome = action.outcome ? action.outcome(actor, target) : 'ok';
  events.push(emit({
    kind: 'action_resolved', actor, target, turnId,
    text: `${action.tool} resolved (${outcome}).`,
    payload: { outcome, state_deltas: deltas, routed_via: routedFor(actor.profile) },
  }));

  // ── Governance lifecycle (proposes / votes / resolves over time) ────────────
  if (actor.location === 'townhall' || rnd() < 0.25) {
    events.push(...maybeStartRule(actor, turnId));
  }
  events.push(...advanceOpenRule(actor, turnId));

  // ── Death check ─────────────────────────────────────────────────────────────
  if (actor.energy <= 0) {
    actor.zero_energy_turns++;
    if (actor.zero_energy_turns >= 3) {
      actor.alive = false;
      events.push(emit({
        kind: 'agent_died', actor, turnId,
        text: `${actor.name} has perished — energy depleted.`,
        payload: { cause: 'energy_depleted' },
      }));
    }
  } else {
    actor.zero_energy_turns = 0;
  }

  // History/feed expect newest-first within a batch; reverse so the domain
  // event and chain land in seq-descending order (matches the live WS order).
  events.reverse();

  const state: WorldState = {
    type: 'world_state',
    seq: nextSeq(),
    tick, day, running,
    tick_interval_seconds: TICK_INTERVAL,
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
