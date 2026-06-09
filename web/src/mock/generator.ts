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

import type {
  WorldState,
  WorldEvent,
  Agent,
  Place,
  ModelProfile,
  Rule,
  EventKind,
  Building,
  BuildingStatus,
  SpawnSpec,
} from '../types';

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

// ── Buildings (W7) — config mirrors config/world.yaml world.buildings ─────────
const BUILD_STEP = 20;            // progress per build_step (5 steps = done)
const ABANDON_AFTER_TICKS = 40;   // no fund/build activity while not operational

let buildings: Building[] = [];
let buildingCounter = 0;

// A small library of buildable projects (kind + funds + function + cost).
const PROJECT_BLUEPRINTS: Array<{ name: string; kind: string; funds: number; fn: string }> = [
  { name: 'Village Clock Tower', kind: 'clocktower', funds: 12, fn: 'voting' },
  { name: 'Community Garden',    kind: 'garden',     funds: 8,  fn: '+forage' },
  { name: "Tinkerer's Workshop", kind: 'workshop',   funds: 10, fn: '+work_reward' },
  { name: 'The Granary',         kind: 'farm',       funds: 9,  fn: '+forage' },
  { name: 'Old Library',         kind: 'library',    funds: 11, fn: 'lore' },
];

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

// ── Building lifecycle (W7) ───────────────────────────────────────────────────
//
// Drives a believable collective-project pipeline so the 3D village visibly
// grows offline: propose_project → contribute_funds → build_step.. → operational
// (one project completes), and a second project that STALLS → abandoned (the
// "clock tower that never got built"). Each transition emits the contract event
// kinds (project_proposed / project_funded / project_built / building_operational
// + structure_state_changed{from,to,reason}), tagged with the turn's turn_id so
// the inspector groups cause→effect exactly like the rule lifecycle.

/** Emit a state-machine transition (structure_state_changed) for a building. */
function emitStructureChange(
  b: Building,
  from: BuildingStatus,
  to: BuildingStatus,
  reason: string,
  actor: Agent | null,
  turnId: string,
): WorldEvent {
  return emit({
    kind: 'structure_state_changed',
    actor,
    turnId,
    actorType: actor ? 'human_agent' : 'system',
    text: `${b.name}: ${from} → ${to} (${reason}).`,
    payload: { building_id: b.id, from, to, reason, kind: b.kind, progress: b.progress },
  });
}

/** Pick a fresh blueprint not already proposed; null if all are in play. */
function pickBlueprint() {
  const taken = new Set(buildings.map((b) => b.kind));
  const free = PROJECT_BLUEPRINTS.filter((p) => !taken.has(p.kind));
  return free.length ? pick(free) : null;
}

/**
 * Advance the building pipeline for one turn. The acting agent proposes a new
 * project (occasionally), funds an under-funded one, or lays a build_step on an
 * under-construction one at its place. Returns the events emitted this turn.
 */
