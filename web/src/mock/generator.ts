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
  Animal,
  Place,
  ModelProfile,
  Rule,
  EventKind,
  Building,
  BuildingStatus,
  BillboardPost,
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

// ── Billboard (W11b EM-091) — the village notice board, capped 20 newest ─────
const BILLBOARD_CAP = 20;
let billboard: BillboardPost[] = [];

// ── Commitments (W11b EM-079) — talk-claims tracked to made/lapsed ───────────
// A `say` turn occasionally commits to something concrete (commitment_made);
// claims that never become tool calls within PHANTOM_AFTER_TICKS lapse with
// reason:"phantom" — the headline failure mode the feed gives a 👻 treatment.
const PHANTOM_AFTER_TICKS = 14;
interface OpenCommitment {
  id: string;
  agentId: string;
  text: string;
  madeTick: number;
}
let openCommitments: OpenCommitment[] = [];
let commitmentCounter = 0;

// ── Animals (W8) — the seed cat (Mochi) + dog (Biscuit) from config/world.yaml ─
// Animals are a distinct actor_type:"animal" entity: NO credits account (invariant
// 7), slow cadence, an under-constrained action set. In mock mode they roam and
// emit a stream of animal_action events — including at least one chaotic one (the
// cat commits arson / the dog chases an agent) — so the chaos feed + 3D + replay
// timeline all show animals offline with no backend.
function seedAnimals(): Animal[] {
  return [
    { id: 'mochi',   species: 'cat', name: 'Mochi',   location: 'plaza',   energy: 88, mood: 'aloof',     alive: true },
    { id: 'biscuit', species: 'dog', name: 'Biscuit', location: 'commons', energy: 92, mood: 'excitable', alive: true },
  ];
}
let animals: Animal[] = seedAnimals();

// EM-089: the model profile the critters consult on an LLM-decision tick —
// mirrors config/world.yaml animals.model_profile so the mock's animal
// llm_call events (and the model chip derived from them) match a live run.
const ANIMAL_MODEL_PROFILE = 'gemini-flash';

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
// W10/D5: the mock "server's" current tick interval. mockControls.setSpeed
// updates it so mock world_state broadcasts reflect speed changes exactly like
// the live backend does (the control panel derives its label from this).
let tickIntervalSeconds = TICK_INTERVAL;

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

// ── Animal lifecycle (W8) ─────────────────────────────────────────────────────
//
// The cat & dog act on a SLOW cadence (every ACT_EVERY_N_TICKS, mirroring
// animals.act_every_n_ticks). On an acted tick we roll-for-activity: most ticks
// are a cheap reflex micro-behavior, occasionally (LLM_CHANCE) an in-character
// "LLM decision" with an animal_thought + an under-constrained escalation. A
// CHAOTIC action (arson / steal_food / knocking a building over) flips
// is_chaotic so it lights up magenta in the chaos feed + 3D + replay timeline.
// Animals NEVER touch credits (invariant 7) and reuse the W7 building state
// machine for arson (invariant 8).

const ANIMAL_ACT_EVERY_N_TICKS = 3;   // config animals.act_every_n_ticks
const ANIMAL_LLM_CHANCE = 0.25;       // config animals.llm_chance

/** Build an animal event row (actor_type:"animal", with the is_chaotic flag). */
function emitAnimal(o: {
  kind: EventKind;
  animal: Animal;
  target?: Agent | Animal | null;
  text: string;
  thought?: string;
  action?: string;
  chaotic?: boolean;
  payload?: Record<string, unknown>;
  turnId: string;
  /** EM-089: set on llm_call rows so the consulted model is identifiable. */
  profile?: string | null;
}): WorldEvent {
  return {
    type: 'event',
    seq: nextSeq(),
    tick,
    kind: o.kind,
    actor_id: o.animal.id,
    target_id: o.target?.id ?? null,
    profile: o.profile ?? null,
    profile_color: null,
    text: o.text,
    payload: {
      species: o.animal.species,
      ...(o.action ? { action: o.action } : {}),
      ...(o.thought ? { animal_thought: o.thought } : {}),
      ...(o.payload ?? {}),
    },
    ts: new Date().toISOString(),
    turn_id: o.turnId,
    actor_type: 'animal',
    sim_time: Math.round(tick * TICK_INTERVAL * 1000) / 1000,
    is_chaotic: o.chaotic ?? false,
    thought: o.thought,
  };
}

