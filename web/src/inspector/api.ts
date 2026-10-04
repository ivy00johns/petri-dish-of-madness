// ============================================================
// Inspector REST client (api.openapi.yaml v1.3.0 read endpoints).
//
// This is the DEEP-REPLAY source: full history beyond the client-side rolling
// window, and `seekTick` materials in live mode. The panels' PRIMARY data
// source is the client-side rolling history (frontend-inspector.md §7); this
// client is only reached when a panel needs depth the rolling window lacks.
//
// W11a (EM-086, frontend-inspector.md §8): every fetcher accepts an OPTIONAL
// `runId`, threaded as the `run_id` query param. Omitted = the active run
// (byte-identical to pre-W11a behavior); set = archive mode, scoping every
// read to that persisted run. `GET /api/runs` powers the RunBrowser.
//
// Every call degrades gracefully: a network/parse error resolves to a safe
// empty value (never throws into a panel), so an offline mock run is unaffected.
// The `*Result` variants return `null` on failure instead, for callers that
// must distinguish "no backend / unknown run" from "run with zero rows".
// ============================================================

import type { WorldEvent, EventKind, ActorType } from '../types';

/** One append-only event-log row (api.openapi.yaml `EventRow` component). */
export interface EventRow {
  seq: number;
  run_id: number;
  tick: number;
  sim_time: number | null;
  kind: EventKind;
  actor_id: string | null;
  actor_type: ActorType | string;
  target_id: string | null;
  profile: string | null;
  /** Hex profile color the backend derives at the /api/events + /api/replay
   *  backfill boundary (EM-187 fix #28; NOT a stored column). The model chip
   *  needs it, so the row → WorldEvent bridge MUST carry it through. */
  profile_color?: string | null;
  turn_id: string | null;
  text: string | null;
  /** Parsed kind-specific payload (event-log.md §2). */
  payload: Record<string, unknown>;
  ts: string;
}

/** Per-rule history row (api.openapi.yaml /api/rules/history, open object). */
export interface RuleHistoryRow {
  rule_id: string;
  effect: string | null;
  text: string | null;
  proposer_id: string | null;
  status: string;
  created_tick: number;
  votes: Array<{ voter_id: string; choice: boolean; tick: number }>;
  resolved_tick: number | null;
  outcome: string | null;
  downstream: number[];
}

/** Snapshot tick listing row (/api/snapshots). */
export interface SnapshotTick {
  tick: number;
}

/** Replay materials for a tick (/api/replay): base snapshot + events to fold. */
export interface ReplayMaterials {
  base: { tick: number; state: Record<string, unknown> } | null;
  events: EventRow[];
}

/** One agent entry in RunRow.config_summary (api.openapi.yaml v1.3.0). */
export interface RunConfigAgent {
  name: string;
  profile: string | null;
}

/**
 * One persisted run (api.openapi.yaml v1.3.0 `RunRow`, GET /api/runs).
 * ACTIVE comes from `is_active` ONLY — the `status` column is stored-as-is and
 * documented-unreliable (crashes/hot-reloads leave dead runs `running`).
 */
export interface RunRow {
  id: number;
  started_at: string;
  ended_at: string | null;
  /** As stored; UNRELIABLE for liveness — render as secondary text at most. */
  status: string;
  /** True iff this is MAX(id) and the loop holds it — the ONLY liveness source. */
  is_active: boolean;
  /** MAX(events.tick) for the run; 0 if no events. */
  max_tick: number;
  event_count: number;
  /** W11b (EM-101): parent run id when this run was forked; null/absent otherwise.
   *  Optional so pre-W11b fixtures/backends stay type-valid. */
  forked_from?: number | null;
  /** W11b (EM-101): the parent tick the fork branched from; null/absent otherwise. */
  forked_at_tick?: number | null;
  /** EM-112: coarse model family this run was cast from; null/absent = un-stamped.
   *  Optional so pre-EM-112 fixtures/backends stay type-valid. */
  model_family?: string | null;
  /** Small projection of runs.config_json: {agents: [{name, profile}], seed?}. */
  config_summary: { agents?: RunConfigAgent[]; seed?: number } & Record<string, unknown>;
}

/** One persona-library card (api.openapi.yaml v1.4.0 GET /api/personas). */
export interface PersonaRow {
  name: string;
  archetype: string;
  personality: string;
  suggested_profile: string;
}

/** Result of POST /api/runs/fork (EM-101). Failures stay labeled, never thrown. */
export type ForkResult =
  | { ok: true; runId: number | null }
  | { ok: false; status: number | null; message: string };

/** Result of a god-console POST (wave-a2 EM-138). Labeled, never thrown. */
export type GodActionResult =
  | { ok: true }
  | { ok: false; status: number | null; message: string };

/** The two targeted-intervention kinds (wave-a2 EM-136). */
export type GodInterveneKind = 'bless_energy' | 'grant_credits';

/** The three world-scale miracle kinds (wave-e EM-184). */
export type GodMiracleKind = 'send_rain' | 'bountiful_harvest' | 'calm_spirits';