function advanceBuildings(actor: Agent, turnId: string): WorldEvent[] {
  const out: WorldEvent[] = [];

  // 1. Propose a new project now and then (cap concurrent active projects).
  const activeProjects = buildings.filter(
    (b) => b.status === 'planned' || b.status === 'under_construction',
  );
  if (activeProjects.length < 2 && rnd() < 0.18) {
    const bp = pickBlueprint();
    if (bp) {
      buildingCounter += 1;
      const b: Building = {
        id: `bld-${buildingCounter}`,
        name: bp.name,
        kind: bp.kind,
        location: actor.location,
        owner_id: 'public',
        status: 'planned',
        health: 100,
        condition_label: 'pristine',
        progress: 0,
        funds_committed: 0,
        funds_required: bp.funds,
        contributors: [],
        function: bp.fn,
      };
      buildings.push(b);
      lastActivityTick.set(b.id, tick);
      out.push(emit({
        kind: 'project_proposed',
        actor,
        turnId,
        text: `${actor.name} proposes a new project: ${b.name}.`,
        payload: { building_id: b.id, name: b.name, kind: b.kind, funds_required: b.funds_required, function: b.function },
      }));
      out.push(emitStructureChange(b, 'planned', 'planned', 'proposed', actor, turnId));
      return out; // one project action per turn
    }
  }

  // 2. Fund a planned project the actor can afford (flips to under_construction
  //    once fully funded + lays the first build_step).
  const fundable = buildings.find((b) => b.status === 'planned');
  if (fundable && actor.credits >= 2 && rnd() < 0.6) {
    const give = Math.min(actor.credits, randInt(2, 5), fundable.funds_required - fundable.funds_committed + 4);
    if (give > 0) {
      actor.credits -= give;
      fundable.funds_committed += give;
      lastActivityTick.set(fundable.id, tick);
      if (!fundable.contributors.includes(actor.id)) fundable.contributors.push(actor.id);
      out.push(emit({
        kind: 'project_funded',
        actor,
        turnId,
        text: `${actor.name} commits ${give} credits to ${fundable.name} (${fundable.funds_committed}/${fundable.funds_required}).`,
        payload: { building_id: fundable.id, amount: give, funds_committed: fundable.funds_committed, funds_required: fundable.funds_required },
      }));
      // economy mirror so the AWI/social panels see the credit flow.
      out.push(emit({
        kind: 'economy',
        actor,
        turnId,
        text: `${give} credits → ${fundable.name}.`,
        payload: { action: 'contribute_funds', building_id: fundable.id, amount: -give, source: 'contribute_funds' },
      }));
      if (fundable.funds_committed >= fundable.funds_required) {
        fundable.status = 'under_construction';
        fundable.progress = Math.min(100, fundable.progress + BUILD_STEP);
        out.push(emitStructureChange(fundable, 'planned', 'under_construction', 'fully_funded', actor, turnId));
        out.push(emit({
          kind: 'project_built',
          actor,
          turnId,
          text: `${actor.name} breaks ground on ${fundable.name} (${fundable.progress}%).`,
          payload: { building_id: fundable.id, progress: fundable.progress, step: BUILD_STEP },
        }));
      }
      return out;
    }
  }

  // 3. Lay a build_step on an under-construction project (visible growth). The
  //    designated STALL project (the clock tower) is skipped so it abandons.
  const buildable = buildings.find(
    (b) => b.status === 'under_construction' && !stalledBuildingIds.has(b.id),
  );
  if (buildable && rnd() < 0.7) {
    buildable.progress = Math.min(100, buildable.progress + BUILD_STEP);
    lastActivityTick.set(buildable.id, tick);
    out.push(emit({
      kind: 'project_built',
      actor,
      turnId,
      text: `${actor.name} works on ${buildable.name} (${buildable.progress}%).`,
      payload: { building_id: buildable.id, progress: buildable.progress, step: BUILD_STEP },
    }));
    if (buildable.progress >= 100) {
      buildable.status = 'operational';
      out.push(emitStructureChange(buildable, 'under_construction', 'operational', 'completed', actor, turnId));
      out.push(emit({
        kind: 'building_operational',
        actor,
        turnId,
        text: `${buildable.name} is complete — ${buildable.function} is now active!`,
        payload: { building_id: buildable.id, kind: buildable.kind, function: buildable.function },
      }));
    }
    return out;
  }

  return out;
}

/** Per-round abandonment sweep: a non-operational project with no fund/build
 *  activity for ABANDON_AFTER_TICKS becomes `abandoned` (engine-side, system
 *  actor) — the realistic collective failure. */
function sweepAbandoned(turnId: string): WorldEvent[] {
  const out: WorldEvent[] = [];
  for (const b of buildings) {
    if (b.status !== 'planned' && b.status !== 'under_construction') continue;
    const since = tick - (lastActivityTick.get(b.id) ?? 0);
    if (since >= ABANDON_AFTER_TICKS) {
      const from = b.status;
      b.status = 'abandoned';
      out.push(emitStructureChange(b, from, 'abandoned', 'no_activity', null, turnId));
    }
  }
  return out;
}

// The clock tower is seeded already under construction but deliberately STALLS
// (no one lays further build_steps), so it slides into `abandoned` after the
// abandon window — the headline "clock tower that never got built".
const stalledBuildingIds = new Set<string>();
const lastActivityTick = new Map<string, number>();

/** Seed the world with a couple of in-flight projects so the village isn't bare
 *  on first paint: one community garden under construction, and the doomed clock
 *  tower stalled mid-build. */
