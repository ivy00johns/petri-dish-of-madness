/**
 * EM-313 — Fingerprint Ticker client (feed/viewer chrome).
 *
 * Types + a tiny read-only fetch for GET /api/fingerprints — the zero-LLM
 * behavioral-stylometry classifier that guesses which model an agent runs from
 * its event-log behavior and races a converging confidence bar against the
 * X-Routed-Via ground truth. The backend owns all the math (single source of
 * truth, versioned) so retro-scores never drift; this module only fetches and
 * shapes the payload for rendering. Gated server-side by
 * `world.fingerprint_ticker.enabled` (default OFF) — a disabled backend returns
 * `{ enabled: false }` and the ticker renders nothing.
 */

export type FingerprintStatus = 'gathering' | 'tracking' | 'locked';

export interface FingerprintSeriesPoint {
  turn: number;
  tick: number;
  guess: string | null;
  confidence: number; // 0..1
  distribution: Record<string, number>;
}

export interface FingerprintAgent {
  agent_id: string;
  turns: number;
  ground_truth: string | null; // X-Routed-Via majority label (the reveal)
  guess: string | null;
  confidence: number; // 0..1
  status: FingerprintStatus;
  correct: boolean | null;
  candidates: string[];
  series: FingerprintSeriesPoint[];
}

export interface FingerprintResponse {
  enabled: boolean;
  feature_version: number;
  run_id?: number;
  temperature?: number;
  lock_threshold?: number;
  min_turns?: number;
  reference_source?: 'historical' | 'within_run';
  reference_runs_used?: number[];
  agents: FingerprintAgent[];
}

/**
 * Fetch the ticker payload. Omit `runId` to scope to the active (live) run.
 * Returns null on any transport/parse failure so callers degrade to hidden —
 * this is chrome, it must never throw into the feed.
 */
export async function fetchFingerprints(
  runId?: number,
): Promise<FingerprintResponse | null> {
  const path =
    runId == null ? '/api/fingerprints' : `/api/fingerprints?run_id=${runId}`;
  try {
    const res = await fetch(path, { headers: { Accept: 'application/json' } });
    if (!res.ok) return null;
    const body = (await res.json()) as unknown;
    if (!body || typeof body !== 'object') return null;
    const r = body as Partial<FingerprintResponse>;
    if (typeof r.enabled !== 'boolean') return null;
    return {
      enabled: r.enabled,
      feature_version: Number(r.feature_version ?? 0),
      run_id: r.run_id,
      temperature: r.temperature,
      lock_threshold: r.lock_threshold,
      min_turns: r.min_turns,
      reference_source: r.reference_source,
      reference_runs_used: r.reference_runs_used,
      agents: Array.isArray(r.agents) ? (r.agents as FingerprintAgent[]) : [],
    };
  } catch {
    return null;
  }
}

/**
 * Choose which agent the compact ticker spotlights: the explicitly focused
 * agent when it has data, else the agent with the MOST turns (the strongest,
 * most-converged read). Returns null when nothing is worth showing.
 */
export function pickAgent(
  data: FingerprintResponse | null,
  activeAgentId?: string | null,
): FingerprintAgent | null {
  if (!data || !data.enabled || data.agents.length === 0) return null;
  if (activeAgentId) {
    const focused = data.agents.find((a) => a.agent_id === activeAgentId);
    if (focused) return focused;
  }
  return data.agents.reduce(
    (best, a) => (best == null || a.turns > best.turns ? a : best),
    null as FingerprintAgent | null,
  );
}

/** A short, readable model label (strip a common provider prefix noise). */
export function shortModel(name: string | null | undefined): string {
  if (!name) return '—';
  return name.length > 22 ? `${name.slice(0, 21)}…` : name;
}

/** Confidence as a whole-percent integer, clamped to [0, 100]. */
export function pct(confidence: number): number {
  return Math.max(0, Math.min(100, Math.round(confidence * 100)));
}
