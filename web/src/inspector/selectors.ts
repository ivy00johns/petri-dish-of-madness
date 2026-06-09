// ============================================================
// Inspector selectors — PURE functions over WorldEvent[] (+ snapshots).
//
// These mirror the backend get_* methods (event-log.md §7) client-side so the
// five inspector panels render in MOCK mode with no backend, and identically
// in live mode. Everything here is a pure projection of the rolling history
// (`useSimulation.history`, newest-first) into a panel view-model.
//
// Invariants honored:
//   - The event log is append-only; selectors never mutate input.
//   - One agent turn = one turn_id (chain rows + domain events it caused).
//   - Unknown kinds are tolerated (default-rendered, never crash).
//   - A scrub at tick T projects state as of T (events with tick <= T).
// ============================================================

import type { Agent, ModelProfile, WorldEvent, EventKind } from '../types';
import type {
  TurnTrace,
  TraceSpan,
  TraceUsage,
  GovTimelineEntry,
  GovVote,
  GovDownstream,
  SocialGraphData,
  SocialNode,
  SocialEdge,
  AwiSummary,
  AwiByModel,
  ReplayFrame,
  ReplayAgentPos,
} from './types';

// ── small payload helpers (open payloads → typed reads, null-safe) ───────────

function payload(e: WorldEvent): Record<string, unknown> {
  return e.payload ?? {};
}

function num(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function str(v: unknown): string | null {
  return typeof v === 'string' ? v : null;
}

function strArr(v: unknown): string[] | null {
  return Array.isArray(v) && v.every((x) => typeof x === 'string') ? (v as string[]) : null;
}

/** Numeric record (e.g. state_deltas) — keeps only finite-number values. */
function numRecord(v: unknown): Record<string, number> {
  const out: Record<string, number> = {};
  if (v && typeof v === 'object') {
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      if (typeof val === 'number' && Number.isFinite(val)) out[k] = val;
    }
  }
  return out;
}

/** Sort a copy of events oldest-first (the history ref is newest-first). */
function ascending(events: WorldEvent[]): WorldEvent[] {
  return [...events].sort((a, b) => a.seq - b.seq);
}

/** Events at or before tick T (a scrub projection), oldest-first. */
function upToTick(events: WorldEvent[], tick: number): WorldEvent[] {
  return ascending(events).filter((e) => e.tick <= tick);
}

// ── maxTick / ticks present ──────────────────────────────────────────────────

export function maxTick(events: WorldEvent[]): number {
  let max = 0;
  for (const e of events) if (e.tick > max) max = e.tick;
  return max;
}

// ── Decision trace (EM-056) — get_turn_trace mirror ──────────────────────────

/** Chain order for stable display when seqs interleave (event-log.md §3). */
const CHAIN_ORDER: Record<string, number> = {
  turn_start: 0,
  perceived: 1,
  memory_retrieved: 2,
  llm_call: 3,
  reasoning: 4,
  action_chosen: 5,
  action_resolved: 6,
};

function spanFrom(e: WorldEvent): TraceSpan {
  return {
    seq: e.seq,
    tick: e.tick,
    kind: e.kind,
    text: e.text ?? null,
    payload: payload(e),
    ts: e.ts ?? null,
  };
}

function usageFromLlmCall(e: WorldEvent): TraceUsage {
  const p = payload(e);
  return {
    requestModel: str(p['gen_ai.request.model']),
    responseModel: str(p['gen_ai.response.model']) ?? str(p['routed_via']),
    inputTokens: num(p['gen_ai.usage.input_tokens']),
    outputTokens: num(p['gen_ai.usage.output_tokens']),
    latencyMs: num(p['latency_ms']),
    finishReasons: strArr(p['gen_ai.response.finish_reasons']),
    cached: p['cached'] === true,
    attempt: num(p['attempt']),
  };
}