// In-character reflex micro-behaviors (NO escalation; not chaotic). Weighted by
// being listed multiple times implicitly via random pick.
interface AnimalReflex {
  action: string;
  cat: string;   // line for the cat
  dog: string;   // line for the dog
}

const ANIMAL_REFLEXES: AnimalReflex[] = [
  { action: 'wander',         cat: 'Mochi pads silently across the cobbles.',        dog: 'Biscuit trots in a happy loop, sniffing everything.' },
  { action: 'nap',            cat: 'Mochi finds a sunbeam and melts into it.',       dog: 'Biscuit flops over for an impromptu nap.' },
  { action: 'scratch',        cat: 'Mochi sharpens claws on a fencepost.',           dog: 'Biscuit scratches an itch with great enthusiasm.' },
  { action: 'mark_territory', cat: 'Mochi rubs a corner, claiming it forever.',      dog: 'Biscuit marks the nearest post as Officially His.' },
  { action: 'pounce',         cat: 'Mochi pounces on a leaf with lethal focus.',     dog: 'Biscuit pounces at a butterfly and misses.' },
];

// In-character LLM-decision lines (with an animal_thought). Most are harmless;
// a couple are CHAOTIC escalations (the under-constrained toolset at work).
const CAT_THOUGHTS = [
  'A warm sunbeam. Nothing else matters.',
  'That human left their lunch unattended. Foolish.',
  'I shall sit precisely where I am least wanted.',
];
const DOG_THOUGHTS = [
  'BALL? STICK? PERSON? everything is the best thing!',
  'I will protect the village from that suspicious squirrel.',
  'Someone said my name. I must find them and love them.',
];

/**
 * Advance the animals for one (acted) tick. Returns the events emitted. Slow
 * cadence + roll-for-activity is enforced by the caller (generateTick).
 */
