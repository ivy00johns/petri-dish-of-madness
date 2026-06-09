/**
 * RoutingDegradedBanner (EM-072) — warns when the model A/B has collapsed.
 *
 * Shown on "/" near the header when useRoutingHealth reports degradation. The
 * signal is SMOOTHED (EM-072 follow-up): it trips only after several
 * consecutive one-model samples spanning ≥2 profiles, and clears only after a
 * couple of diverse samples — so this banner means "this run's comparison is
 * durably compromised", not a per-call status light, and it no longer flaps
 * with FreeLLMAPI's rate-limit windows.
 *
 * The banner is dismissible per degradation signature (model name) — if
 * routing collapses onto a DIFFERENT model later, the banner returns. When the
 * degradation CLEARS, a transient "routing recovered" strip shows for a few
 * seconds (health.recovered) so the state change is legible instead of the
 * warning silently vanishing.
 *
 * Token-only styling (lab-warn register; lab-acid for the recovery note).
 */

import { useState } from 'react';
import type { RoutingHealth } from '../hooks/useRoutingHealth';

export function RoutingDegradedBanner({ health }: { health: RoutingHealth }) {
  // Dismissal is keyed by the degraded model so a new collapse re-surfaces it.
  const [dismissedFor, setDismissedFor] = useState<string | null>(null);

  // EM-072 follow-up: transient recovery note after the degradation clears.
  if (!health.degraded && health.recovered) {
    return (
      <div
        role="status"
        className="flex items-center gap-3 px-4 py-1.5 border-b border-lab-acid bg-lab-acid/10 shrink-0"
      >
        <span className="font-mono text-xs text-lab-acid shrink-0" aria-hidden="true">
          ✓
        </span>
        <p className="flex-1 min-w-0 font-mono text-[11px] text-lab-acid leading-snug">
          <span className="font-bold uppercase tracking-wide">Routing recovered</span> —
          profiles are resolving to distinct models again; the model-vs-model comparison is
          valid from here on.
        </p>
      </div>
    );
  }

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
