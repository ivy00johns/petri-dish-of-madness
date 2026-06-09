// ============================================================
// Inspector view-models (frontend-inspector.md §7).
//
// These are the SHAPES the five inspector panels consume. They are derived
// (by `selectors.ts`) from the client-side rolling history (`WorldEvent[]`,
// the 5,000-cap ref in useSimulation) so the panels render in MOCK mode with
// no backend, and identically in live mode. The REST `api.ts` client is the
// deep-replay source (full history beyond the rolling window).
//
// Mirror the backend `get_*` shapes (event-log.md §7) so a panel built against
// these types works against either data source.
// ============================================================

import type { Agent, ModelProfile, WorldEvent, EventKind, BuildingStatus } from '../types';

// ── PanelProps — the single contract every inspector panel receives ──────────
//
// InspectorLayout owns the shared `currentTick`; ReplayScrubber drives it; the
// other panels re-project at `currentTick` (scrub once, everything follows).
// Every panel (DecisionTrace, GovernanceHistory, SocialGraph, AWIDashboard,
// and ReplayScrubber's siblings) is mounted with EXACTLY this prop bag.
export interface PanelProps {
  /**
   * Event history (newest-first), the panels' primary data source. While
   * scrubbed (not pinned to live) InspectorLayout passes a SCOPED slice
   * (events with tick <= currentTick) so panels never bleed live-edge data
   * into a replayed view (audit C8, frontend-inspector.md v1.1.0 §3).
   */
  events: WorldEvent[];
  /**
   * Agents (the social-graph nodes + analytics population). While scrubbed,
   * `alive` is re-projected at the scrub tick from death events (audit C8).
   */
  agents: Agent[];
  /** Model profiles — the legend, and the color-by-model source. */
  profiles: ModelProfile[];
  /** Shared scrub position. Panels re-project their view AT this tick. */
  currentTick: number;
  /** Latest tick present in `events` (the scrubber's right edge). */
  maxTick: number;
  /**
   * True while the live-mode /api/events backfill is still paging in (EM-069).
   * Panels with no data yet label it "history loading…" instead of an empty
   * claim like "no events". Optional: absent ⇒ not loading (mock mode).
   */
  historyLoading?: boolean;
  /**
   * W10 (EM-075): true while scrubbed when at least one agent's energy/credits
   * at the scrub tick could NOT be reconstructed from events (no `turn_start`
   * sample ≤ T in the scoped window) — those agents carry live-edge values.
   * Panels that surface per-agent economy (the AWI economy card) show a subtle
   * "~" approximation marker with an explanatory title. Absent ⇒ exact/live.
   */
  agentsApproximate?: boolean;
}

// ── Decision trace (EM-056) ──────────────────────────────────────────────────
//
// One agent turn = one linked chain sharing a `turn_id` (event-log.md §3),
// ordered: turn_start → perceived → memory_retrieved → llm_call → reasoning →
// action_chosen → action_resolved, plus any domain events the action caused.

/** One parsed span in a turn's chain (an EventRow projected to the UI). */
export interface TraceSpan {
  seq: number;
  tick: number;
  kind: EventKind;
  /** Human-readable feed line, when present. */
  text: string | null;
  /** Parsed kind-specific payload (open shape, event-log.md §2). */
  payload: Record<string, unknown>;
  /** Wall-clock ISO timestamp, when present. */
  ts: string | null;
}

/** Token / latency summary lifted from the chain's `llm_call` span. */
export interface TraceUsage {
  /** Requested model profile (`gen_ai.request.model`). */
  requestModel: string | null;
  /** Model that actually answered (`gen_ai.response.model` / routed_via). */
  responseModel: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
  latencyMs: number | null;
  finishReasons: string[] | null;
  cached: boolean;
  /** Attempt that produced the result (1 or 2). */
  attempt: number | null;
}

/** The full decision-trace view-model for one turn. */
export interface TurnTrace {
  turnId: string;
  tick: number;
  agentId: string | null;
  /** Model profile of the acting agent (color-coding). */
  profile: string | null;
  /** The ordered chain spans (seq ascending). */
  spans: TraceSpan[];
  /** Usage parsed from the `llm_call` span (nulls until EM-067). */
  usage: TraceUsage | null;
  /** Final outcome from `action_resolved`, when present. */
  outcome: 'ok' | 'gated' | 'failed' | null;
  /** State deltas from `action_resolved.state_deltas`. */
  stateDeltas: Record<string, number>;
  /** The chosen tool + args from `action_chosen`. */
  chosenTool: string | null;
}

// ── Governance history (EM-057) ──────────────────────────────────────────────
//
// Per rule_id: the proposal lifecycle + downstream consequences
// (the "clock tower failure made visible"). Mirrors get_rule_history.

export type GovStatus = 'proposed' | 'active' | 'rejected';

export interface GovVote {
  voterId: string;
  choice: boolean;
  tick: number;
}

/** A downstream event a rule caused (an economy/ubi distribution, a death). */
export interface GovDownstream {
  seq: number;
  tick: number;
  kind: EventKind;
  text: string | null;
}