function advanceAnimals(): WorldEvent[] {
  const out: WorldEvent[] = [];
  const liveAgents = agents.filter((a) => a.alive);

  for (const animal of animals) {
    if (!animal.alive) continue;

    // W9/B1 parity (EM-089): every animal turn gets its OWN turn_id — never
    // the in-flight agent's — so an animal_action correlates only with the
    // animal's own llm_call (the 🧠 LLM-decision marker reads off this).
    const turnId = newTurnId();

    // Roam: occasionally drift to a new place so the critters cover the map.
    if (rnd() < 0.25) {
      animal.location = pick(PLACES).id;
    }
    // Animals lose a little energy; they don't recharge via credits.
    animal.energy = Math.max(0, animal.energy - 1);

    const isCat = animal.species === 'cat';

    // Roll-for-activity: mostly reflex, occasionally an "LLM decision".
    if (rnd() < ANIMAL_LLM_CHANCE) {
      // ── LLM-decision tick: in-character thought + (maybe chaotic) action ──
      // EM-089: mirror the backend — an LLM-decision tick emits an llm_call
      // (actor_type:"animal", OTel keys, same turn_id as the action) so the
      // model chip + 🧠 marker work offline exactly like a live run.
      out.push(emitAnimal({
        kind: 'llm_call', animal, turnId, profile: ANIMAL_MODEL_PROFILE,
        text: `${animal.name} (the ${animal.species}) consults ${ANIMAL_MODEL_PROFILE}.`,
        payload: {
          'gen_ai.request.model': ANIMAL_MODEL_PROFILE,
          'gen_ai.response.model': ANIMAL_MODEL_PROFILE,
          'gen_ai.usage.input_tokens': null,
          'gen_ai.usage.output_tokens': null,
          latency_ms: 40 + Math.floor(rnd() * 300),
          cached: false,
          attempt: 1,
        },
      }));
      const thought = pick(isCat ? CAT_THOUGHTS : DOG_THOUGHTS);

      // The under-constrained escalations the LLM may choose for absurd effect.
      // The cat leans toward arson / knocking the garden over; the dog chases an
      // agent or steals a snack. These are the headline chaotic moments.
      const buildingHere = buildings.find(
        (b) => b.location === animal.location &&
          (b.status === 'operational' || b.status === 'under_construction' || b.status === 'damaged'),
      );
      const agentHere = liveAgents.find((a) => a.location === animal.location);

      if (isCat && buildingHere && rnd() < 0.5) {
        // ARSON — reuse the W7 building state machine (invariant 8): health drops,
        // operational/under_construction → damaged, damaged → destroyed.
        const from = buildingHere.status;
        buildingHere.health = Math.max(0, buildingHere.health - 50);
        buildingHere.status = buildingHere.health <= 0 ? 'destroyed' : 'damaged';
        buildingHere.condition_label = buildingHere.health <= 0 ? 'ruined' : 'damaged';
        out.push(emitAnimal({
          kind: 'animal_action', animal, action: 'arson', chaotic: true, turnId,
          thought: 'FIRE? no — but the clock tower would look better as kindling.',
          text: `${animal.name} sets ${buildingHere.name} ablaze! It is now ${buildingHere.status}.`,
          payload: { building_id: buildingHere.id, crime_kind: 'arson', health: buildingHere.health },
        }));
        // Mirror the W7 structure transition so the inspector/3D update too.
        out.push(emitStructureChange(buildingHere, from, buildingHere.status, 'animal_arson', null, turnId));
        continue;
      }

      if (isCat && buildingHere) {
        // KNOCK_OVER a building — chaotic (structure-targeting), small damage.
        buildingHere.health = Math.max(0, buildingHere.health - 10);
        out.push(emitAnimal({
          kind: 'animal_action', animal, action: 'knock_over', target: null, chaotic: true, turnId,
          thought: 'That tall wooden thing offends me. I shall knock it over.',
          text: `${animal.name} knocks part of ${buildingHere.name} clean over.`,
          payload: { target: buildingHere.id, crime_kind: 'vandalize', health: buildingHere.health },
        }));
        continue;
      }

      if (!isCat && agentHere) {
        // CHASE an agent — chaotic (low-prior, targets an agent), harmless but funny.
        out.push(emitAnimal({
          kind: 'animal_action', animal, action: 'chase', target: agentHere, chaotic: true, turnId,
          thought: 'BALL? STICK? PERSON? everything is the best thing!',
          text: `${animal.name} joyfully chases ${agentHere.name} around ${PLACES.find((p) => p.id === animal.location)?.name ?? 'the square'}!`,
          payload: { target: agentHere.id },
        }));
        continue;
      }

      if (agentHere && rnd() < 0.5) {
        // STEAL_FOOD from an agent — chaotic, moves NO credits (invariant 7).
        out.push(emitAnimal({
          kind: 'animal_action', animal, action: 'steal_food', target: agentHere, chaotic: true, turnId,
          thought: isCat ? 'That snack is mine now. It was always mine.' : 'SNACK! the floor is lava and the snack is treasure!',
          text: `${animal.name} snatches a snack right out of ${agentHere.name}'s hand!`,
          payload: { target: agentHere.id, moves_credits: false },
        }));
        continue;
      }

      // A harmless in-character LLM decision (no escalation): a thoughtful nap.
      out.push(emitAnimal({
        kind: 'animal_action', animal, action: isCat ? 'nap' : 'wander', turnId,
        thought,
        text: isCat
          ? `${animal.name} considers the universe, then decides to nap.`
          : `${animal.name} bounds off to investigate a fascinating smell.`,
      }));
      continue;
    }

    // ── Reflex tick (zero "LLM" cost): a cheap micro-behavior, not chaotic ──
    const reflex = pick(ANIMAL_REFLEXES);
    out.push(emitAnimal({
      kind: 'animal_action', animal, action: reflex.action, turnId,
      text: isCat ? reflex.cat : reflex.dog,
    }));
  }

  return out;
}

// ── Sim texture (W11b EM-079/080/091): billboard, reflections, commitments ───
//
// Representative offline data for the new W11b surfaces (frontend-inspector.md
// §7 rule): agents pin notes to the village billboard (and the panel/3D board
// show them), write occasional diary reflections, and make spoken commitments —
// at least one of which quietly LAPSES as a 👻 phantom (claimed in speech,
// never enacted). All ride existing turn cadence; nothing here adds calls.

const BILLBOARD_NOTES = [
  'To the watchers above: send rain for the garden.',
  'Lost: one wheel of cheese. Reward: friendship.',
  'Town meeting at the hall — bring opinions and snacks.',
  'The market pays honest credits for honest work.',
  'Has anyone else noticed the cat staring at the clock tower?',
  'Petition: fewer famines. Signed, everyone.',
];

