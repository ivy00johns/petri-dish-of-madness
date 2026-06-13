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

import type { Agent, Animal, Building, BuildingStatus, ModelProfile, WorldEvent, EventKind } from '../types';
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
  ReplayBuildingState,
  ReplayAnimalPos,
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

// Wave F (EM-194): the ascending sort used to run PER SELECTOR CALL — at a
// 50k-event history a single scrub step paid 4–6 O(n log n) sorts. The sorted
// copy is now cached per events-array reference (WeakMap: a dropped history
// ref frees its cache entry). The cached array is shared READ-ONLY by every
// selector — none mutates it (filters/maps produce fresh arrays) — and the
// comparator is unchanged, so results stay byte-identical.
const ascendingCache = new WeakMap<WorldEvent[], WorldEvent[]>();

/** Sorted copy of events oldest-first by seq (cached per array reference). */
export function sortedBySeqAsc(events: WorldEvent[]): WorldEvent[] {
  const cached = ascendingCache.get(events);
  if (cached) return cached;
  const sorted = [...events].sort((a, b) => a.seq - b.seq);
  ascendingCache.set(events, sorted);
  return sorted;
}

/** Sort a copy of events oldest-first (the history ref is newest-first). */
function ascending(events: WorldEvent[]): WorldEvent[] {
  return sortedBySeqAsc(events);
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

// Wave E (EM-113/B6): typed-bond transitions. payload carries the ABSOLUTE
// post-transition state {from_type, to_type, trust, since_tick} — the fold
// SETS type/trust rather than bumping a delta.
const REL_CHANGED_KINDS = new Set<EventKind>(['relationship_changed']);

/** Wave E (EM-120/B6): faction membership at a tick, folded from faction_*
 *  events (≤ atTick, oldest-first). Pure; tolerant of partial payloads.
 *  Last-write-wins when an agent's faction changes (formed/joined override;
 *  left/dissolved clear). */
export function factionMembership(
  events: WorldEvent[],
  atTick: number,
): Map<string, { id: string; name: string }> {
  const byAgent = new Map<string, { id: string; name: string }>();
  for (const e of upToTick(events, atTick)) {
    const p = payload(e);
    const fid = str(p['faction_id']);
    if (!fid) continue;
    const name = str(p['name']) ?? fid;
    if (e.kind === 'faction_formed') {
      for (const m of strArr(p['members']) ?? []) byAgent.set(m, { id: fid, name });
    } else if (e.kind === 'faction_joined' && e.actor_id) {
      byAgent.set(e.actor_id, { id: fid, name });
    } else if (e.kind === 'faction_left' && e.actor_id) {
      if (byAgent.get(e.actor_id)?.id === fid) byAgent.delete(e.actor_id);
    } else if (e.kind === 'faction_dissolved') {
      for (const [agentId, f] of [...byAgent.entries()]) {
        if (f.id === fid) byAgent.delete(agentId);
      }
    }
  }
  return byAgent;
}

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

  // Wave E (EM-120): faction membership at the scrub tick rides the nodes so
  // the graph can ring/tint member nodes (faction_* events carry agent ids).
  const factions = factionMembership(events, atTick);

  const nodes: SocialNode[] = agents.map((a) => {
    const diedAt = deadByTick.get(a.id);
    const alive = diedAt === undefined ? a.alive : atTick < diedAt;
    const faction = factions.get(a.id) ?? null;
    return {
      id: a.id,
      label: a.name,
      // Data-driven color from the model profile. Empty when none is known;
      // the VIEW resolves the neutral token (data layer stays color-literal-free).
      color: a.profile_color ?? profileColor.get(a.profile) ?? '',
      alive,
      factionId: faction?.id ?? null,
      factionName: faction?.name ?? null,
    };
  });

  // Edges may only connect graph NODES. Conflict/economy events can carry a
  // BUILDING as target_id (arson, project funding) — feeding those into the
  // force layout threw "node not found: bld_…" and killed the whole panel on
  // building-heavy archived runs (run 189: 43 conflicts + 57 economy events
  // targeting buildings).
  const nodeIds = new Set(nodes.map((n) => n.id));

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
    if (!nodeIds.has(a) || !nodeIds.has(b) || a === b) continue;
    if (REL_KINDS.has(e.kind)) {
      const type = str(payload(e)['type']) ?? inferRelType(e.text);
      const trust = num(payload(e)['trust_delta']) ?? (type === 'rival' || type === 'enemy' ? -20 : 20);
      bump(a, b, type, trust);
    } else if (REL_CHANGED_KINDS.has(e.kind)) {
      // Wave E (EM-113): payload.to_type/trust are the ABSOLUTE post-transition
      // state — SET them (never accumulate). EM-141 holds: the nodeIds guard
      // above already dropped non-agent endpoints before this branch.
      const p = payload(e);
      const key = edgeKey(a, b);
      const cur = edges.get(key) ?? { type: 'neutral', trust: 0, interactions: 0 };
      cur.type = str(p['to_type']) ?? cur.type;
      const trust = num(p['trust']);
      if (trust !== null) cur.trust = Math.max(-100, Math.min(100, trust));
      cur.interactions += 1;
      edges.set(key, cur);
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
      if (!nodeIds.has(otherId) || otherId === a.id) continue;
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
  return { alive: 0, dead: 0, crimes: 0, gives: 0, proposals: 0, passed: 0, rejected: 0, creditShare: 0 };
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

  // Per-model governance attribution (audit C6): a pass/reject is credited to
  // the model whose agent PROPOSED the rule, so numerator and denominator
  // measure the same thing — proposals BY that model that passed, over
  // proposals BY that model that resolved (passed + rejected).
  const proposerModelByRule = new Map<string, string | null>();
  const openRuleIds: string[] = [];
  const resolveRuleModel = (e: WorldEvent): AwiByModel | null => {
    const rid = ruleIdOf(e) ?? openRuleIds[0] ?? null;
    if (!rid) return null;
    const idx = openRuleIds.indexOf(rid);
    if (idx >= 0) openRuleIds.splice(idx, 1);
    return ensureModel(proposerModelByRule.get(rid));
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
        // W9-QA-1: the backend emits the destination as payload.place
        // (runtime.py ground truth); `to`/`location` are tolerated fallbacks.
        const place = str(p['place']) ?? str(p['to']) ?? str(p['location']);
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
      const rid = ruleIdOf(e);
      if (rid) {
        proposerModelByRule.set(rid, e.profile ?? null);
        openRuleIds.push(rid);
      }
    }
    if (e.kind === 'rule_passed') {
      passed += 1;
      const proposerModel = resolveRuleModel(e);
      if (proposerModel) proposerModel.passed += 1;
    }
    if (e.kind === 'rule_rejected') {
      rejected += 1;
      const proposerModel = resolveRuleModel(e);
      if (proposerModel) proposerModel.rejected += 1;
    }
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
  /** W10/C7: building state at the snapshot tick (subset of world_state.buildings). */
  buildings?: Array<{
    id: string;
    name?: string;
    kind?: string;
    location?: string;
    status?: string;
    progress?: number;
  }>;
  /** W10/D4: animal roster at the snapshot tick. */
  animals?: Array<{
    id: string;
    name?: string;
    species?: string;
    location: string;
    alive?: boolean;
  }>;
}

/** The seven contract building statuses (world-model.md §W7) — used to validate
 *  open event payloads before they drive a glyph color. */
const BUILDING_STATUSES = new Set<BuildingStatus>([
  'planned',
  'under_construction',
  'operational',
  'damaged',
  'offline',
  'abandoned',
  'destroyed',
]);

function asBuildingStatus(v: unknown): BuildingStatus | null {
  return typeof v === 'string' && BUILDING_STATUSES.has(v as BuildingStatus)
    ? (v as BuildingStatus)
    : null;
}

/**
 * World positions at `tick`, for the top-down Canvas2D replay map (EM-055).
 * Folds the nearest prior snapshot forward through agent_moved / agent_died
 * events up to `tick`. With no snapshots (mock), starts from the agent roster
 * and replays movement. Pure: never mutates inputs.
 *
 * W10 additions:
 *   • Buildings (audit C7): `frame.buildings` is the building state AT `tick`,
 *     folded from snapshot buildings (base) + construction-lifecycle events —
 *     never the live roster's status. `liveBuildings` only fills display
 *     metadata (name/kind/location) for entries the event window can't name.
 *   • Animals (audit D4): `frame.animals` is a best-effort roster at `tick`
 *     (see the fold below for why animal positions are approximate).
 */
export function replayStateAt(
  events: WorldEvent[],
  snapshots: ReplaySnapshot[],
  tick: number,
  agents: Agent[],
  places: Array<{ id: string; x: number; y: number }>,
  liveBuildings: Building[] = [],
  liveAnimals: Animal[] = [],
): ReplayFrame {
  const inputs: ReplayFoldInputs = { agents, places, liveBuildings, liveAnimals };
  // Base: nearest snapshot at tick <= T, else the live roster's start.
  const base = nearestSnapshot(snapshots, tick);
  const state = replayFoldSeed(base, inputs);
  // Fold boundary (audit C4; event-log.md v1.1.0 §3 / api.openapi v1.2.0): a
  // snapshot at tick S is the state AFTER all tick-S events, so the fold is
  // STRICT-LEFT — keep events with base.tick < e.tick <= tick. With no snapshot
  // the fold starts before tick 0 (so tick-0 events apply).
  for (const e of ascending(events)) {
    if (e.tick > state.fromTick && e.tick <= tick) replayFoldStep(state, e);
  }
  const post: ReplayFoldPostWindow = {
    earliestLaterBuildingEvent: (buildingId) => {
      let earliest: WorldEvent | null = null;
      for (const e of events) {
        if (e.tick <= tick) continue;
        const bid = str(payload(e)['building_id']) ?? e.target_id;
        if (bid !== buildingId) continue;
        if (earliest === null || e.seq < earliest.seq) earliest = e;
      }
      return earliest;
    },
    spawnsAfterTick: ascending(events).filter(
      (e) => e.tick > tick && e.kind === 'animal_spawned' && !!e.actor_id,
    ),
    eventsAtTick: ascending(events).filter((e) => e.tick === tick),
  };
  return replayFoldFinalize(state, tick, inputs, post);
}

// ── Wave F (EM-194) — the replay fold decomposed into seed / step / finalize ──
//
// replayStateAt above ≡ finalize(advance(seed(base, inputs), window), …): seed
// the fold state from the nearest snapshot, advance it one event at a time
// through the strict-left window (fromTick < e.tick <= T), then finalize into a
// ReplayFrame. The incremental scrub projector (projections.ts) reuses these
// SAME pieces with a persistent cursor + checkpoint LRU, so a frame computed
// incrementally is equal to the full fold by construction.

/** Animal accumulator inside the replay fold (best-effort positions, D4). */
export interface ReplayAnimalAcc {
  name: string;
  species: string;
  location: string;
  alive: boolean;
  approximate: boolean;
}

/** The non-event inputs the replay fold seeds/finalizes from. */
export interface ReplayFoldInputs {
  agents: Agent[];
  places: Array<{ id: string; x: number; y: number }>;
  liveBuildings: Building[];
  liveAnimals: Animal[];
}

/** Mutable replay fold state — the event-driven half of a ReplayFrame. */
export interface ReplayFoldState {
  /** Strict-left fold boundary (audit C4): events with tick > fromTick apply. */
  fromTick: number;
  /** Place coords (static after seeding — events never move places). */
  placeXY: Map<string, { x: number; y: number }>;
  location: Map<string, string>;
  profileOf: Map<string, string | null>;
  aliveOf: Map<string, boolean>;
  bld: Map<string, ReplayBuildingState>;
  ani: Map<string, ReplayAnimalAcc>;
}

function ensureBld(bld: Map<string, ReplayBuildingState>, id: string): ReplayBuildingState {
  let b = bld.get(id);
  if (!b) {
    b = { id, name: id, kind: '', location: '', status: 'planned', progress: 0 };
    bld.set(id, b);
  }
  return b;
}

/** Seed the fold state from the base snapshot (or the live rosters). */
export function replayFoldSeed(
  base: ReplaySnapshot | null,
  inputs: ReplayFoldInputs,
): ReplayFoldState {
  const placeXY = new Map<string, { x: number; y: number }>();
  for (const p of inputs.places) placeXY.set(p.id, { x: p.x, y: p.y });

  const location = new Map<string, string>();
  const profileOf = new Map<string, string | null>();
  const aliveOf = new Map<string, boolean>();
  for (const a of inputs.agents) {
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

  // W10 / audit C7 — building base: snapshot.buildings (state AFTER all
  // tick-base.tick events) when present; otherwise the fold starts EMPTY and
  // project_proposed / structure_state_changed events CREATE entries — the
  // live roster is never a status source (finalize fills display metadata).
  const bld = new Map<string, ReplayBuildingState>();
  for (const s of base?.buildings ?? []) {
    if (!s.id) continue;
    const b = ensureBld(bld, s.id);
    if (s.name) b.name = s.name;
    if (s.kind) b.kind = s.kind;
    if (s.location) b.location = s.location;
    const status = asBuildingStatus(s.status);
    if (status) b.status = status;
    if (typeof s.progress === 'number' && Number.isFinite(s.progress)) b.progress = s.progress;
  }

  // W10 / audit D4 — animal base: snapshot.animals (true roster at base.tick
  // ≤ T) when present, else the live roster flagged `approximate`.
  const ani = new Map<string, ReplayAnimalAcc>();
  if (base?.animals) {
    for (const a of base.animals) {
      if (!a.id || !a.location) continue;
      ani.set(a.id, {
        name: a.name ?? a.id,
        species: a.species ?? '',
        location: a.location,
        alive: a.alive ?? true,
        approximate: false,
      });
    }
  } else {
    for (const a of inputs.liveAnimals) {
      ani.set(a.id, {
        name: a.name,
        species: a.species,
        location: a.location,
        alive: a.alive,
        approximate: true,
      });
    }
  }

  return { fromTick: base ? base.tick : -1, placeXY, location, profileOf, aliveOf, bld, ani };
}

/**
 * ONE replay fold step. The caller enforces the strict-left window
 * (state.fromTick < e.tick <= T) and seq-ascending order. The agent, building
 * and animal branches touch disjoint state, so folding them in a single pass
 * is equivalent to the historical three-loop fold.
 */
export function replayFoldStep(state: ReplayFoldState, e: WorldEvent): void {
  const p = payload(e);

  // Agents.
  if (e.kind === 'agent_moved' && e.actor_id) {
    // W9-QA-1: the backend's agent_moved destination is payload.place
    // (runtime.py emits {place: <place_id>}); `to`/`location`/`target_id`
    // remain as fallbacks (mock / older shapes).
    const to = str(p['place']) ?? str(p['to']) ?? str(p['location']) ?? e.target_id;
    if (to && state.placeXY.has(to)) state.location.set(e.actor_id, to);
  } else if (e.kind === 'agent_died' && e.actor_id) {
    state.aliveOf.set(e.actor_id, false);
  }

  // Buildings (audit C7). Tolerant of missing payload fields: every read is
  // null-checked and an unknown status keeps the previous one.
  const buildingId =
    str(p['building_id']) ??
    (e.kind.startsWith('project_') ||
    e.kind.startsWith('building_') ||
    e.kind === 'structure_state_changed'
      ? e.target_id ?? null
      : null);
  if (buildingId) {
    if (e.kind === 'project_proposed') {
      // payload: {building_id, name, kind, location, funds_required, function}
      const b = ensureBld(state.bld, buildingId);
      b.name = str(p['name']) ?? b.name;
      b.kind = str(p['kind']) ?? b.kind;
      b.location = str(p['location']) ?? b.location;
      b.status = 'planned';
      b.progress = 0;
    } else if (e.kind === 'structure_state_changed') {
      // payload: {building_id, from, to, reason} — `to` drives the status.
      const b = ensureBld(state.bld, buildingId);
      const to = asBuildingStatus(p['to']);
      if (to) b.status = to;
    } else if (e.kind === 'project_built' || e.kind === 'project_completed') {
      // payload: {building_id, progress, step}
      const b = ensureBld(state.bld, buildingId);
      const progress = num(p['progress']);
      if (progress !== null) b.progress = Math.max(0, Math.min(100, progress));
    } else if (e.kind === 'building_operational') {
      // payload: {building_id, kind, function, location}
      const b = ensureBld(state.bld, buildingId);
      b.status = 'operational';
      b.progress = 100;
      b.kind = str(p['kind']) ?? b.kind;
      b.location = str(p['location']) ?? b.location;
    }
    // project_funded / project_contributed carry funds only — nothing the
    // replay frame renders changes, so they are intentionally not folded.
  }

  // Animals (audit D4): fold animal_spawned (payload carries location) and
  // animal_died for liveness. Positions stay best-effort (see replayFoldSeed).
  if (e.kind === 'animal_spawned' && e.actor_id) {
    const cur = state.ani.get(e.actor_id);
    state.ani.set(e.actor_id, {
      name: str(p['name']) ?? cur?.name ?? e.actor_id,
      species: str(p['species']) ?? cur?.species ?? '',
      location: str(p['location']) ?? cur?.location ?? '',
      alive: true,
      approximate: false,
    });
  } else if (e.kind === 'animal_died' && e.actor_id) {
    const cur = state.ani.get(e.actor_id);
    if (cur) cur.alive = false;
  }
}

/**
 * Post-window context finalize needs — events AFTER the scrub tick (the
 * building back-fill + the "spawned after T" pruning) and AT it. The full fold
 * computes these by scanning; the incremental projector serves them from
 * binary-searched per-events indexes. Same answers either way.
 */
export interface ReplayFoldPostWindow {
  /** Min-seq event with tick > T whose building id matches, or null. */
  earliestLaterBuildingEvent: (buildingId: string) => WorldEvent | null;
  /** animal_spawned events (with an actor_id) at tick > T. */
  spawnsAfterTick: WorldEvent[];
  /** Events at EXACTLY tick T, seq-ascending. */
  eventsAtTick: WorldEvent[];
}

/**
 * Materialize a ReplayFrame from a fold state advanced to `tick`. Pure with
 * respect to `state`: the building metadata fill / back-fill and the
 * spawned-after-T pruning operate on CLONES, so a persistent cursor state is
 * never corrupted by per-call display concerns.
 */
export function replayFoldFinalize(
  state: ReplayFoldState,
  tick: number,
  inputs: ReplayFoldInputs,
  post: ReplayFoldPostWindow,
): ReplayFrame {
  const { agents, liveBuildings } = inputs;

  const profileColor = new Map<string, string>();
  for (const a of agents) if (a.profile && a.profile_color) profileColor.set(a.profile, a.profile_color);

  const agentPositions: ReplayAgentPos[] = [];
  for (const a of agents) {
    const loc = state.location.get(a.id) ?? a.location;
    const xy = state.placeXY.get(loc) ?? { x: 500, y: 500 };
    const prof = state.profileOf.get(a.id) ?? a.profile ?? null;
    agentPositions.push({
      id: a.id,
      x: xy.x,
      y: xy.y,
      profile: prof,
      // Data-driven model color; empty when unknown — the VIEW resolves the
      // neutral token (keeps the data layer free of color literals).
      color: a.profile_color ?? (prof ? profileColor.get(prof) ?? '' : ''),
      alive: state.aliveOf.get(a.id) ?? a.alive,
    });
  }

  // Buildings: clone, then display-metadata fill ONLY (never status/progress)
  // from the live roster.
  const bld = new Map<string, ReplayBuildingState>();
  for (const [id, b] of state.bld) bld.set(id, { ...b });
  for (const lb of liveBuildings) {
    const b = bld.get(lb.id);
    if (!b) continue;
    if (!b.name || b.name === b.id) b.name = lb.name;
    if (!b.kind) b.kind = lb.kind;
    if (!b.location) b.location = lb.location;
  }
  // Tolerant back-fill: a live-roster building ABSENT from the fold either
  // (a) was created AFTER the scrub tick (its earliest event is a
  //     project_proposed > T) → it does not exist at T, skip it;
  // (b) predates the available window (seeded world / truncated history). For
  //     (b), rewind through its earliest later transition when possible —
  //     structure_state_changed carries `from`, the status BEFORE the change —
  //     otherwise fall back to the live state (better than vanishing).
  for (const lb of liveBuildings) {
    if (bld.has(lb.id)) continue;
    const earliestLater = post.earliestLaterBuildingEvent(lb.id);
    if (earliestLater?.kind === 'project_proposed') continue; // born after T
    let status: BuildingStatus = lb.status;
    if (earliestLater?.kind === 'structure_state_changed') {
      status = asBuildingStatus(payload(earliestLater)['from']) ?? lb.status;
    }
    bld.set(lb.id, {
      id: lb.id,
      name: lb.name,
      kind: lb.kind,
      location: lb.location,
      status,
      progress: lb.progress,
    });
  }

  // Animals: clone the map, then drop entries whose spawn is AFTER the scrub
  // tick — they don't exist at T. Only the live-roster fallback is overruled;
  // a snapshot ≤ T already attested the animal existed (snapshots are
  // authoritative, events tolerated).
  const ani = new Map(state.ani);
  for (const e of post.spawnsAfterTick) {
    if (!e.actor_id) continue;
    const cur = ani.get(e.actor_id);
    if (cur === undefined || cur.approximate) ani.delete(e.actor_id);
  }
  const animalPositions: ReplayAnimalPos[] = [];
  for (const [id, a] of ani) {
    const xy = state.placeXY.get(a.location);
    if (!xy) continue;
    animalPositions.push({
      id,
      name: a.name,
      species: a.species,
      x: xy.x,
      y: xy.y,
      alive: a.alive,
      approximate: a.approximate,
    });
  }

  return {
    tick,
    agents: agentPositions,
    buildings: [...bld.values()],
    animals: animalPositions,
    eventsAtTick: post.eventsAtTick,
  };
}

/** Nearest snapshot with tick <= T (replay cost bound, event-log.md §5). */
export function nearestSnapshot(snapshots: ReplaySnapshot[], tick: number): ReplaySnapshot | null {
  let best: ReplaySnapshot | null = null;
  for (const s of snapshots) {
    if (s.tick <= tick && (best === null || s.tick > best.tick)) best = s;
  }
  return best;
}

// ── W10 — scrub-consistent status strip + agent economy re-projection ────────

/**
 * Rules ACTIVE within `events` (callers pass the SCOPED slice, tick <= T, so
 * this is "rules active at the scrub tick"). A rule is active once passed and
 * never un-passes (no repeal mechanic in the contract), so counting the
 * governance lifecycle over the scoped window is exact.
 */
export function activeRuleCount(events: WorldEvent[]): number {
  return governanceTimeline(events).filter((r) => r.status === 'active').length;
}

/**
 * The sim DAY at the latest event in `events` (callers pass the SCOPED slice).
 * `turn_start` is the cheapest authoritative carrier ({..., day} per
 * event-log.md §3); the LATEST turn_start wins. `fallback` (the live world's
 * day) is returned when the window holds no turn_start.
 */
export function dayAt(events: WorldEvent[], fallback: number): number {
  let bestSeq = -Infinity;
  let day: number | null = null;
  for (const e of events) {
    if (e.kind !== 'turn_start' || e.seq <= bestSeq) continue;
    const d = num(payload(e)['day']);
    if (d !== null) {
      bestSeq = e.seq;
      day = d;
    }
  }
  return day ?? fallback;
}

/** Per-agent energy/credits re-projected from events (W10 / EM-075). */
export interface AgentEconomySample {
  energy: number;
  credits: number;
  /** True when the value came from an authoritative turn_start sample. */
  sampled: boolean;
}

/**
 * Re-project each agent's energy/credits from the SCOPED event window
 * (callers pass events with tick <= T, the scrub position).
 *
 * Approach (event-log.md §3): every `turn_start` payload carries the acting
 * agent's {energy, credits} — the cheapest authoritative per-turn sample. The
 * LATEST turn_start ≤ T anchors the value; later `action_resolved.state_deltas`
 * ({energy?, credits?, ...}) by the same agent are folded on top (they are the
 * only trivially-attributable per-agent deltas — economy events can move
 * credits for the TARGET too, which a turn-anchored fold can't safely split,
 * and per-turn energy decay is engine-internal and never evented). So the
 * result is exact-at-turn-granularity: an agent's value as of its most recent
 * turn at-or-before T, plus its own resolved deltas. Agents with NO turn_start
 * in the window (spawned later / never acted / window truncated) are absent
 * from the map — callers keep the live value and mark it approximate ("~").
 */
export function agentEconomyAt(events: WorldEvent[]): Map<string, AgentEconomySample> {
  const out = new Map<string, AgentEconomySample>();
  for (const e of ascending(events)) economyFoldStep(out, e);
  return out;
}

/**
 * Wave F (EM-194): ONE economy fold step — extracted so the incremental scrub
 * projector (projections.ts) folds the SAME transition agentEconomyAt does,
 * making the two paths equal by construction. Mutates `state` in place.
 */
export function economyFoldStep(state: Map<string, AgentEconomySample>, e: WorldEvent): void {
  if (!e.actor_id) return;
  const p = payload(e);
  if (e.kind === 'turn_start') {
    const energy = num(p['energy']);
    const credits = num(p['credits']);
    if (energy === null && credits === null) return;
    const prev = state.get(e.actor_id);
    state.set(e.actor_id, {
      energy: energy ?? prev?.energy ?? 0,
      credits: credits ?? prev?.credits ?? 0,
      sampled: true,
    });
  } else if (e.kind === 'action_resolved') {
    const cur = state.get(e.actor_id);
    if (!cur) return;
    const deltas = numRecord(p['state_deltas']);
    if (deltas['energy'] !== undefined) {
      cur.energy = Math.max(0, Math.min(100, cur.energy + deltas['energy']));
    }
    if (deltas['credits'] !== undefined) {
      cur.credits = cur.credits + deltas['credits'];
    }
  }
}

// ── W11a (EM-086) — archive-mode agent roster, reconstructed from events ─────

/**
 * Build an Agent[] for an ARCHIVED run purely from its fetched events plus the
 * RunRow.config_summary roster (frontend-inspector.md §8). The live `world`
 * prop describes the ACTIVE run, so in archive mode the panels need a roster
 * reconstructed from the selected run's own data:
 *
 *   • Seed from config_summary.agents ({name, profile} — name doubles as id).
 *   • Sweep the run's events (ascending): any human_agent actor joins the
 *     roster; `e.profile` fills the model attribution; `agent_died` flips
 *     `alive`; `agent_moved` tracks location; the LATEST `turn_start`
 *     {energy, credits} sample (+ own action_resolved deltas, via
 *     agentEconomyAt) provides final-economy values.
 *   • `profile_color` resolves from the live profile legend by NAME — model
 *     profiles are stable config across runs; a renamed profile simply gets
 *     the neutral token at the view layer (data stays color-literal-free).
 *
 * Pure; tolerant of an empty run (returns just the config roster, or []).
 */
export function archiveAgents(
  events: WorldEvent[],
  roster: Array<{ name: string; profile: string | null }> = [],
  profiles: ModelProfile[] = [],
): Agent[] {
  const colorByProfile = new Map<string, string>();
  for (const p of profiles) if (p.name && p.color) colorByProfile.set(p.name, p.color);

  const byId = new Map<string, Agent>();
  const ensure = (id: string, name?: string, profile?: string | null): Agent => {
    let a = byId.get(id);
    if (!a) {
      a = {
        id,
        name: name ?? id,
        personality: '',
        profile: profile ?? '',
        profile_color: profile ? colorByProfile.get(profile) : undefined,
        location: '',
        energy: 0,
        credits: 0,
        mood: '—',
        alive: true,
        zero_energy_turns: 0,
        beliefs: [],
        relationships: {},
      };
      byId.set(id, a);
    }
    return a;
  };

  for (const r of roster) {
    if (r.name) ensure(r.name, r.name, r.profile ?? null);
  }

  for (const e of ascending(events)) {
    if (!e.actor_id) continue;
    // Only human agents populate the roster (animals/system/god are not Agent
    // rows); tolerate a missing actor_type on kinds that imply an agent actor.
    const agentImplied =
      e.kind in CHAIN_ORDER ||
      e.kind === 'agent_died' ||
      e.kind === 'agent_moved' ||
      e.kind === 'agent_speech';
    const isAgent = e.actor_type === 'human_agent' || (e.actor_type == null && agentImplied);
    if (!isAgent) continue;
    const a = ensure(e.actor_id);
    if (e.profile && !a.profile) {
      a.profile = e.profile;
      a.profile_color = colorByProfile.get(e.profile);
    }
    if (e.kind === 'agent_died') a.alive = false;
    if (e.kind === 'agent_moved') {
      const to =
        str(payload(e)['place']) ?? str(payload(e)['to']) ?? str(payload(e)['location']) ?? e.target_id;
      if (to) a.location = to;
    }
  }

  // Final energy/credits from the run's own turn samples (exact at turn
  // granularity; agents that never acted keep the 0 defaults).
  const economy = agentEconomyAt(events);
  for (const [id, sample] of economy) {
    const a = byId.get(id);
    if (a) {
      a.energy = sample.energy;
      a.credits = sample.credits;
    }
  }

  return [...byId.values()];
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
    e.kind === 'project_contributed' ||  // legacy alias, tolerated
    e.kind === 'project_funded' ||       // events.schema.json x-known-kinds (W7)
    e.kind === 'project_completed' ||    // legacy alias, tolerated
    e.kind === 'project_built' ||        // events.schema.json x-known-kinds (W7)
    e.kind === 'building_operational' ||
    e.kind === 'building_damaged' ||
    e.kind === 'building_destroyed' ||
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
