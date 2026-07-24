import type { CapabilityResponse, EstimateResult, Recommendation, Verdict } from '../types';

export const DEFAULT_THRESHOLDS = { tClean: 4500, tPaid: 8000 };

export function recommend(
  estimate: EstimateResult,
  cap: CapabilityResponse,
  thresholds: { tClean: number; tPaid: number },
): Recommendation {
  const tokens = estimate.total_input_tokens ?? 0;

  // Fail-closed: only `clean` lanes are ever "safe". reasoning/unknown are risky.
  const safe = cap.lanes.filter((l) => l.reliability === 'clean').map((l) => l.id);
  const risky = cap.lanes.filter((l) => l.reliability !== 'clean').map((l) => l.id);

  let verdict: Verdict;
  let banner: string;
  if (tokens <= thresholds.tClean) {
    verdict = 'free_clean_ok';
    banner = `≈${tokens} input tokens → free clean lanes OK.`;
  } else if (tokens <= thresholds.tPaid) {
    verdict = 'free_at_risk';
    banner = `≈${tokens} → known risk: free lanes may truncate. Run paid/best, or drop a flag.`;
  } else {
    verdict = 'needs_paid';
    banner = `≈${tokens} → free lanes will truncate. Use a paid/best lane or trim the combo.`;
  }

  // Reasoning lanes truncate on the heavy strict-JSON turn regardless of size.
  const riskyIds = new Set(risky);
  const castPinRisks = Object.entries(cap.cast_pins)
    .filter(([, lane]) => riskyIds.has(lane))
    .map(([agent, lane]) => ({
      agent, lane,
      reason: 'reasoning/unproven lane — truncates strict-JSON on the heavy turn; bounce lands on auto',
    }));

  return { verdict, banner, safe, risky, castPinRisks };
}