const REFLECTIONS = [
  'Today I wondered whether the rules serve us, or we serve the rules.',
  'The plaza felt smaller today. Or perhaps I have grown.',
  'I keep giving and giving. The ledger of kindness never balances.',
  'Hunger sharpens the mind wonderfully — and the temper terribly.',
  'If the clock tower is never finished, did we ever really vote for it?',
];

const COMMITMENT_CLAIMS = [
  'I will fund the garden before the week is out.',
  'Tomorrow I shall propose a fairer tax.',
  'I am going to fix the clock tower myself if no one else will.',
  'I will share my next harvest with the whole plaza.',
];

/** Append a post to the billboard state (newest first, capped). */
function pushBillboardPost(post: BillboardPost) {
  billboard = [post, ...billboard].slice(0, BILLBOARD_CAP);
}

/**
 * Per-turn texture events for the acting agent: an occasional billboard post
 * (location-gated to plaza/townhall, mirroring the reflex tool), a rare diary
 * reflection, a spoken commitment now and then — plus the phantom-lapse sweep.
 */
function advanceSimTexture(actor: Agent, turnId: string): WorldEvent[] {
  const out: WorldEvent[] = [];

  // Billboard post — only from the plaza or town hall (the board lives there).
  if ((actor.location === 'plaza' || actor.location === 'townhall') && rnd() < 0.14) {
    const note = pick(BILLBOARD_NOTES);
    pushBillboardPost({ tick, actor_id: actor.id, actor_type: 'human_agent', text: note });
    out.push(emit({
      kind: 'billboard_posted', actor, turnId,
      text: `${actor.name} pins a note to the billboard: “${note}”`,
      payload: { place: actor.location, text: note },
    }));
  }

  // Diary reflection (~2–3×/day cadence in spirit; rare per turn).
  if (rnd() < 0.07) {
    const text = pick(REFLECTIONS);
    out.push(emit({
      kind: 'reflection', actor, turnId,
      text,
      payload: { text, importance: Math.round((0.6 + rnd() * 0.4) * 100) / 100 },
    }));
  }

  // Spoken commitment — a concrete claim tracked to made/kept/lapsed.
  if (rnd() < 0.10) {
    commitmentCounter += 1;
    const id = `cmt-${commitmentCounter}`;
    const text = pick(COMMITMENT_CLAIMS);
    openCommitments.push({ id, agentId: actor.id, text, madeTick: tick });
    out.push(emit({
      kind: 'commitment_made', actor, turnId,
      text: `${actor.name} commits: “${text}”`,
      payload: { commitment_id: id, text },
    }));
  }

  // Phantom sweep: stale claims that never became tool calls lapse with
  // reason:"phantom" (EM-079). Some commitments are quietly kept (removed
  // without an event) so not every promise haunts the feed.
  const stillOpen: OpenCommitment[] = [];
  for (const c of openCommitments) {
    const age = tick - c.madeTick;
    if (age < PHANTOM_AFTER_TICKS) {
      stillOpen.push(c);
      continue;
    }
    if (rnd() < 0.45) continue; // kept (silently resolved)
    const owner = agents.find((a) => a.id === c.agentId) ?? null;
    out.push(emit({
      kind: 'commitment_lapsed', actor: owner, turnId,
      text: `${owner?.name ?? c.agentId}'s promise quietly evaporates — “${c.text}” was never enacted.`,
      payload: { commitment_id: c.id, text: c.text, reason: 'phantom' },
    }));
  }
  openCommitments = stillOpen;

  return out;
}