/** The full decision-trace view-model for one turn, or null if absent. */
export function turnTrace(events: WorldEvent[], turnId: string): TurnTrace | null {
  const chain = ascending(events)
    .filter((e) => e.turn_id === turnId)
    .sort((a, b) => {
      const oa = CHAIN_ORDER[a.kind as string];
      const ob = CHAIN_ORDER[b.kind as string];
      // Known chain kinds order by their canonical position; everything else
      // (domain events the turn caused) keeps seq order after the chain.
      if (oa !== undefined && ob !== undefined) return oa - ob || a.seq - b.seq;
      if (oa !== undefined) return -1;
      if (ob !== undefined) return 1;
      return a.seq - b.seq;
    });
  if (chain.length === 0) return null;

  const llm = chain.find((e) => e.kind === 'llm_call');
  const resolved = chain.find((e) => e.kind === 'action_resolved');
  const chosen = chain.find((e) => e.kind === 'action_chosen');
  const head = chain.find((e) => e.kind === 'turn_start') ?? chain[0];

  const outcomeRaw = resolved ? str(payload(resolved)['outcome']) : null;
  const outcome =
    outcomeRaw === 'ok' || outcomeRaw === 'gated' || outcomeRaw === 'failed'
      ? outcomeRaw
      : null;

  return {
    turnId,
    tick: head.tick,
    agentId: head.actor_id ?? null,
    profile: head.profile ?? null,
    spans: chain.map(spanFrom),
    usage: llm ? usageFromLlmCall(llm) : null,
    outcome,
    stateDeltas: resolved ? numRecord(payload(resolved)['state_deltas']) : {},
    chosenTool: chosen ? str(payload(chosen)['chosen_tool']) : null,
  };
}

/** All turn_ids present in history (newest turn first), for a trace picker. */
export function turnIds(events: WorldEvent[]): Array<{ turnId: string; tick: number; agentId: string | null }> {
  const seen = new Map<string, { tick: number; agentId: string | null }>();
  for (const e of events) {
    if (!e.turn_id) continue;
    if (!seen.has(e.turn_id)) {
      seen.set(e.turn_id, { tick: e.tick, agentId: e.actor_id ?? null });
    }
  }
  return [...seen.entries()]
    .map(([turnId, v]) => ({ turnId, tick: v.tick, agentId: v.agentId }))
    .sort((a, b) => b.tick - a.tick || b.turnId.localeCompare(a.turnId));
}

// ── Governance history (EM-057) — get_rule_history mirror ────────────────────

const PROPOSE_KINDS = new Set<EventKind>(['rule_proposed']);
const VOTE_KINDS = new Set<EventKind>(['rule_vote']);
const PASS_KINDS = new Set<EventKind>(['rule_passed']);
const REJECT_KINDS = new Set<EventKind>(['rule_rejected']);

function ruleIdOf(e: WorldEvent): string | null {
  const p = payload(e);
  return str(p['rule_id']) ?? str(p['id']) ?? (e.target_id ?? null);
}

/**
 * Build the per-rule lifecycle + downstream-consequence links.
 * Downstream = later events (economy / agent_died / …) sharing the rule's
 * turn_id, OR tagged with this rule_id in their payload (mirrors the backend
 * downstream[] links). Honors append-only ordering (seq).
 */
