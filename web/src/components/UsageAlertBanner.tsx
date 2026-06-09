/**
 * UsageAlertBanner (W11b EM-083) — surfaces `usage_alert` events as a
 * dismissible amber banner, the same idiom as RoutingDegradedBanner.
 *
 * Event payload (event-log.md v1.3.0): {provider, metric:"rpd"|"tpd", pct,
 * limit} — emitted once per provider/metric/window when usage crosses 70% of
 * a configured cap. The banner shows the LATEST alert per provider+metric.
 *
 * Re-arming: dismissal is keyed by the alert event's seq, so the NEXT window's
 * alert (a new event = a new seq) re-raises the banner even after a dismissal
 * — exactly the contract's "auto-clears next window" semantics, inverted into
 * "re-arms next window".
 *
 * Token-only styling (lab-warn register). Renders nothing with no alerts.
 */

import { useMemo, useState } from 'react';
import type { WorldEvent } from '../types';

interface UsageAlert {
  seq: number;
  provider: string;
  metric: string;
  pct: number;
  limit: number | null;
}

const METRIC_LABEL: Record<string, string> = {
  rpd: 'request',
  tpd: 'token',
};

/** Latest usage_alert per provider+metric (pure; exported for reuse/tests). */
export function latestUsageAlerts(history: WorldEvent[]): UsageAlert[] {
  const byKey = new Map<string, UsageAlert>();
  for (const e of history) {
    if (e.kind !== 'usage_alert') continue;
    const p = e.payload ?? {};
    const provider = typeof p.provider === 'string' ? p.provider : 'unknown provider';
    const metric = typeof p.metric === 'string' ? p.metric : '';
    const pct = typeof p.pct === 'number' ? p.pct : NaN;
    if (!Number.isFinite(pct)) continue;
    const key = `${provider}|${metric}`;
    const cur = byKey.get(key);
    if (!cur || e.seq > cur.seq) {
      byKey.set(key, {
        seq: e.seq,
        provider,
        metric,
        pct,
        limit: typeof p.limit === 'number' ? p.limit : null,
      });
    }
  }
  return [...byKey.values()].sort((a, b) => b.pct - a.pct);
}

export function UsageAlertBanner({ history }: { history: WorldEvent[] }) {
  // Dismissals are keyed by event seq: a fresh alert (next window) has a new
  // seq, so it shows again even if the previous one was dismissed.
  const [dismissed, setDismissed] = useState<ReadonlySet<number>>(new Set());

  const alerts = useMemo(() => latestUsageAlerts(history), [history]);
  const visible = alerts.filter((a) => !dismissed.has(a.seq));

  if (visible.length === 0) return null;

  return (
    <div className="shrink-0">
      {visible.map((a) => (
        <div
          key={`${a.provider}|${a.metric}`}
          role="alert"
          className="flex items-center gap-3 px-4 py-1.5 border-b border-lab-warn bg-lab-warn/10"
        >
          <span className="font-mono text-xs text-lab-warn shrink-0" aria-hidden="true">
            ⚠
          </span>
          <p className="flex-1 min-w-0 m-0 font-mono text-[11px] text-lab-warn leading-snug">
            <span className="font-bold uppercase tracking-wide">Usage alert:</span>{' '}
            <span className="font-bold">{a.provider}</span> at{' '}
            <span className="font-bold tabular-nums">{Math.round(a.pct)}%</span> of its daily{' '}
            {METRIC_LABEL[a.metric] ?? a.metric} cap
            {a.limit !== null && (
              <span className="text-lab-warn/80"> (limit {a.limit.toLocaleString()})</span>
            )}{' '}
            — routing may degrade when it trips.
          </p>
          <button
            type="button"
            onClick={() => setDismissed((cur) => new Set(cur).add(a.seq))}
            className="shrink-0 font-mono text-[10px] uppercase tracking-wide px-1.5 py-0.5 border border-lab-warn text-lab-warn hover:bg-lab-warn/20 transition-colors rounded-sm"
            aria-label={`Dismiss the ${a.provider} usage alert`}
          >
            ✕ dismiss
          </button>
        </div>
      ))}
    </div>
  );
}
