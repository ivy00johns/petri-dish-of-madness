/**
 * RoutingDegradedBanner (EM-072) — warns when the model A/B has collapsed.
 *
 * Shown on "/" near the header when useRoutingHealth reports degradation:
 * ≥2 distinct living profiles, all recently served by ONE routed model. The
 * banner is dismissible per degradation signature (model name) — if routing
 * collapses onto a DIFFERENT model later, the banner returns.
 *
 * Token-only styling (lab-warn register).
 */

import { useState } from 'react';
import type { RoutingHealth } from '../hooks/useRoutingHealth';

export function RoutingDegradedBanner({ health }: { health: RoutingHealth }) {
  // Dismissal is keyed by the degraded model so a new collapse re-surfaces it.
  const [dismissedFor, setDismissedFor] = useState<string | null>(null);

  if (!health.degraded || !health.model) return null;
  if (dismissedFor === health.model) return null;

  return (
    <div
      role="alert"
      className="flex items-center gap-3 px-4 py-1.5 border-b border-lab-warn bg-lab-warn/10 shrink-0"
    >
      <span className="font-mono text-xs text-lab-warn shrink-0" aria-hidden="true">
        ⚠
      </span>
      <p className="flex-1 min-w-0 font-mono text-[11px] text-lab-warn leading-snug">
        <span className="font-bold uppercase tracking-wide">Routing degraded:</span>{' '}
        all {health.profileCount} profiles are being served by{' '}
        <span className="font-bold">{health.model}</span> — model-vs-model comparison is
        not valid for this run.
      </p>
      <button
        type="button"
        onClick={() => setDismissedFor(health.model)}
        className="shrink-0 font-mono text-[10px] uppercase tracking-wide px-1.5 py-0.5 border border-lab-warn text-lab-warn hover:bg-lab-warn/20 transition-colors rounded-sm"
        aria-label="Dismiss the routing-degraded warning"
      >
        ✕ dismiss
      </button>
    </div>
  );
}