export function governanceTimeline(events: WorldEvent[]): GovTimelineEntry[] {
  const asc = ascending(events);
  const entries = new Map<string, GovTimelineEntry>();
  // turn_id → rule_id, so downstream domain events can be linked back.
  const ruleByTurn = new Map<string, string>();

  for (const e of asc) {
    const ruleId = ruleIdOf(e);
    if (PROPOSE_KINDS.has(e.kind)) {
      if (!ruleId) continue;
      if (!entries.has(ruleId)) {
        entries.set(ruleId, {
          ruleId,
          effect: str(payload(e)['effect']),
          text: e.text ?? str(payload(e)['text']),
          proposerId: e.actor_id ?? null,
          status: 'proposed',
          createdTick: e.tick,
          votes: [],
          resolvedTick: null,
          outcome: null,
          downstream: [],
        });
      }
      if (e.turn_id) ruleByTurn.set(e.turn_id, ruleId);
    } else if (VOTE_KINDS.has(e.kind)) {
      const entry = ruleId ? entries.get(ruleId) : firstOpenRule(entries);
      if (!entry || !e.actor_id) continue;
      const choice = readVoteChoice(e);
      const vote: GovVote = { voterId: e.actor_id, choice, tick: e.tick };
      entry.votes.push(vote);
      if (e.turn_id) ruleByTurn.set(e.turn_id, entry.ruleId);
    } else if (PASS_KINDS.has(e.kind)) {
      const entry = ruleId ? entries.get(ruleId) : firstOpenRule(entries);
      if (!entry) continue;
      entry.status = 'active';
      entry.outcome = 'passed';
      entry.resolvedTick = e.tick;
      if (e.turn_id) ruleByTurn.set(e.turn_id, entry.ruleId);
    } else if (REJECT_KINDS.has(e.kind)) {
      const entry = ruleId ? entries.get(ruleId) : firstOpenRule(entries);
      if (!entry) continue;
      entry.status = 'rejected';
      entry.outcome = 'rejected';
      entry.resolvedTick = e.tick;
    }
  }

  // Second pass: attach downstream consequences (events caused by a passed
  // rule's turn, or carrying an explicit rule_id, after it resolved).
  for (const e of asc) {
    if (
      PROPOSE_KINDS.has(e.kind) ||
      VOTE_KINDS.has(e.kind) ||
      PASS_KINDS.has(e.kind) ||
      REJECT_KINDS.has(e.kind)
    ) {
      continue;
    }
    const explicitRule = str(payload(e)['rule_id']);
    const linkedRule = explicitRule ?? (e.turn_id ? ruleByTurn.get(e.turn_id) ?? null : null);
    if (!linkedRule) continue;
    const entry = entries.get(linkedRule);
    if (!entry) continue;
    // Only count it as a consequence if it lands at/after the rule resolved
    // (or at/after it was created when still open) — that's the causal window.
    const since = entry.resolvedTick ?? entry.createdTick;
    if (e.tick < since) continue;
    const down: GovDownstream = { seq: e.seq, tick: e.tick, kind: e.kind, text: e.text ?? null };
    entry.downstream.push(down);
  }

  return [...entries.values()].sort((a, b) => a.createdTick - b.createdTick);
}

function firstOpenRule(entries: Map<string, GovTimelineEntry>): GovTimelineEntry | null {
  for (const entry of entries.values()) {
    if (entry.status === 'proposed') return entry;
  }
  return null;
}

function readVoteChoice(e: WorldEvent): boolean {
  const p = payload(e);
  const c = p['choice'] ?? p['vote'] ?? p['yes'];
  if (typeof c === 'boolean') return c;
  if (typeof c === 'string') return /^(y|yes|true|aye|for)$/i.test(c);
  // Fall back to the feed text ("votes YES on …").
  return /\bYES\b/.test(e.text ?? '');
}

// ── Social graph (EM-058) — get_relationship_timeline mirror ─────────────────

const REL_KINDS = new Set<EventKind>(['relationship']);
const GIVE_KINDS = new Set<EventKind>(['economy']);
const CONFLICT_KINDS = new Set<EventKind>(['conflict']);

interface EdgeAccum {
  type: string;
  trust: number;
  interactions: number;
}

function edgeKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

/**
 * The relationship graph AS OF `atTick` — fold relationship/conflict/gift
 * events (oldest→`atTick`) into directed-ish edges, color nodes by model.
 * Time-scrubbable: pass a smaller `atTick` to rewind the graph.
 */