function seedBuildings() {
  if (buildings.length > 0) return;
  buildingCounter = 0;

  // A garden already rising at the commons (will keep progressing → operational).
  buildingCounter += 1;
  const garden: Building = {
    id: `bld-${buildingCounter}`,
    name: 'Community Garden',
    kind: 'garden',
    location: 'commons',
    owner_id: 'public',
    status: 'under_construction',
    health: 100,
    condition_label: 'pristine',
    progress: 40,
    funds_committed: 8,
    funds_required: 8,
    contributors: ['esi', 'ada'],
    function: '+forage',
  };
  buildings.push(garden);
  lastActivityTick.set(garden.id, 0);

  // The doomed clock tower, stalled at the town hall.
  buildingCounter += 1;
  const tower: Building = {
    id: `bld-${buildingCounter}`,
    name: 'Village Clock Tower',
    kind: 'clocktower',
    location: 'townhall',
    owner_id: 'public',
    status: 'under_construction',
    health: 100,
    condition_label: 'pristine',
    progress: 20,
    funds_committed: 12,
    funds_required: 12,
    contributors: ['cleo'],
    function: 'voting',
  };
  buildings.push(tower);
  stalledBuildingIds.add(tower.id);
  // last activity at tick 0 so it abandons ~tick ABANDON_AFTER_TICKS.
  lastActivityTick.set(tower.id, 0);

  // An operational house already standing at the hearth (kind tinted, function).
  buildingCounter += 1;
  const house: Building = {
    id: `bld-${buildingCounter}`,
    name: 'Wayfarer Cottage',
    kind: 'house',
    location: 'home',
    owner_id: 'dov',
    status: 'operational',
    health: 100,
    condition_label: 'pristine',
    progress: 100,
    funds_committed: 6,
    funds_required: 6,
    contributors: ['dov'],
    function: '+energy',
  };
  buildings.push(house);
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
  seedBuildings();
  return {
    type: 'world_state',
    seq: nextSeq(),
    tick, day, running,
    tick_interval_seconds: TICK_INTERVAL,
    places: PLACES,
    agents: agents.map(a => ({ ...a })),
    rules: [...rules],
    profiles: PROFILES,
    buildings: buildings.map(b => ({ ...b, contributors: [...b.contributors] })),
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

  // ── Building lifecycle (W7): propose / fund / build_step → operational, and
  //    the stalled clock tower drifting to abandoned. ──────────────────────────
  events.push(...advanceBuildings(actor, turnId));
  // Per-round abandonment sweep (round = every living agent acted once).
  if (tick % Math.max(1, liveAgents.length) === 0) {
    events.push(...sweepAbandoned(turnId));
  }

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
    buildings: buildings.map(b => ({ ...b, contributors: [...b.contributors] })),
  };

  return { state, events };
}

// ── Ad-hoc spawn (W7 EM-063) — synthesize a new agent in mock mode ───────────
let spawnCounter = 0;

/**
 * Synthesize a hot-joined agent from a god-panel spawn spec. Returns the new
 * world state (agent added) plus the events (agent_spawned + a perceived nudge
 * for co-located neighbors, mirroring the contract's "nearby agents notice the
 * newcomer"). `mode:governance` emits a governance-method spawn event with a
 * synthetic proposal id (the mock admits immediately — no live vote engine).
 */
function spawnAgentMock(spec: SpawnSpec): { state: WorldState; events: WorldEvent[] } {
  const prof = PROFILES.find(p => p.name === spec.profile) ?? PROFILES[0];
  spawnCounter += 1;
  const id = `spawn-${spawnCounter}`;
  const location = PLACES.some(p => p.id === spec.location) ? spec.location : 'plaza';
  const agent: Agent = {
    id,
    name: spec.name || `Newcomer ${spawnCounter}`,
    personality: spec.personality || 'A curious newcomer finding their footing.',
    profile: prof.name,
    profile_color: prof.color,
    location,
    energy: 90,
    credits: 10,
    mood: 'newly arrived',
    alive: true,
    zero_energy_turns: 0,
    beliefs: [],
    relationships: {},
  };
  agents.push(agent);

  const turnId = newTurnId();
  const method = spec.mode === 'governance' ? 'governance' : 'god';
  const proposalId = method === 'governance' ? `admit-${spawnCounter}` : undefined;
  const events: WorldEvent[] = [];
  events.push(emit({
    kind: 'agent_spawned',
    actor: agent,
    turnId,
    actorType: 'god',
    text: method === 'governance'
      ? `${agent.name} petitions to join (admit_agent ${proposalId}).`
      : `${agent.name} materializes at ${PLACES.find(p => p.id === location)?.name ?? location}.`,
    payload: { method, profile: agent.profile, location, ...(proposalId ? { proposal_id: proposalId } : {}) },
  }));
  // Co-located neighbors perceive the newcomer.
  const nearby = agents.filter(a => a.alive && a.id !== id && a.location === location);
  if (nearby.length > 0) {
    events.push(emit({
      kind: 'perceived',
      actor: agent,
      turnId,
      text: `${nearby.map(a => a.name).join(', ')} notice ${agent.name} arrive.`,
      payload: { visible_agents: nearby.map(a => a.id), newcomer: id },
    }));
  }
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
    buildings: buildings.map(b => ({ ...b, contributors: [...b.contributors] })),
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
  spawn: (spec: SpawnSpec) => spawnAgentMock(spec),
  isRunning: () => running,
  getProfiles: () => PROFILES,
};
