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
  limit?: number;
  order?: 'asc' | 'desc';
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
    text: row.text,
    payload: row.payload ?? {},
    ts: row.ts,
    turn_id: row.turn_id,
    actor_type: (row.actor_type as ActorType) ?? null,
    sim_time: row.sim_time,
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
    limit: query.limit,
    order: query.order,
  })}`;
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
   * Failure-aware GET /api/analytics scoped to ONE run (EM-086 cross-run
   * comparison): `null` = fetch failed, so the compare panel can label
   * "couldn't load run #N" instead of rendering an all-zero summary.
   */
  async runAnalytics(runId: number): Promise<Record<string, unknown> | null> {
    const data = await getJsonOrNull(`/api/analytics${qs({ run_id: runId })}`);
    return isObject(data) ? data : null;
  },
};

export type InspectorApi = typeof inspectorApi;