export function socialGraph(
  events: WorldEvent[],
  agents: Agent[],
  atTick: number,
): SocialGraphData {
  const profileColor = new Map<string, string>();
  for (const a of agents) {
    if (a.profile && a.profile_color) profileColor.set(a.profile, a.profile_color);
  }

  // Track which agents are alive at the scrub tick from death events.
  const deadByTick = new Map<string, number>();
  for (const e of ascending(events)) {
    if (e.kind === 'agent_died' && e.actor_id) deadByTick.set(e.actor_id, e.tick);
  }

  const nodes: SocialNode[] = agents.map((a) => {
    const diedAt = deadByTick.get(a.id);
    const alive = diedAt === undefined ? a.alive : atTick < diedAt;
    return {
      id: a.id,
      label: a.name,
      // Data-driven color from the model profile. Empty when none is known;
      // the VIEW resolves the neutral token (data layer stays color-literal-free).
      color: a.profile_color ?? profileColor.get(a.profile) ?? '',
      alive,
    };
  });

  const edges = new Map<string, EdgeAccum>();
  const bump = (a: string, b: string, type: string, trustDelta: number) => {
    const key = edgeKey(a, b);
    const cur = edges.get(key) ?? { type, trust: 0, interactions: 0 };
    cur.type = type;
    cur.trust = Math.max(-100, Math.min(100, cur.trust + trustDelta));
    cur.interactions += 1;
    edges.set(key, cur);
  };

  for (const e of upToTick(events, atTick)) {
    const a = e.actor_id;
    const b = e.target_id;
    if (!a || !b) continue;
    if (REL_KINDS.has(e.kind)) {
      const type = str(payload(e)['type']) ?? inferRelType(e.text);
      const trust = num(payload(e)['trust_delta']) ?? (type === 'rival' || type === 'enemy' ? -20 : 20);
      bump(a, b, type, trust);
    } else if (GIVE_KINDS.has(e.kind) && isGift(e)) {
      bump(a, b, 'ally', 10);
    } else if (CONFLICT_KINDS.has(e.kind)) {
      bump(a, b, 'rival', -15);
    }
  }

  // Seed from the live agent relationship maps too (so a fresh world isn't
  // empty before any relationship event has fired) — only forward edges.
  for (const a of agents) {
    for (const [otherId, rel] of Object.entries(a.relationships ?? {})) {
      if (rel.interactions === 0 && rel.trust === 0 && rel.type === 'neutral') continue;
      const key = edgeKey(a.id, otherId);
      if (!edges.has(key)) {
        edges.set(key, { type: rel.type, trust: rel.trust, interactions: rel.interactions });
      }
    }
  }

  const edgeList: SocialEdge[] = [...edges.entries()].map(([key, v]) => {
    const [source, target] = key.split('|');
    return { source, target, type: v.type, trust: v.trust };
  });

  return { nodes, edges: edgeList };
}

function isGift(e: WorldEvent): boolean {
  const p = payload(e);
  if (str(p['action']) === 'give' || p['gift'] === true) return true;
  return /\bgive|gift|shares?\b/i.test(e.text ?? '');
}

function inferRelType(text: string | null | undefined): string {
  const t = (text ?? '').toLowerCase();
  if (t.includes('ally') || t.includes('friend')) return 'ally';
  if (t.includes('rival') || t.includes('enemy')) return 'rival';
  return 'neutral';
}

// ── AWI dashboard (EM-059) — get_analytics mirror ────────────────────────────

const CRIME_KINDS: Record<string, true> = { conflict: true };

function emptyByModel(): AwiByModel {
  return { alive: 0, dead: 0, crimes: 0, gives: 0, proposals: 0, passed: 0, creditShare: 0 };
}

/**
 * The 9-AWI + model-vs-model spine, computed from events in [from, to].
 * NO composite score (event-log.md §7) — nine indicators side by side, with
 * the per-model differentiator cut. Tolerates an empty range gracefully.
 */