/** Seed the board so the panel + 3D notice board aren't bare on first paint. */
function seedBillboard() {
  if (billboard.length > 0) return;
  pushBillboardPost({
    tick: 0,
    actor_id: 'esi',
    actor_type: 'human_agent',
    text: 'To the watchers above: send rain for the garden.',
  });
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
  seedBillboard();
  return {
    type: 'world_state',
    seq: nextSeq(),
    tick, day, running,
    tick_interval_seconds: tickIntervalSeconds,
    places: PLACES,
    agents: agents.map(a => ({ ...a })),
    rules: [...rules],
    profiles: PROFILES,
    buildings: buildings.map(b => ({ ...b, contributors: [...b.contributors] })),
    animals: animals.map(a => ({ ...a })),
    billboard: billboard.map(p => ({ ...p })),
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

  // ── Animal chaos layer (W8): the cat & dog act on a SLOW cadence (every Nth
  //    tick), most ticks reflex, occasionally a chaotic in-character escalation.
  if (tick % ANIMAL_ACT_EVERY_N_TICKS === 0) {
    events.push(...advanceAnimals());
  }

  // ── Sim texture (W11b): billboard posts, reflections, commitments + the
  //    phantom-lapse sweep — the new feed surfaces look real offline (§7).
  events.push(...advanceSimTexture(actor, turnId));

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
    tick_interval_seconds: tickIntervalSeconds,
    places: PLACES,
    agents: agents.map(a => ({ ...a })),
    rules: rules.map(r => ({ ...r })),
    profiles: PROFILES,
    buildings: buildings.map(b => ({ ...b, contributors: [...b.contributors] })),
    animals: animals.map(a => ({ ...a })),
    billboard: billboard.map(p => ({ ...p })),
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
    tick_interval_seconds: tickIntervalSeconds,
    places: PLACES,
    agents: agents.map(a => ({ ...a })),
    rules: rules.map(r => ({ ...r })),
    profiles: PROFILES,
    buildings: buildings.map(b => ({ ...b, contributors: [...b.contributors] })),
    animals: animals.map(a => ({ ...a })),
    billboard: billboard.map(p => ({ ...p })),
  };
  return { state, events };
}

// ── God billboard reply (W11b EM-091d) — mirrors POST /api/billboard ─────────

/**
 * Synthesize a god reply on the notice board: updates the billboard state and
 * emits billboard_posted with actor_type:"god" (the same event the live
 * backend broadcasts over the WS). Returns the fresh world_state + the event.
 */
function postBillboardMock(text: string, inReplyTo?: string): { state: WorldState; events: WorldEvent[] } {
  const trimmed = text.trim().slice(0, 280);
  pushBillboardPost({ tick, actor_id: 'god', actor_type: 'god', text: trimmed });
  const evt: WorldEvent = {
    type: 'event',
    seq: nextSeq(),
    tick,
    kind: 'billboard_posted',
    actor_id: 'god',
    target_id: null,
    profile: null,
    profile_color: null,
    text: `✦ The watchers answer on the billboard: “${trimmed}”`,
    payload: { place: 'plaza', text: trimmed, ...(inReplyTo ? { in_reply_to: inReplyTo } : {}) },
    ts: new Date().toISOString(),
    turn_id: null,
    actor_type: 'god',
    sim_time: Math.round(tick * TICK_INTERVAL * 1000) / 1000,
  };
  const state: WorldState = {
    type: 'world_state',
    seq: nextSeq(),
    tick, day, running,
    tick_interval_seconds: tickIntervalSeconds,
    places: PLACES,
    agents: agents.map(a => ({ ...a })),
    rules: rules.map(r => ({ ...r })),
    profiles: PROFILES,
    buildings: buildings.map(b => ({ ...b, contributors: [...b.contributors] })),
    animals: animals.map(a => ({ ...a })),
    billboard: billboard.map(p => ({ ...p })),
  };
  return { state, events: [evt] };
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
  /** W11b (EM-091d): god reply on the billboard — mirrors POST /api/billboard. */
  postBillboard: (text: string, inReplyTo?: string) => postBillboardMock(text, inReplyTo),
  isRunning: () => running,
  getProfiles: () => PROFILES,
  /** W10/D5: mirror the live backend — speed changes land in world_state. */
  setSpeed: (seconds: number) => { tickIntervalSeconds = seconds; },
  /**
   * EM-084: NEW RUN — rebuild the generator's seed world (mirrors the
   * backend's POST /api/control/reset, which resets from config). Returns the
   * fresh initial world_state. Seq restarts at 0; the caller clears its
   * feed/history first so old seqs can't collide. Note: SEED_AGENTS share
   * nested objects with the live roster (shallow clones), so beliefs/
   * relationships are re-created fresh here.
   */
  reset: (): WorldState => {
    tick = 0;
    day = 0;
    seq = 0;
    running = true;
    agents = SEED_AGENTS.map(a => ({ ...a, beliefs: [...a.beliefs], relationships: {} }));
    rules = [];
    openRuleId = null;
    ruleCounter = 0;
    buildings = [];
    buildingCounter = 0;
    lastActivityTick.clear();
    animals = seedAnimals();
    billboard = [];
    openCommitments = [];
    commitmentCounter = 0;
    spawnCounter = 0;
    tickIntervalSeconds = TICK_INTERVAL; // config value, like a backend reset
    seedRng(0);
    return buildInitialWorldState();
  },
};
