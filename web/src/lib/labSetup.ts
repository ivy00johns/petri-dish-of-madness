// ============================================================
// Lab Setup admin panel — thin fetch wrappers over the config/flags,
// estimate, lane-capability, and config/apply endpoints (Tasks 1-4 on this
// branch). Raw fetch + status-code check, matching the codebase's existing
// non-inspector fetch convention (no shared base-URL helper here).
// ============================================================

import type {
  FlagsResponse, EstimateResult, CapabilityResponse, ApplyResult,
} from '../types';

const JSON_HEADERS = { 'Content-Type': 'application/json', Accept: 'application/json' };

/** GET /api/config/flags — baked flag values + the prompt_weight/routing_ops groups. */
export async function fetchFlags(): Promise<FlagsResponse> {
  const res = await fetch('/api/config/flags', { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`flags ${res.status}`);
  return res.json();
}

/** POST /api/estimate {overrides} — projected token cost under a flag override set. */
export async function postEstimate(overrides: Record<string, boolean>): Promise<EstimateResult> {
  const res = await fetch('/api/estimate', {
    method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ overrides }),
  });
  if (!res.ok) throw new Error(`estimate ${res.status}`);
  return res.json();
}

/** GET /api/lanes/capability — lane roster (provider/free/context/reliability) + cast pins. */
export async function fetchCapability(): Promise<CapabilityResponse> {
  const res = await fetch('/api/lanes/capability', { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`capability ${res.status}`);
  return res.json();
}

/** POST /api/config/apply {overrides} — bake the override set; returns the diff + restart flag. */
export async function postApply(overrides: Record<string, boolean>): Promise<ApplyResult> {
  const res = await fetch('/api/config/apply', {
    method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ overrides }),
  });
  if (!res.ok) throw new Error(`apply ${res.status}`);
  return res.json();
}