export function awiSummary(
  events: WorldEvent[],
  range: { fromTick?: number; toTick?: number } = {},
  agents: Agent[] = [],
  profiles: ModelProfile[] = [],
): AwiSummary {
  const from = range.fromTick ?? 0;
  const to = range.toTick ?? maxTick(events);
  const inRange = ascending(events).filter((e) => e.tick >= from && e.tick <= to);

  const crimeByKind: Record<string, number> = {};
  const toolsByAgent: Record<string, Set<string>> = {};
  const placesByAgent: Record<string, Set<string>> = {};
  const sayByAgent: Record<string, number> = {};
  let say = 0;
  let proposeRule = 0;
  let proposed = 0;
  let passed = 0;
  let rejected = 0;
  let voteEvents = 0;
  const voters = new Set<string>();
  const socialByType: Record<string, number> = {};
  const socialEdges = new Set<string>();
  let economyThroughput = 0;
  const populationByTick = new Map<number, number>();
  const byModel: Record<string, AwiByModel> = {};
  const usageByProfile: Record<string, { requests: number; inputTokens: number; outputTokens: number }> = {};

  // Seed per-model rows for every known profile so the cut is never blank.
  for (const p of profiles) byModel[p.name] = emptyByModel();
  const ensureModel = (name: string | null | undefined): AwiByModel | null => {
    if (!name) return null;
    if (!byModel[name]) byModel[name] = emptyByModel();
    return byModel[name];
  };

  for (const e of inRange) {
    const p = payload(e);
    const model = ensureModel(e.profile);

    // Crime (the 'crime' indicator + per-model crimes).
    const crimeKind = str(p['crime_kind']) ?? (CRIME_KINDS[e.kind as string] ? stealOrAttack(e) : null);
    if (crimeKind) {
      crimeByKind[crimeKind] = (crimeByKind[crimeKind] ?? 0) + 1;
      if (model) model.crimes += 1;
    }

    // Tool / space exploration.
    if (e.actor_id) {
      const tool = str(p['chosen_tool']) ?? (e.kind === 'action_chosen' ? str(p['tool']) : null);
      if (tool) (toolsByAgent[e.actor_id] ??= new Set()).add(tool);
      if (e.kind === 'agent_moved') {
        const place = str(p['to']) ?? str(p['location']);
        if (place) (placesByAgent[e.actor_id] ??= new Set()).add(place);
      }
    }

    // Public expression.
    if (e.kind === 'agent_speech') {
      say += 1;
      if (e.actor_id) sayByAgent[e.actor_id] = (sayByAgent[e.actor_id] ?? 0) + 1;
    }
    if (e.kind === 'rule_proposed') {
      proposeRule += 1;
      proposed += 1;
      if (model) model.proposals += 1;
    }
    if (e.kind === 'rule_passed') {
      passed += 1;
      if (model) model.passed += 1;
    }
    if (e.kind === 'rule_rejected') rejected += 1;
    if (e.kind === 'rule_vote') {
      voteEvents += 1;
      if (e.actor_id) voters.add(e.actor_id);
    }

    // Social fabric (edges by relationship type).
    if (e.kind === 'relationship' && e.actor_id && e.target_id) {
      const type = str(p['type']) ?? inferRelType(e.text);
      socialByType[type] = (socialByType[type] ?? 0) + 1;
      socialEdges.add(edgeKey(e.actor_id, e.target_id));
    }

    // Economy throughput + per-model gives.
    if (e.kind === 'economy') {
      const amount = num(p['amount']) ?? num(p['credits']) ?? 1;
      economyThroughput += Math.abs(amount);
      if (isGift(e) && model) model.gives += 1;
    }

    // Usage (EM-067) — read llm_call rows; tolerate null tokens.
    if (e.kind === 'llm_call') {
      const name = str(p['gen_ai.request.model']) ?? e.profile;
      if (name) {
        const u = (usageByProfile[name] ??= { requests: 0, inputTokens: 0, outputTokens: 0 });
        u.requests += 1;
        u.inputTokens += num(p['gen_ai.usage.input_tokens']) ?? 0;
        u.outputTokens += num(p['gen_ai.usage.output_tokens']) ?? 0;
      }
    }

    // Population: prefer an explicit alive count carried on turn_start/world
    // events; otherwise leave it to the agents-derived fallback below.
    const aliveCount = num(p['alive']) ?? num(p['population']);
    if (aliveCount !== null) populationByTick.set(e.tick, aliveCount);
  }

  // Per-model alive/dead + credit share from the live agent snapshot.
  let totalCredits = 0;
  const economyByAgent: Record<string, number> = {};
  for (const a of agents) {
    totalCredits += Math.max(0, a.credits);
    economyByAgent[a.id] = a.credits;
    const model = ensureModel(a.profile);
    if (model) {
      if (a.alive) model.alive += 1;
      else model.dead += 1;
    }
  }
  if (totalCredits > 0) {
    for (const a of agents) {
      const model = ensureModel(a.profile);
      if (model) model.creditShare += Math.max(0, a.credits) / totalCredits;
    }
  }

  // Population series: if no explicit counts were carried, synthesize from
  // death events (start = all agents, decrement at each death tick).
  const population = buildPopulation(populationByTick, inRange, agents, from, to);

  const participation = agents.length > 0 ? voters.size / agents.length : 0;

  const gini = giniCoefficient(agents.map((a) => Math.max(0, a.credits)));

  // Active rules / amendments from the governance lifecycle.
  const gov = governanceTimeline(events);
  const activeRules = gov.filter((r) => r.status === 'active').length;
  const amendments = gov.length;

  return {
    population,
    crime: { byKind: crimeByKind },
    toolExploration: { byAgent: mapSetCounts(toolsByAgent) },
    spaceExploration: { byAgent: mapSetCounts(placesByAgent) },
    governance: { participation, proposed, passed, rejected },
    publicExpression: { say, proposeRule },
    socialFabric: { edges: socialEdges.size, byType: socialByType },
    economy: { gini, throughput: economyThroughput, byAgent: economyByAgent },
    constitution: { activeRules, amendments },
    byModel,
    usage: { byProfile: usageByProfile },
  };
}

