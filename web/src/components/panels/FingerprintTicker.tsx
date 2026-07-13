/**
 * FingerprintTicker (EM-313) — live behavioral stylometry in the feed margin.
 *
 * A compact, collapsible left-column strip that spotlights ONE agent's
 * converging model guess: a confidence bar that races upward turn by turn until
 * it locks ("93% cerebras-qwen"), a sparkline of that convergence, and the
 * X-Routed-Via ground-truth reveal (✓/✗). All the math is server-side
 * (GET /api/fingerprints, zero-LLM, versioned) — this is pure viewer chrome.
 *
 * Renders NOTHING when the backend has the feature OFF (default) or has no
 * agent worth showing yet, so it adds zero chrome until it fires (golden-safe,
 * mirrors WarPanel). Off the sim/replay surface entirely; no sim feedback.
 *
 * `FingerprintTickerView` is the pure presentational half (data in, no fetch)
 * so it is trivially testable; the default export is the polling container.
 */

import { useEffect, useRef, useState } from 'react';
import {
  fetchFingerprints,
  pickAgent,
  pct,
  shortModel,
  type FingerprintAgent,
  type FingerprintResponse,
} from '../../lib/fingerprint';
import '../../inspector/inspector-tokens.css';

const COLLAPSE_KEY = 'em.fingerprint.collapsed';
const POLL_MS = 4000;

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

/** Status → the accent CSS var driving the bar / chips. */
function accentVar(agent: FingerprintAgent): string {
  if (agent.correct === false) return 'var(--lab-danger)';
  if (agent.status === 'locked') return 'var(--lab-acid)';
  return 'var(--marker-governance)';
}