/** Query params accepted by GET /api/events (api.openapi.yaml v1.3.0). */
export interface EventsQuery {
  /** EM-086: scope to a past run (serialized `run_id`); omitted = active run. */
  runId?: number;
  fromTick?: number;
  toTick?: number;
  /** Event kinds to include (serialized comma-separated). */
  kinds?: string[];
  actorId?: string;
  turnId?: string;
  /** Keyset pagination: rows with seq > afterSeq. */
  afterSeq?: number;
  /**
   * Wave F (EM-194): TAIL keyset pagination — rows with seq < beforeSeq,
   * paired with order:'desc' (rows newest-first). Mirror of afterSeq/asc.
   */
  beforeSeq?: number;
  limit?: number;
  order?: 'asc' | 'desc';
  /**
   * EM-187/EM-101: include ancestor (pre-fork) events so a forked/resumed run's
   * feed shows the full timeline, not just events written after the fork point.
   * Omitted/false = the run's own events only (the EM-086 run-scoped default).
   */
  lineage?: boolean;
}

/**
 * Wave F (EM-194): GET /api/events/stats — the run's event-log shape, so the
 * client can size the backfill and show honest progress ("12,000 / 99,140").
 */
export interface EventStats {
  total: number;
  max_seq: number;
  max_tick: number;
  min_seq: number;
}

/** Query params accepted by GET /api/relationships. */
export interface RelationshipsQuery {
  /** EM-086: scope to a past run (serialized `run_id`); omitted = active run. */
  runId?: number;
  agentId?: string;
  fromTick?: number;
  toTick?: number;
}

// ── EventRow ⇄ WorldEvent bridge ─────────────────────────────────────────────
//
// The panels speak `WorldEvent` (the WS/mock shape). REST rows are `EventRow`.
// They overlap; this lifts a row into the WorldEvent the selectors consume so
// deep-replay rows flow through the SAME pure selectors as rolling history.
export function eventRowToWorldEvent(row: EventRow): WorldEvent {
  return {
    type: 'event',
    seq: row.seq,
    tick: row.tick,
    kind: row.kind,
    actor_id: row.actor_id,
    target_id: row.target_id,
    profile: row.profile,
    // EM-187 fix #28 — the backfill bridge MUST carry profile_color through, or
    // the model chip renders ONLY on live WS events and vanishes for all
    // backfilled/replayed history on refresh (the live path stores rows raw; this
    // bridge is the one that previously dropped it).
    profile_color: row.profile_color ?? null,
    text: row.text,
    payload: row.payload ?? {},
    ts: row.ts,
    turn_id: row.turn_id,
    actor_type: (row.actor_type as ActorType) ?? null,
    sim_time: row.sim_time,
  };
}

// ── EM-314 The Babel Matrix (dyadic inter-model social physics) ──────────────

/** One receipt behind a matrix cell — the exact dyadic outcome event, so a
 *  finding is quotable/replayable evidence, never a chart alone. */
export interface BabelReceipt {
  seq: number;
  tick: number;
  kind: string;
  family: string;
  positive: boolean;
  actor_id: string;
  target_id: string;
  text: string;
  /** Ground-truth model that actually answered the actor's turn, when known. */
  routed_via: string | null;
}

/** One (actor-model row × target-model col) cell of the matrix. */
export interface BabelCell {
  actor: string;   // row model (the agent taking the resolving action)
  target: string;  // col model (the counterparty it acted upon)
  total: number;
  positive: number;
  rate: number | null;
  /** Wilson 95% score interval — honest confidence for thin dyad samples. */
  ci_lo: number | null;
  ci_hi: number | null;
  by_family: Record<string, { total: number; positive: number; rate: number | null }>;
  receipts: BabelReceipt[];
}

/** GET /api/babel-matrix response (fingerprint.dyadic.build_babel_matrix). */
export interface BabelMatrix {
  version: string;
  family: string | null;
  families: string[];
  models: string[];
  cells: BabelCell[];
  totals: { outcomes: number; positive: number; cells: number; receipts_capped: boolean };
}

// ── Lane Health observability (EM-300 P3/P5 — GET /api/lanes + registry) ─────

/** One outcome entry in a lane's EM-135 rolling window (router verbatim). */
export interface LaneWindowEntry {
  parsed: boolean;
  truncated: boolean;
  timed_out?: boolean;
  error?: boolean;
}

/** Per-lane cooldown state (EM-300 P3 spec §3.7 — router lane_cooldowns()).
 *  `platform` (EM-300 P3 finish): present when the parking comes from the
 *  platform's proxy-declared resume_at window, not a lane-own 429. */
export interface LaneCooldown {
  cooling: boolean;
  expires_in_s: number;
  strikes: number;
  platform?: string;
}

/** One lane in GET /api/lanes — the profile-keyed lane_health() map. */
export interface LaneHealthRow {
  window: LaneWindowEntry[];
  boosted: boolean;
  timeouts: number;
  errors: number;
  last_routed_via: string | null;
  sick: boolean;
  detours_routed_here: number;
  /** Present only while the lane is inside a 429 cooling window. */
  cooldown?: LaneCooldown;
}

export type LaneHealthMap = Record<string, LaneHealthRow>;

/** One entry in GET /api/lanes/registry (EM-300 P2 discovery view, §8). */
export interface LaneRegistryRow {
  id: string;
  source: string;
  model_id: string;
  profile: string;
  priority: number;
  enabled: boolean;
  health: 'sick' | 'ok';
  cooldown?: LaneCooldown | null;
  cap_state: 'sick' | 'ok';
  discovered: boolean;
  free: boolean;
  out_hint: string | null;
  /** Learned from X-Routed-Via ("platform - model") — EM-300 P3 finish. */
  platform?: string | null;
  last_refresh_counter: number;
}