export interface GovTimelineEntry {
  ruleId: string;
  effect: string | null;
  text: string | null;
  proposerId: string | null;
  status: GovStatus;
  createdTick: number;
  votes: GovVote[];
  resolvedTick: number | null;
  /** 'passed' | 'rejected' | null while still open. */
  outcome: 'passed' | 'rejected' | null;
  /** Later events this rule caused (the consequence links). */
  downstream: GovDownstream[];
}

// ── Social graph (EM-058) ────────────────────────────────────────────────────
//
// Nodes = agents (color by model); edges = relationships. Time-scrubbable: the
// graph is the relationship state AT a tick. Mirrors get_relationship_timeline.

export interface SocialNode {
  id: string;
  label: string;
  /** Hex color from the agent's model profile (data-driven, not a literal). */
  color: string;
  /** Whether the agent is alive at the scrub tick. */
  alive: boolean;
}

export interface SocialEdge {
  source: string;
  target: string;
  /** ally | rival | friend | enemy | neutral (relationship type). */
  type: string;
  /** -100..100 trust at the scrub tick. */
  trust: number;
}

export interface SocialGraphData {
  nodes: SocialNode[];
  edges: SocialEdge[];
}

// ── AWI dashboard (EM-059) ───────────────────────────────────────────────────
//
// The 9 agent-welfare indicators + model-vs-model cut + usage. NO composite
// score (weighting embeds values). Typed mirror of get_analytics (event-log.md
// §7). Every field tolerates the empty / partial case so the panel degrades
// to an empty-but-labeled state.

export interface AwiCrime {
  byKind: Record<string, number>;
}

export interface AwiGovernance {
  participation: number;
  proposed: number;
  passed: number;
  rejected: number;
}

export interface AwiPublicExpression {
  say: number;
  proposeRule: number;
}

export interface AwiSocialFabric {
  edges: number;
  byType: Record<string, number>;
}

export interface AwiEconomy {
  gini: number;
  throughput: number;
  byAgent: Record<string, number>;
}

export interface AwiConstitution {
  activeRules: number;
  amendments: number;
}

export interface AwiByModel {
  alive: number;
  dead: number;
  crimes: number;
  gives: number;
  /** Proposals BY this model's agents. */
  proposals: number;
  /** Of this model's proposals, how many passed (audit C6: same population as `rejected`). */
  passed: number;
  /** Of this model's proposals, how many were rejected. */
  rejected: number;
  creditShare: number;
}

export interface AwiUsageByProfile {
  requests: number;
  inputTokens: number;
  outputTokens: number;
}

export interface AwiSummary {
  /** Population over time — one point per observed tick. */
  population: Array<{ tick: number; alive: number }>;
  crime: AwiCrime;
  toolExploration: { byAgent: Record<string, number> };
  spaceExploration: { byAgent: Record<string, number> };
  governance: AwiGovernance;
  publicExpression: AwiPublicExpression;
  socialFabric: AwiSocialFabric;
  economy: AwiEconomy;
  constitution: AwiConstitution;
  /** The differentiator cut: per-profile rollup. */
  byModel: Record<string, AwiByModel>;
  /** Per-profile token usage (EM-067; zero until populated). */
  usage: { byProfile: Record<string, AwiUsageByProfile> };
}

// ── Replay (EM-055) ──────────────────────────────────────────────────────────
//
// World state materialized at a tick (the same shape the replay map reads).
// In mock mode this is folded client-side from history (+ snapshots if any);
// in live mode the deep source is GET /api/replay.

/** A lightweight agent position for the Canvas2D mini-map. */
export interface ReplayAgentPos {
  id: string;
  /** Logical [0..1000] position (the place the agent is at). */
  x: number;
  y: number;
  profile: string | null;
  color: string;
  alive: boolean;
}

/**
 * W10 / audit C7 — building state TIME-PROJECTED at a tick. A minimal subset of
 * `Building` (exactly what the replay mini-map + structures readout render), so
 * both a full live `Building` and an event-folded projection satisfy it.
 */
export interface ReplayBuildingState {
  id: string;
  name: string;
  kind: string;
  location: string;
  status: BuildingStatus;
  progress: number;
}

/**
 * W10 / audit D4 — an animal position for the replay mini-map. Animal moves are
 * NOT replayable from events (`animal_action` doesn't carry the destination
 * place id), so positions are best-effort: snapshot-based when deep-replay
 * materials are present, otherwise the live roster (flagged `approximate`).
 */
export interface ReplayAnimalPos {
  id: string;
  name: string;
  species: string;
  /** Logical [0..1000] position (the place the animal is at). */
  x: number;
  y: number;
  alive: boolean;
  /** True when the position comes from the live roster, not a tick-T source. */
  approximate: boolean;
}

export interface ReplayFrame {
  tick: number;
  /** Agent positions at this tick (for the top-down map). */
  agents: ReplayAgentPos[];
  /** W10/C7: building state projected at this tick (status/progress at T). */
  buildings: ReplayBuildingState[];
  /** W10/D4: animal positions at this tick (best-effort, see ReplayAnimalPos). */
  animals: ReplayAnimalPos[];
  /** Events that occurred AT exactly this tick (for the markers detail). */
  eventsAtTick: WorldEvent[];
}