function stealOrAttack(e: WorldEvent): string {
  const t = (e.text ?? '').toLowerCase();
  if (t.includes('steal')) return 'steal';
  if (t.includes('attack')) return 'attack';
  if (t.includes('insult')) return 'insult';
  if (t.includes('arson') || t.includes('burn')) return 'arson';
  return 'conflict';
}

function mapSetCounts(m: Record<string, Set<string>>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, set] of Object.entries(m)) out[k] = set.size;
  return out;
}

function buildPopulation(
  explicit: Map<number, number>,
  inRange: WorldEvent[],
  agents: Agent[],
  from: number,
  to: number,
): Array<{ tick: number; alive: number }> {
  if (explicit.size > 0) {
    return [...explicit.entries()].map(([tick, alive]) => ({ tick, alive })).sort((a, b) => a.tick - b.tick);
  }
  // Synthesize: start from the full roster, drop one at each death tick.
  const deaths = inRange.filter((e) => e.kind === 'agent_died').sort((a, b) => a.tick - b.tick);
  if (deaths.length === 0) {
    const alive = agents.filter((a) => a.alive).length || agents.length;
    return [
      { tick: from, alive },
      { tick: to, alive },
    ];
  }
  const series: Array<{ tick: number; alive: number }> = [];
  let alive = agents.length;
  series.push({ tick: from, alive });
  for (const d of deaths) {
    alive = Math.max(0, alive - 1);
    series.push({ tick: d.tick, alive });
  }
  series.push({ tick: to, alive });
  return series;
}

/** Gini coefficient of a credit distribution (0 = equal, →1 = unequal). */
function giniCoefficient(values: number[]): number {
  const v = values.filter((x) => x >= 0);
  const n = v.length;
  if (n === 0) return 0;
  const sum = v.reduce((s, x) => s + x, 0);
  if (sum === 0) return 0;
  const sorted = [...v].sort((a, b) => a - b);
  let cum = 0;
  for (let i = 0; i < n; i++) cum += (i + 1) * sorted[i];
  return (2 * cum) / (n * sum) - (n + 1) / n;
}

// ── Replay (EM-055) — replayStateAt: fold history (+snapshots) to a tick ──────

/** Snapshot row shape the replay fold consumes (subset of world_state). */
export interface ReplaySnapshot {
  tick: number;
  /** Minimal positional state: agentId → place id, plus place coords. */
  agents?: Array<{ id: string; location: string; profile?: string | null; alive?: boolean }>;
  places?: Array<{ id: string; x: number; y: number }>;
}

/**
 * World positions at `tick`, for the top-down Canvas2D replay map (EM-055).
 * Folds the nearest prior snapshot forward through agent_moved / agent_died
 * events up to `tick`. With no snapshots (mock), starts from the agent roster
 * and replays movement. Pure: never mutates inputs.
 */