/** GET /api/lanes/registry — ordered lanes + the discovery meta block. */
export interface LaneRegistryView {
  lanes: LaneRegistryRow[];
  discovery: {
    enabled: boolean;
    every_turns: number | null;
    served_turns: number;
    last_refresh_counter: number;
    retired: Array<{ id: string; reason: string }>;
  };
}

// ── fetch plumbing ───────────────────────────────────────────────────────────

const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null;

/**
 * GET `path` and parse JSON; `null` on ANY failure (network, !ok, parse).
 * The failure-aware base — callers that can't distinguish "no backend" from
 * "empty data" go through `getJson` (fallback) instead.
 */
async function getJsonOrNull(path: string): Promise<unknown | null> {
  try {
    const res = await fetch(path, { headers: { Accept: 'application/json' } });
    if (!res.ok) return null;
    return (await res.json()) as unknown;
  } catch {
    // Offline / mock mode: no backend. The panels fall back to rolling history.
    return null;
  }
}

/** GET `path` and parse JSON, returning `fallback` on any failure. */
async function getJson<T>(path: string, fallback: T): Promise<T> {
  const data = await getJsonOrNull(path);
  return data === null ? fallback : (data as T);
}

/** Build a query string from defined params only (skips undefined/empty). */
function qs(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === '') continue;
    search.set(k, String(v));
  }
  const s = search.toString();
  return s ? `?${s}` : '';
}

/** Coerce an unknown array-ish JSON value into a typed row array. */
function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

/**
 * Shared POST for the god console (wave-a2 EM-138): labeled ok/failure with a
 * status-mapped message (the forkRun idiom) — 422 = validation (unknown/dead
 * agent, bad amount, empty text), 503 = world not initialized. Never throws.
 */
async function postGodAction(
  path: string,
  body: Record<string, unknown>,
  what: string,
): Promise<GodActionResult> {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const message =
        res.status === 422
          ? `${what} rejected — unknown/dead agent or invalid input (HTTP 422)`
          : res.status === 503
            ? 'the world is not initialized yet (HTTP 503)'
            : `${what} failed (HTTP ${res.status})`;
      return { ok: false, status: res.status, message };
    }
    return { ok: true };
  } catch {
    return { ok: false, status: null, message: `backend unreachable — ${what} not sent` };
  }
}

// ── Typed read client ────────────────────────────────────────────────────────

/** Build the GET /api/events path for a query (shared by events/eventsResult). */
function eventsPath(query: EventsQuery): string {
  return `/api/events${qs({
    run_id: query.runId,
    from_tick: query.fromTick,
    to_tick: query.toTick,
    kinds: query.kinds?.length ? query.kinds.join(',') : undefined,
    actor_id: query.actorId,
    turn_id: query.turnId,
    after_seq: query.afterSeq,
    before_seq: query.beforeSeq,
    limit: query.limit,
    order: query.order,
    lineage: query.lineage ? 1 : undefined,
  })}`;
}

// ── EM-112 + EM-119 — the Model-Family Arena ──────────────────────────────

/** One run's civilization-outcome card (zero-LLM projection of its events). */
export interface ArenaRun {
  run_id: number;
  max_tick: number;
  outcomes: {
    population: number;
    laws_passed: number;
    buildings: number;
    crimes: number;
    credits: number;
  };
  /** Downsampled population series [{tick, alive}] (≤48 points, first+last kept). */
  population_sparkline: Array<{ tick: number; alive: number }>;
}

/** One family's standings block: its runs + per-run means. */
export interface ArenaFamily {
  family: string;
  avg_per_run: ArenaRun['outcomes'];
  runs: ArenaRun[];
}

export interface ArenaSummary {
  families: ArenaFamily[];
  /** EM-334 — contact runs: runs whose config_json carries an ARMED contact
   * block, with the family pairing + per-settlement cards. Absent on a
   * pre-EM-334 backend ⇒ parsed to []. */
  contact_runs: ContactArenaRun[];
}

/** EM-334 — one contact run's Arena card (family pairing + per-town cards). */
export interface ContactArenaRun {
  run_id: number;
  max_tick: number;
  family_a: string;
  family_b: string;
  name_b: string;
  outcomes: ArenaRun['outcomes'];
  population_by_town: Record<string, number>;
  contact_made: { tick: number; agent_id: string; from_settlement: string; to_settlement: string } | null;
  ledger: { crossings: number; by_family: Record<string, { hops: number; mutated: number }> } | null;
  events: Record<string, number>;
}

/** EM-334 — one settlement card on the /api/contact read surface. */
export interface ContactSettlement {
  id: string;
  name: string;
  founded_tick: number;
  member_count: number;
  families: Record<string, number>;
}

/** EM-334 — the /api/contact payload (the First Contact read surface). */
export interface ContactSummary {
  enabled: boolean;
  tick: number;
  settlements: ContactSettlement[];
  contact_made: { tick: number; agent_id: string; from_settlement: string; to_settlement: string } | null;
  ledger: { crossings: number; by_family: Record<string, { hops: number; mutated: number }> } | null;
  crossings: Array<{ tick: number; kind: string; actor_id: string | null; text: string }>;
  travels: Array<{ tick: number; kind: string; actor_id: string | null; text: string }>;
}

/** One settled/in-progress family result from the tournament status. */
export interface TournamentFamilyResult {
  family: string;
  run_id: number | null;
  ticks_run: number;
  status: 'done' | 'stalled' | 'aborted';
  note: string;
}

export interface TournamentStatus {
  status: 'idle' | 'running' | 'done' | 'aborted' | 'error';
  families: string[];
  ticks_per_family: number;
  current_family: string | null;
  current_index: number;
  current_run_id: number | null;
  ticks_done_in_current: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  results: TournamentFamilyResult[];
}

