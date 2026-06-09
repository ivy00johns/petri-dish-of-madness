// ============================================================
// Inspector REST client (api.openapi.yaml v1.1.0 read endpoints).
//
// This is the DEEP-REPLAY source: full history beyond the client-side rolling
// window, and `seekTick` materials in live mode. The panels' PRIMARY data
// source is the client-side rolling history (frontend-inspector.md §7); this
// client is only reached when a panel needs depth the rolling window lacks.
//
// Every call degrades gracefully: a network/parse error resolves to a safe
// empty value (never throws into a panel), so an offline mock run is unaffected.
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

/** Query params accepted by GET /api/events (api.openapi.yaml). */
export interface EventsQuery {
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

/** GET `path` and parse JSON, returning `fallback` on any failure. */
async function getJson<T>(path: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(path, { headers: { Accept: 'application/json' } });
    if (!res.ok) return fallback;
    return (await res.json()) as T;
  } catch {
    // Offline / mock mode: no backend. The panels fall back to rolling history.
    return fallback;
  }
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

export const inspectorApi = {
  /** GET /api/events — query the append-only log (keyset-paginatable). */
  async events(query: EventsQuery = {}): Promise<EventRow[]> {
    const path = `/api/events${qs({
      from_tick: query.fromTick,
      to_tick: query.toTick,
      kinds: query.kinds?.length ? query.kinds.join(',') : undefined,
      actor_id: query.actorId,
      turn_id: query.turnId,
      after_seq: query.afterSeq,
      limit: query.limit,
      order: query.order,
    })}`;
    return asArray<EventRow>(await getJson<unknown>(path, []));
  },

  /** GET /api/turns/{turn_id} — the full ordered chain for one turn (EM-056). */
  async turn(turnId: string): Promise<EventRow[]> {
    const path = `/api/turns/${encodeURIComponent(turnId)}`;
    return asArray<EventRow>(await getJson<unknown>(path, []));
  },

  /** GET /api/rules/history — governance lifecycle + downstream (EM-057). */
  async rulesHistory(): Promise<RuleHistoryRow[]> {
    return asArray<RuleHistoryRow>(await getJson<unknown>('/api/rules/history', []));
  },

  /** GET /api/relationships — relationship/conflict/gift events (EM-058). */
  async relationships(query: RelationshipsQuery = {}): Promise<EventRow[]> {
    const path = `/api/relationships${qs({
      agent_id: query.agentId,
      from_tick: query.fromTick,
      to_tick: query.toTick,
    })}`;
    return asArray<EventRow>(await getJson<unknown>(path, []));
  },

  /** GET /api/snapshots — snapshot ticks, ascending. */
  async snapshots(): Promise<SnapshotTick[]> {
    return asArray<SnapshotTick>(await getJson<unknown>('/api/snapshots', []));
  },

  /** GET /api/replay?tick=T — nearest prior snapshot + events to fold (EM-055). */
  async replay(tick: number): Promise<ReplayMaterials> {
    const fallback: ReplayMaterials = { base: null, events: [] };
    const data = await getJson<unknown>(`/api/replay${qs({ tick })}`, fallback);
    if (!isObject(data)) return fallback;
    const base =
      isObject(data.base) && typeof data.base.tick === 'number'
        ? { tick: data.base.tick, state: isObject(data.base.state) ? data.base.state : {} }
        : null;
    return { base, events: asArray<EventRow>(data.events) };
  },

  /** GET /api/analytics — the 9-AWI + model-vs-model spine (EM-059/067). */
  async analytics(range?: { fromTick?: number; toTick?: number }): Promise<Record<string, unknown>> {
    const path = `/api/analytics${qs({ from_tick: range?.fromTick, to_tick: range?.toTick })}`;
    const data = await getJson<unknown>(path, {});
    return isObject(data) ? data : {};
  },
};

export type InspectorApi = typeof inspectorApi;