/** A tiny inline sparkline of the convergence series (confidence over turns). */
function Sparkline({ agent, color }: { agent: FingerprintAgent; color: string }) {
  const pts = agent.series;
  if (pts.length < 2) return null;
  const w = 56;
  const h = 14;
  const n = pts.length;
  const d = pts
    .map((p, i) => {
      const x = (i / (n - 1)) * w;
      const y = h - Math.max(0, Math.min(1, p.confidence)) * h;
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      className="shrink-0"
      aria-hidden="true"
      preserveAspectRatio="none"
    >
      <path d={d} fill="none" stroke={color} strokeWidth="1.25" />
    </svg>
  );
}

export interface FingerprintTickerViewProps {
  data: FingerprintResponse | null;
  activeAgentId?: string | null;
  /** id → display name; falls back to a truncated id. */
  names?: Record<string, string>;
}

export function FingerprintTickerView({
  data,
  activeAgentId,
  names,
}: FingerprintTickerViewProps) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  const agent = pickAgent(data, activeAgentId);
  // Nothing worth showing (disabled backend, no agents, or no turns) ⇒ zero
  // chrome, exactly like a peacetime WarPanel.
  if (!agent) return null;

  const name =
    (names && names[agent.agent_id]) ||
    (agent.agent_id.length > 12 ? `${agent.agent_id.slice(0, 12)}…` : agent.agent_id);
  const accent = accentVar(agent);
  const gathering = agent.status === 'gathering';
  const confidence = pct(agent.confidence);

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label="Fingerprint ticker — live model guess vs ground truth"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">
          🔬 FINGERPRINT
        </h2>
        <div className="flex items-center gap-2">
          {data?.reference_source === 'within_run' && (
            <span
              className="font-mono text-[9px] text-lab-dim normal-case tracking-normal"
              title="No historical runs yet — inferring from this run's other agents"
            >
              cold start
            </span>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand the fingerprint ticker' : 'Collapse the fingerprint ticker'}
            title={collapsed ? 'Expand the fingerprint ticker' : 'Collapse the fingerprint ticker'}
            className="font-mono text-[10px] px-1.5 py-0.5 border border-lab-border text-lab-muted
                       hover:border-lab-acid hover:text-lab-acid rounded-sm cursor-pointer
                       transition-colors duration-100"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="px-3 py-2">
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-mono text-[11px] text-lab-text truncate" title={name}>
              {name}
            </span>
            <span className="font-mono text-[9px] uppercase tracking-wider text-lab-dim tabular-nums">
              {agent.turns} turn{agent.turns === 1 ? '' : 's'}
            </span>
          </div>

          {gathering ? (
            <p className="m-0 mt-1 font-mono text-[10px] italic text-lab-muted leading-snug">
              gathering signal… not enough behavior to guess yet
            </p>
          ) : (
            <>
              <div className="mt-1.5 flex items-center gap-2">
                <span
                  className="font-mono text-[13px] font-semibold tabular-nums"
                  style={{ color: accent }}
                >
                  {confidence}%
                </span>
                <span
                  className="font-mono text-[12px] truncate"
                  style={{ color: accent }}
                  title={agent.guess ?? undefined}
                >
                  {shortModel(agent.guess)}
                </span>
                <Sparkline agent={agent} color={accent} />
              </div>

              {/* The racing bar. */}
              <div
                className="mt-1 h-1.5 w-full rounded-sm overflow-hidden"
                style={{ background: 'var(--lab-chrome)' }}
                role="progressbar"
                aria-valuenow={confidence}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label="model guess confidence"
              >
                <div
                  className="h-full rounded-sm transition-[width] duration-500"
                  style={{ width: `${confidence}%`, background: accent }}
                />
              </div>

              {/* Ground-truth reveal — the X-Routed-Via chip, scored ✓/✗. */}
              {agent.ground_truth != null && (
                <div className="mt-1.5 flex items-center gap-1.5 font-mono text-[10px]">
                  <span className="text-lab-dim uppercase tracking-wider">actual</span>
                  <span
                    className="px-1 py-px border rounded-sm truncate"
                    style={{ color: 'var(--lab-muted)', borderColor: 'var(--lab-border-bright)' }}
                    title={agent.ground_truth}
                  >
                    {shortModel(agent.ground_truth)}
                  </span>
                  {agent.correct != null && (
                    <span
                      className="ml-auto tabular-nums"
                      style={{ color: agent.correct ? 'var(--lab-acid)' : 'var(--lab-danger)' }}
                      aria-label={agent.correct ? 'guess correct' : 'guess wrong'}
                    >
                      {agent.correct ? '✓ locked on' : '✗ fooled'}
                    </span>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

export interface FingerprintTickerProps {
  /** Live tick — re-polls when it advances so the guess keeps converging. */
  tick?: number;
  /** Explicitly focused agent (from the 3D/roster selection), if any. */
  activeAgentId?: string | null;
  /** id → display name for the spotlighted agent. */
  names?: Record<string, string>;
  /** Scope to a specific run; omit for the active/live run. */
  runId?: number;
}

/**
 * Polling container. Fetches on mount + every POLL_MS, and immediately when the
 * tick advances. Stops polling once the backend reports the feature OFF (so a
 * disabled deployment makes exactly one request, then goes quiet).
 */
export default function FingerprintTicker({
  tick,
  activeAgentId,
  names,
  runId,
}: FingerprintTickerProps) {
  const [data, setData] = useState<FingerprintResponse | null>(null);
  const disabledRef = useRef(false);
  const inFlightRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      if (disabledRef.current || inFlightRef.current) return;
      inFlightRef.current = true;
      const res = await fetchFingerprints(runId);
      inFlightRef.current = false;
      if (cancelled) return;
      if (res && !res.enabled) {
        disabledRef.current = true; // feature off — stop polling
      }
      setData(res);
    }

    poll();
    const id = window.setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // Nudge a refetch when the tick advances (throttled by inFlightRef), so the
  // converging guess tracks the live feed without waiting the full interval.
  useEffect(() => {
    if (disabledRef.current || inFlightRef.current) return;
    let cancelled = false;
    (async () => {
      inFlightRef.current = true;
      const res = await fetchFingerprints(runId);
      inFlightRef.current = false;
      if (cancelled) return;
      if (res && !res.enabled) disabledRef.current = true;
      setData(res);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  return <FingerprintTickerView data={data} activeAgentId={activeAgentId} names={names} />;
}