/** Labeled outcome shared with forkRun/god actions — never a throw. */
export interface TournamentActionResult {
  ok: boolean;
  status: number | null;
  message: string;
}

export const inspectorApi = {
  /**
   * GET /api/runs — every persisted run, newest first (EM-086, the RunBrowser).
   * Returns `null` when the backend is unreachable / pre-W11a (no endpoint),
   * so the browser can render its labeled "no backend — live session only"
   * state instead of conflating failure with "zero runs".
   */
  async runs(): Promise<RunRow[] | null> {
    const data = await getJsonOrNull('/api/runs');
    if (!Array.isArray(data)) return null;
    const rows: RunRow[] = [];
    for (const raw of data) {
      if (!isObject(raw) || typeof raw.id !== 'number') continue;
      rows.push({
        id: raw.id,
        started_at: typeof raw.started_at === 'string' ? raw.started_at : '',
        ended_at: typeof raw.ended_at === 'string' ? raw.ended_at : null,
        status: typeof raw.status === 'string' ? raw.status : '',
        is_active: raw.is_active === true,
        max_tick: typeof raw.max_tick === 'number' ? raw.max_tick : 0,
        event_count: typeof raw.event_count === 'number' ? raw.event_count : 0,
        forked_from: typeof raw.forked_from === 'number' ? raw.forked_from : null,
        forked_at_tick: typeof raw.forked_at_tick === 'number' ? raw.forked_at_tick : null,
        model_family: typeof raw.model_family === 'string' ? raw.model_family : null,
        config_summary: isObject(raw.config_summary)
          ? (raw.config_summary as RunRow['config_summary'])
          : {},
      });
    }
    // Contract: newest first. The backend already orders; enforce defensively.
    return rows.sort((a, b) => b.id - a.id);
  },

  /** GET /api/events — query the append-only log (keyset-paginatable). */
  async events(query: EventsQuery = {}): Promise<EventRow[]> {
    return asArray<EventRow>(await getJson<unknown>(eventsPath(query), []));
  },

  /**
   * Wave F (EM-194): GET /api/events/stats [?run_id] — cheap COUNT/MAX over
   * the run's event log. `null` on any failure (no backend / pre-F1 backend),
   * so callers degrade to "no progress figure" instead of a fake zero.
   */
  async eventStats(runId?: number, lineage?: boolean): Promise<EventStats | null> {
    const data = await getJsonOrNull(
      `/api/events/stats${qs({ run_id: runId, lineage: lineage ? 1 : undefined })}`);
    if (!isObject(data)) return null;
    const total = data.total;
    const maxSeq = data.max_seq;
    const maxTick = data.max_tick;
    const minSeq = data.min_seq;
    if (
      typeof total !== 'number' ||
      typeof maxSeq !== 'number' ||
      typeof maxTick !== 'number' ||
      typeof minSeq !== 'number'
    ) {
      return null;
    }
    return { total, max_seq: maxSeq, max_tick: maxTick, min_seq: minSeq };
  },

  /**
   * Failure-aware GET /api/events: `null` = fetch failed (no backend, unknown
   * run_id → 404). Archive mode uses this so an EMPTY past run gets its
   * labeled empty state rather than being mistaken for a dead backend.
   */
  async eventsResult(query: EventsQuery = {}): Promise<EventRow[] | null> {
    const data = await getJsonOrNull(eventsPath(query));
    if (data === null) return null;
    return asArray<EventRow>(data);
  },

  /** GET /api/turns/{turn_id} — the full ordered chain for one turn (EM-056). */
  async turn(turnId: string, runId?: number): Promise<EventRow[]> {
    const path = `/api/turns/${encodeURIComponent(turnId)}${qs({ run_id: runId })}`;
    return asArray<EventRow>(await getJson<unknown>(path, []));
  },

  /** GET /api/rules/history — governance lifecycle + downstream (EM-057). */
  async rulesHistory(runId?: number): Promise<RuleHistoryRow[]> {
    const path = `/api/rules/history${qs({ run_id: runId })}`;
    return asArray<RuleHistoryRow>(await getJson<unknown>(path, []));
  },

  /** GET /api/relationships — relationship/conflict/gift events (EM-058). */
  async relationships(query: RelationshipsQuery = {}): Promise<EventRow[]> {
    const path = `/api/relationships${qs({
      run_id: query.runId,
      agent_id: query.agentId,
      from_tick: query.fromTick,
      to_tick: query.toTick,
    })}`;
    return asArray<EventRow>(await getJson<unknown>(path, []));
  },

  /** GET /api/snapshots — snapshot ticks, ascending. */
  async snapshots(runId?: number): Promise<SnapshotTick[]> {
    const path = `/api/snapshots${qs({ run_id: runId })}`;
    return asArray<SnapshotTick>(await getJson<unknown>(path, []));
  },

  /** GET /api/replay?tick=T — nearest prior snapshot + events to fold (EM-055). */
  async replay(tick: number, runId?: number): Promise<ReplayMaterials> {
    const fallback: ReplayMaterials = { base: null, events: [] };
    const data = await getJson<unknown>(`/api/replay${qs({ tick, run_id: runId })}`, fallback);
    if (!isObject(data)) return fallback;
    const base =
      isObject(data.base) && typeof data.base.tick === 'number'
        ? { tick: data.base.tick, state: isObject(data.base.state) ? data.base.state : {} }
        : null;
    return { base, events: asArray<EventRow>(data.events) };
  },

  /** GET /api/analytics — the 9-AWI + model-vs-model spine (EM-059/067). */
  async analytics(
    range?: { fromTick?: number; toTick?: number },
    runId?: number,
  ): Promise<Record<string, unknown>> {
    const path = `/api/analytics${qs({
      run_id: runId,
      from_tick: range?.fromTick,
      to_tick: range?.toTick,
    })}`;
    const data = await getJson<unknown>(path, {});
    return isObject(data) ? data : {};
  },

  /**
   * GET /api/personas — the persona library (W11b EM-092). Returns `null`
   * when the backend is unreachable / pre-W11b (no endpoint) so the spawn
   * form can render its labeled "no backend" state instead of conflating
   * failure with "empty library" (which returns `[]`).
   */
  async personas(): Promise<PersonaRow[] | null> {
    const data = await getJsonOrNull('/api/personas');
    if (!Array.isArray(data)) return null;
    const rows: PersonaRow[] = [];
    for (const raw of data) {
      if (!isObject(raw) || typeof raw.name !== 'string' || raw.name.length === 0) continue;
      rows.push({
        name: raw.name,
        archetype: typeof raw.archetype === 'string' ? raw.archetype : '',
        personality: typeof raw.personality === 'string' ? raw.personality : '',
        suggested_profile: typeof raw.suggested_profile === 'string' ? raw.suggested_profile : '',
      });
    }
    return rows;
  },

  /**
   * POST /api/runs/fork {run_id, tick} (W11b EM-101) — fork a past run at
   * tick T into a NEW paused run. 201 → {ok:true, runId}; 400 (bad tick) /
   * 404 (unknown run) / network failure → a labeled {ok:false} result so the
   * Run Browser renders the failure inline, never a throw.
   */
  async forkRun(runId: number, tick: number): Promise<ForkResult> {
    try {
      const res = await fetch('/api/runs/fork', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ run_id: runId, tick }),
      });
      if (!res.ok) {
        const message =
          res.status === 404
            ? `run #${runId} not found on the backend`
            : res.status === 400
              ? `tick ${tick} is out of range for run #${runId}`
              : `fork failed (HTTP ${res.status})`;
        return { ok: false, status: res.status, message };
      }
      let newRunId: number | null = null;
      try {
        const body = (await res.json()) as unknown;
        if (isObject(body) && typeof body.run_id === 'number') newRunId = body.run_id;
      } catch {
        // 201 with an unparsable body still forked — refresh will surface it.
      }
      return { ok: true, runId: newRunId };
    } catch {
      return { ok: false, status: null, message: 'backend unreachable — fork not sent' };
    }
  },

  /**
   * GET /api/arena (EM-119) — Model-Family Arena standings: every run stamped
   * with `runs.model_family` grouped by family (outcome cards + population
   * sparklines + family means). Returns `null` when the backend is
   * unreachable / pre-EM-119, so the panel can render its labeled state.
   */
  async arena(): Promise<ArenaSummary | null> {
    const data = await getJsonOrNull('/api/arena');
    if (!isObject(data) || !Array.isArray(data.families)) return null;
    const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
    const families: ArenaFamily[] = [];
    for (const rawFam of data.families) {
      if (!isObject(rawFam) || typeof rawFam.family !== 'string') continue;
      const avg = isObject(rawFam.avg_per_run) ? rawFam.avg_per_run : {};
      const runs: ArenaRun[] = [];
      for (const rawRun of Array.isArray(rawFam.runs) ? rawFam.runs : []) {
        if (!isObject(rawRun) || typeof rawRun.run_id !== 'number') continue;
        const outcomes = isObject(rawRun.outcomes) ? rawRun.outcomes : {};
        const sparkline: Array<{ tick: number; alive: number }> = [];
        for (const p of Array.isArray(rawRun.population_sparkline) ? rawRun.population_sparkline : []) {
          if (!isObject(p)) continue;
          sparkline.push({ tick: num(p.tick), alive: num(p.alive) });
        }
        runs.push({
          run_id: rawRun.run_id,
          max_tick: num(rawRun.max_tick),
          outcomes: {
            population: num(outcomes.population),
            laws_passed: num(outcomes.laws_passed),
            buildings: num(outcomes.buildings),
            crimes: num(outcomes.crimes),
            credits: num(outcomes.credits),
          },
          population_sparkline: sparkline,
        });
      }
      families.push({
        family: rawFam.family,
        avg_per_run: {
          population: num(avg.population),
          laws_passed: num(avg.laws_passed),
          buildings: num(avg.buildings),
          crimes: num(avg.crimes),
          credits: num(avg.credits),
        },
        runs,
      });
    }
    // EM-334 — the additive contact-runs section (defensive: a pre-EM-334
    // backend omits the key ⇒ []).
    const contactRuns: ContactArenaRun[] = [];
    for (const rawCard of Array.isArray(data.contact_runs) ? data.contact_runs : []) {
      if (!isObject(rawCard) || typeof rawCard.run_id !== 'number') continue;
      const outcomes = isObject(rawCard.outcomes) ? rawCard.outcomes : {};
      const popByTown: Record<string, number> = {};
      if (isObject(rawCard.population_by_town)) {
        for (const [town, n] of Object.entries(rawCard.population_by_town)) {
          popByTown[town] = num(n);
        }
      }
      const ledgerRaw = isObject(rawCard.ledger) ? rawCard.ledger : null;
      const byFamily: Record<string, { hops: number; mutated: number }> = {};
      if (ledgerRaw && isObject(ledgerRaw.by_family)) {
        for (const [fam, rec] of Object.entries(ledgerRaw.by_family)) {
          if (!isObject(rec)) continue;
          byFamily[fam] = { hops: num(rec.hops), mutated: num(rec.mutated) };
        }
      }
      const madeRaw = isObject(rawCard.contact_made) ? rawCard.contact_made : null;
      const events: Record<string, number> = {};
      if (isObject(rawCard.events)) {
        for (const [k, n] of Object.entries(rawCard.events)) events[k] = num(n);
      }
      contactRuns.push({
        run_id: rawCard.run_id,
        max_tick: num(rawCard.max_tick),
        family_a: typeof rawCard.family_a === 'string' ? rawCard.family_a : '',
        family_b: typeof rawCard.family_b === 'string' ? rawCard.family_b : '',
        name_b: typeof rawCard.name_b === 'string' ? rawCard.name_b : '',
        outcomes: {
          population: num(outcomes.population),
          laws_passed: num(outcomes.laws_passed),
          buildings: num(outcomes.buildings),
          crimes: num(outcomes.crimes),
          credits: num(outcomes.credits),
        },
        population_by_town: popByTown,
        contact_made: madeRaw
          ? {
              tick: num(madeRaw.tick),
              agent_id: typeof madeRaw.agent_id === 'string' ? madeRaw.agent_id : '',
              from_settlement: typeof madeRaw.from_settlement === 'string' ? madeRaw.from_settlement : '',
              to_settlement: typeof madeRaw.to_settlement === 'string' ? madeRaw.to_settlement : '',
            }
          : null,
        ledger: ledgerRaw
          ? { crossings: num(ledgerRaw.crossings), by_family: byFamily }
          : null,
        events,
      });
    }
    return { families, contact_runs: contactRuns };
  },

  /**
   * GET /api/contact (EM-334) — the First Contact read surface: settlement
   * cards, the contact marker latch, the honesty ledger, and the recent
   * crossing/travel events. Returns `null` when the backend is unreachable;
   * an unarmed world parses to `{ enabled: false }` so the panel renders its
   * labeled zero state.
   */
  async contact(): Promise<ContactSummary | null> {
    const data = await getJsonOrNull('/api/contact');
    if (!isObject(data)) return null;
    if (data.enabled !== true) return { enabled: false, tick: 0, settlements: [], contact_made: null, ledger: null, crossings: [], travels: [] };
    const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
    const str = (v: unknown): string => (typeof v === 'string' ? v : '');
    const settlements: ContactSettlement[] = [];
    for (const s of Array.isArray(data.settlements) ? data.settlements : []) {
      if (!isObject(s) || typeof s.id !== 'string') continue;
      const families: Record<string, number> = {};
      if (isObject(s.families)) {
        for (const [fam, n] of Object.entries(s.families)) families[fam] = num(n);
      }
      settlements.push({
        id: s.id,
        name: str(s.name),
        founded_tick: num(s.founded_tick),
        member_count: num(s.member_count),
        families,
      });
    }
    const madeRaw = isObject(data.contact_made) ? data.contact_made : null;
    const ledgerRaw = isObject(data.ledger) ? data.ledger : null;
    const byFamily: Record<string, { hops: number; mutated: number }> = {};
    if (ledgerRaw && isObject(ledgerRaw.by_family)) {
      for (const [fam, rec] of Object.entries(ledgerRaw.by_family)) {
        if (!isObject(rec)) continue;
        byFamily[fam] = { hops: num(rec.hops), mutated: num(rec.mutated) };
      }
    }
    const readLegs = (raw: unknown): ContactSummary['crossings'] =>
      (Array.isArray(raw) ? raw : [])
        .filter(isObject)
        .map((e) => ({
          tick: num(e.tick),
          kind: str(e.kind),
          actor_id: typeof e.actor_id === 'string' ? e.actor_id : null,
          text: str(e.text),
        }));
    return {
      enabled: true,
      tick: num(data.tick),
      settlements,
      contact_made: madeRaw
        ? {
            tick: num(madeRaw.tick),
            agent_id: str(madeRaw.agent_id),
            from_settlement: str(madeRaw.from_settlement),
            to_settlement: str(madeRaw.to_settlement),
          }
        : null,
      ledger: ledgerRaw
        ? { crossings: num(ledgerRaw.crossings), by_family: byFamily }
        : null,
      crossings: readLegs(data.crossings),
      travels: readLegs(data.travels),
    };
  },

  /**
   * GET /api/arena/tournament (EM-112) — current tournament state. Any
   * failure parses to the idle shape (the panel just shows its controls).
   */
  async tournamentStatus(): Promise<TournamentStatus> {
    const data = await getJsonOrNull('/api/arena/tournament');
    if (!isObject(data) || typeof data.status !== 'string') {
      return {
        status: 'idle', families: [], ticks_per_family: 40,
        current_family: null, current_index: 0, current_run_id: null,
        ticks_done_in_current: 0, started_at: null, finished_at: null,
        error: null, results: [],
      };
    }
    const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
    const results: TournamentFamilyResult[] = [];
    for (const r of Array.isArray(data.results) ? data.results : []) {
      if (!isObject(r) || typeof r.family !== 'string') continue;
      const st = r.status === 'stalled' || r.status === 'aborted' ? r.status : 'done';
      results.push({
        family: r.family,
        run_id: typeof r.run_id === 'number' ? r.run_id : null,
        ticks_run: num(r.ticks_run),
        status: st,
        note: typeof r.note === 'string' ? r.note : '',
      });
    }
    const rawStatus: unknown = data.status;
    const status: TournamentStatus['status'] =
      rawStatus === 'running' || rawStatus === 'done' ||
      rawStatus === 'aborted' || rawStatus === 'error'
        ? rawStatus
        : 'idle';
    return {
      status,
      families: (Array.isArray(data.families) ? data.families : []).filter(
        (f): f is string => typeof f === 'string'),
      ticks_per_family: num(data.ticks_per_family) || 40,
      current_family: typeof data.current_family === 'string' ? data.current_family : null,
      current_index: num(data.current_index),
      current_run_id: typeof data.current_run_id === 'number' ? data.current_run_id : null,
      ticks_done_in_current: num(data.ticks_done_in_current),
      started_at: typeof data.started_at === 'string' ? data.started_at : null,
      finished_at: typeof data.finished_at === 'string' ? data.finished_at : null,
      error: typeof data.error === 'string' ? data.error : null,
      results,
    };
  },

  /**
   * POST /api/arena/tournament (EM-112) — start a SEQUENTIAL parallel-worlds
   * tournament (one family's world at a time through the live loop). 202 →
   * {ok:true}; 400 (unknown/un-castable family, bad ticks) / 409 (already
   * running) / network failure → labeled {ok:false}, never a throw.
   */
  async startTournament(
    families: string[],
    ticksPerFamily: number,
  ): Promise<TournamentActionResult> {
    try {
      const res = await fetch('/api/arena/tournament', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ families, ticks_per_family: ticksPerFamily }),
      });
      if (!res.ok) {
        let detail = `tournament start failed (HTTP ${res.status})`;
        try {
          const body = (await res.json()) as unknown;
          if (isObject(body) && typeof body.detail === 'string') detail = body.detail;
        } catch {
          // non-JSON error body — keep the labeled fallback
        }
        return { ok: false, status: res.status, message: detail };
      }
      return { ok: true, status: res.status, message: 'started' };
    } catch {
      return { ok: false, status: null, message: 'backend unreachable — tournament not started' };
    }
  },

  /**
   * DELETE /api/arena/tournament (EM-112) — abort between turns. The current
   * family's run stays (paused, partial); 409 when nothing is running.
   */
  async abortTournament(): Promise<TournamentActionResult> {
    try {
      const res = await fetch('/api/arena/tournament', { method: 'DELETE' });
      if (!res.ok) {
        return {
          ok: false,
          status: res.status,
          message: res.status === 409 ? 'no tournament is running' : `abort failed (HTTP ${res.status})`,
        };
      }
      return { ok: true, status: res.status, message: 'aborting' };
    } catch {
      return { ok: false, status: null, message: 'backend unreachable — abort not sent' };
    }
  },

  /**
   * POST /api/god/intervene {kind, agent_id, amount?} (wave-a2 EM-136/138) —
   * targeted god intervention on a LIVING agent. `amount` omitted = the
   * backend's defaults (+25 energy / +10 credits). Optimistic-free: the
   * god_intervention event arrives via the WS feed; this returns only the
   * labeled ok/failure for the console's inline error treatment.
   */
  async godIntervene(
    kind: GodInterveneKind,
    agentId: string,
    amount?: number,
  ): Promise<GodActionResult> {
    return postGodAction(
      '/api/god/intervene',
      { kind, agent_id: agentId, ...(amount !== undefined ? { amount } : {}) },
      'intervention',
    );
  },

  /**
   * POST /api/god/intervene {kind} (wave-e EM-184/185) — cast a WORLD-scale
   * miracle. The contract REQUIRES agent_id absent for world kinds (the
   * backend 422s otherwise), so the body carries `kind` alone — never an
   * agent_id key. Optimistic-free: the god_miracle event arrives via the WS;
   * this returns only the labeled ok/failure (422 = unknown kind / miracles
   * disabled / agent_id mismatch; 503 = world not initialized; never throws).
   */
  async godMiracle(kind: GodMiracleKind): Promise<GodActionResult> {
    return postGodAction('/api/god/intervene', { kind }, 'miracle');
  },

  /**
   * POST /api/god/whisper {agent_id, text} (wave-a2 EM-137/138) — queue a
   * one-shot line into the agent's NEXT context. Capped at 280 chars here,
   * mirroring the billboard cap. The whisper_posted event arrives via the WS.
   */
  async godWhisper(agentId: string, text: string): Promise<GodActionResult> {
    return postGodAction(
      '/api/god/whisper',
      { agent_id: agentId, text: text.trim().slice(0, 280) },
      'whisper',
    );
  },

  /**
   * POST /api/proclaim {text} (wave-a2 EM-137 sibling) — the LOUD god voice: a
   * proclamation heard by the WHOLE town. Unlike the opt-in billboard (agents
   * must choose to read the board), the active proclamation rides EVERY agent's
   * next prompt, so the word is guaranteed to reach them. Capped at 280 chars
   * (the backend ProclaimBody cap). Optimistic-free: the proclamation_posted
   * event arrives via the WS feed; this returns only the labeled ok/failure
   * (422 = empty/too-long; 503 = world not initialized; never throws).
   */
  async proclaim(text: string): Promise<GodActionResult> {
    return postGodAction('/api/proclaim', { text: text.trim().slice(0, 280) }, 'proclamation');
  },

  /**
   * Failure-aware GET /api/analytics scoped to ONE run (EM-086 cross-run
   * comparison): `null` = fetch failed, so the compare panel can label
   * "couldn't load run #N" instead of rendering an all-zero summary.
   */
  async runAnalytics(runId: number): Promise<Record<string, unknown> | null> {
    const data = await getJsonOrNull(`/api/analytics${qs({ run_id: runId })}`);
    return isObject(data) ? data : null;
  },

  /**
   * EM-314 — GET /api/babel-matrix [?run_id&family&lineage]. The dyadic
   * (actor-model × target-model) outcome heatmap for a run. Returns `null` when
   * the backend is unreachable OR the feature is disabled (the endpoint 404s
   * unless PETRIDISH_BABEL_MATRIX_ENABLED is set), so the panel can render its
   * labeled "disabled / no backend" state instead of an empty grid. WITHIN-run
   * dyads (distinct from EM-119 cross-run charts); lineage folds one fork chain.
   */
  async babelMatrix(
    runId?: number,
    opts?: { family?: string; lineage?: boolean },
  ): Promise<BabelMatrix | null> {
    const path = `/api/babel-matrix${qs({
      run_id: runId,
      family: opts?.family,
      lineage: opts?.lineage ? 1 : undefined,
    })}`;
    const data = await getJsonOrNull(path);
    if (!isObject(data) || !Array.isArray(data.cells) || !Array.isArray(data.models)) {
      return null;
    }
    return data as unknown as BabelMatrix;
  },

  /**
   * EM-300 P5 — GET /api/lanes. The router's EM-135 lane_health() map verbatim
   * (profile → {window, boosted, timeouts, errors, last_routed_via, sick,
   * detours_routed_here, cooldown?}), the same payload the Wave D3 endpoint has
   * always served (cooldown is the additive EM-300 P3 key). `null` when the
   * backend is unreachable, so the panel renders its labeled "no backend"
   * state instead of an empty table.
   */
  async lanes(): Promise<LaneHealthMap | null> {
    const data = await getJsonOrNull('/api/lanes');
    if (!isObject(data) || Array.isArray(data)) return null;
    const out: LaneHealthMap = {};
    for (const [profile, raw] of Object.entries(data)) {
      if (!isObject(raw)) continue;
      const row = raw as Record<string, unknown>;
      out[profile] = {
        window: Array.isArray(row.window)
          ? (row.window as LaneWindowEntry[])
          : [],
        boosted: row.boosted === true,
        timeouts: typeof row.timeouts === 'number' ? row.timeouts : 0,
        errors: typeof row.errors === 'number' ? row.errors : 0,
        last_routed_via: typeof row.last_routed_via === 'string' ? row.last_routed_via : null,
        sick: row.sick === true,
        detours_routed_here: typeof row.detours_routed_here === 'number' ? row.detours_routed_here : 0,
        ...(isObject(row.cooldown)
          ? {
              cooldown: {
                cooling: row.cooldown.cooling === true,
                expires_in_s: typeof row.cooldown.expires_in_s === 'number'
                  ? row.cooldown.expires_in_s
                  : 0,
                strikes: typeof row.cooldown.strikes === 'number' ? row.cooldown.strikes : 0,
              },
            }
          : {}),
      };
    }
    return out;
  },

  /**
   * EM-300 P5 — GET /api/lanes/registry. The EM-300 P2 discovery view: the
   * lane registry in priority order + the discovery meta block. `null` when
   * the backend is unreachable / pre-P2 (no endpoint), so the panel can label
   * the state instead of conflating it with "zero lanes".
   */
  async lanesRegistry(): Promise<LaneRegistryView | null> {
    const data = await getJsonOrNull('/api/lanes/registry');
    if (!isObject(data) || !Array.isArray(data.lanes)) return null;
    const lanes: LaneRegistryRow[] = [];
    for (const raw of data.lanes) {
      if (!isObject(raw) || typeof raw.id !== 'string') continue;
      lanes.push({
        id: raw.id,
        source: typeof raw.source === 'string' ? raw.source : '',
        model_id: typeof raw.model_id === 'string' ? raw.model_id : '',
        profile: typeof raw.profile === 'string' ? raw.profile : '',
        priority: typeof raw.priority === 'number' ? raw.priority : 0,
        enabled: raw.enabled !== false,
        health: raw.health === 'sick' ? 'sick' : 'ok',
        cooldown: isObject(raw.cooldown) ? raw.cooldown as unknown as LaneCooldown : null,
        cap_state: raw.cap_state === 'sick' ? 'sick' : 'ok',
        discovered: raw.discovered === true,
        free: raw.free !== false,
        out_hint: typeof raw.out_hint === 'string' ? raw.out_hint : null,
        last_refresh_counter: typeof raw.last_refresh_counter === 'number' ? raw.last_refresh_counter : 0,
      });
    }
    const d = isObject(data.discovery) ? data.discovery as Record<string, unknown> : {};
    return {
      lanes,
      discovery: {
        enabled: d.enabled === true,
        every_turns: typeof d.every_turns === 'number' ? d.every_turns : null,
        served_turns: typeof d.served_turns === 'number' ? d.served_turns : 0,
        last_refresh_counter: typeof d.last_refresh_counter === 'number' ? d.last_refresh_counter : 0,
        retired: Array.isArray(d.retired) ? d.retired as Array<{ id: string; reason: string }> : [],
      },
    };
  },
};

export type InspectorApi = typeof inspectorApi;