export function replayStateAt(
  events: WorldEvent[],
  snapshots: ReplaySnapshot[],
  tick: number,
  agents: Agent[],
  places: Array<{ id: string; x: number; y: number }>,
): ReplayFrame {
  const placeXY = new Map<string, { x: number; y: number }>();
  for (const p of places) placeXY.set(p.id, { x: p.x, y: p.y });

  // Base: nearest snapshot at tick <= T, else the live roster's start.
  const base = nearestSnapshot(snapshots, tick);
  const location = new Map<string, string>();
  const profileOf = new Map<string, string | null>();
  const aliveOf = new Map<string, boolean>();

  for (const a of agents) {
    location.set(a.id, a.location);
    profileOf.set(a.id, a.profile ?? null);
    aliveOf.set(a.id, true);
  }
  if (base) {
    for (const a of base.agents ?? []) {
      location.set(a.id, a.location);
      if (a.profile !== undefined) profileOf.set(a.id, a.profile);
      if (a.alive !== undefined) aliveOf.set(a.id, a.alive);
    }
    for (const p of base.places ?? []) placeXY.set(p.id, { x: p.x, y: p.y });
  }

  const fromTick = base?.tick ?? 0;
  for (const e of ascending(events)) {
    if (e.tick <= fromTick || e.tick > tick) continue;
    if (e.kind === 'agent_moved' && e.actor_id) {
      const to = str(payload(e)['to']) ?? str(payload(e)['location']) ?? e.target_id;
      if (to && placeXY.has(to)) location.set(e.actor_id, to);
    } else if (e.kind === 'agent_died' && e.actor_id) {
      aliveOf.set(e.actor_id, false);
    }
  }

  const profileColor = new Map<string, string>();
  for (const a of agents) if (a.profile && a.profile_color) profileColor.set(a.profile, a.profile_color);

  const agentPositions: ReplayAgentPos[] = [];
  for (const a of agents) {
    const loc = location.get(a.id) ?? a.location;
    const xy = placeXY.get(loc) ?? { x: 500, y: 500 };
    const prof = profileOf.get(a.id) ?? a.profile ?? null;
    agentPositions.push({
      id: a.id,
      x: xy.x,
      y: xy.y,
      profile: prof,
      // Data-driven model color; empty when unknown — the VIEW resolves the
      // neutral token (keeps the data layer free of color literals).
      color: a.profile_color ?? (prof ? profileColor.get(prof) ?? '' : ''),
      alive: aliveOf.get(a.id) ?? a.alive,
    });
  }

  const eventsAtTick = ascending(events).filter((e) => e.tick === tick);

  return { tick, agents: agentPositions, eventsAtTick };
}

/** Nearest snapshot with tick <= T (replay cost bound, event-log.md §5). */
export function nearestSnapshot(snapshots: ReplaySnapshot[], tick: number): ReplaySnapshot | null {
  let best: ReplaySnapshot | null = null;
  for (const s of snapshots) {
    if (s.tick <= tick && (best === null || s.tick > best.tick)) best = s;
  }
  return best;
}

// ── Replay markers (EM-055) — color-coded by type, for the timeline ──────────

export type MarkerCategory = 'crime' | 'governance' | 'construction' | 'animal' | 'trace' | 'other';

/** Classify an event into the scrubber's color-coded marker categories. */
export function markerCategory(e: WorldEvent): MarkerCategory {
  if (e.actor_type === 'animal' || e.kind === 'animal_action' || e.kind === 'animal_spawned') {
    return 'animal';
  }
  if (e.kind === 'conflict') return 'crime';
  if (
    e.kind === 'rule_proposed' ||
    e.kind === 'rule_vote' ||
    e.kind === 'rule_passed' ||
    e.kind === 'rule_rejected'
  ) {
    return 'governance';
  }
  if (
    e.kind === 'project_proposed' ||
    e.kind === 'project_contributed' ||
    e.kind === 'project_completed' ||
    e.kind === 'structure_state_changed'
  ) {
    return 'construction';
  }
  if (
    e.kind === 'perceived' ||
    e.kind === 'memory_retrieved' ||
    e.kind === 'llm_call' ||
    e.kind === 'reasoning' ||
    e.kind === 'action_chosen' ||
    e.kind === 'action_resolved'
  ) {
    return 'trace';
  }
  return 'other';
}
