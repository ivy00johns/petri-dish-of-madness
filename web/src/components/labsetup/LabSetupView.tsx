// web/src/components/labsetup/LabSetupView.tsx
//
// Lab Setup admin panel — the wired page. Loads the baked flags + lane
// capability, holds the pending flag combo, re-estimates prompt weight on
// every change, computes the baked-vs-pending diff, and applies overrides.
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FlagsResponse, EstimateResult, CapabilityResponse, ApplyResult } from '../../types';
import { fetchFlags, postEstimate, fetchCapability, postApply } from '../../lib/labSetup';
import { recommend, DEFAULT_THRESHOLDS } from '../../lib/recommender';
import { FlagBoard } from './FlagBoard';
import { EstimatePanel } from './EstimatePanel';
import { RecommenderPanel } from './Recommender';
import { CapabilityTable } from './CapabilityTable';
import { ApplyBar } from './ApplyBar';

export function LabSetupView() {
  const [flags, setFlags] = useState<FlagsResponse | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [estimate, setEstimate] = useState<EstimateResult | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [cap, setCap] = useState<CapabilityResponse | null>(null);
  const [applyResult, setApplyResult] = useState<ApplyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    fetchFlags()
      .then((f) => { setFlags(f); setPending({ ...f.baked }); })
      .catch((e) => { console.error('lab-setup: fetchFlags failed', e); setLoadError(String(e)); });
    fetchCapability()
      .then(setCap)
      .catch((e) => { console.error('lab-setup: fetchCapability failed', e); setLoadError(String(e)); });
  }, []);

  // Re-estimate whenever the pending combo changes (prompt-weight flags only).
  useEffect(() => {
    if (!flags) return;
    const overrides: Record<string, boolean> = {};
    for (const f of flags.groups.prompt_weight) overrides[f] = pending[f] ?? !!flags.baked[f];
    let cancelled = false;
    setEstimating(true);
    postEstimate(overrides)
      .then((r) => { if (!cancelled) setEstimate(r); })
      .catch((e) => { if (!cancelled) setEstimate({ ok: false, error: String(e) }); })
      .finally(() => { if (!cancelled) setEstimating(false); });
    return () => { cancelled = true; };
  }, [flags, pending]);

  const onToggle = useCallback((flag: string) => {
    setPending((p) => ({ ...p, [flag]: !(p[flag] ?? (flags?.baked[flag] ?? false)) }));
  }, [flags]);

  const diff = useMemo(() => {
    if (!flags) return [];
    return Object.keys(flags.baked)
      .filter((f) => (pending[f] ?? flags.baked[f]) !== flags.baked[f])
      .map((f) => ({ flag: f, from: !!flags.baked[f], to: !!pending[f] }));
  }, [flags, pending]);

  const rec = useMemo(
    () => (estimate?.ok && cap ? recommend(estimate, cap, DEFAULT_THRESHOLDS) : null),
    [estimate, cap],
  );

  const onApply = useCallback(async () => {
    const overrides: Record<string, boolean> = {};
    for (const d of diff) overrides[d.flag] = d.to;
    setBusy(true);
    try { setApplyResult(await postApply(overrides)); }
    finally { setBusy(false); }
  }, [diff]);

  if (loadError && !flags) {
    return (
      <div className="labsetup bg-lab-bg text-lab-text font-mono h-full overflow-y-auto p-4">
        <p role="alert" className="labsetup-loaderror border border-lab-danger text-lab-danger text-[11px] px-3 py-2">
          Couldn’t load Lab Setup — is the backend running? ({loadError})
        </p>
      </div>
    );
  }
  if (!flags) {
    return (
      <div className="labsetup bg-lab-bg text-lab-text font-mono h-full overflow-y-auto p-4">
        <p className="text-[11px] text-lab-muted animate-pulse">Loading Lab Setup…</p>
      </div>
    );
  }
  return (
    <div className="labsetup bg-lab-bg text-lab-text font-mono h-full overflow-y-auto">
      <div className="max-w-[1600px] mx-auto p-4 pb-24">
        <header className="mb-4">
          <h2 className="text-sm font-bold uppercase tracking-widest text-lab-text">
            Lab Setup <span className="text-lab-acid">— compose the next run</span>
          </h2>
          <p className="mt-0.5 text-[10px] text-lab-muted">
            Toggle flags → see the prompt size the combo generates and the lane tier it needs.
            Changes bake on the next <span className="text-lab-muted-bright">./dev</span> restart.
          </p>
        </header>

        {loadError && (
          <p role="alert" className="labsetup-loaderror mb-3 border border-lab-warn text-lab-warn text-[10px] px-3 py-1.5">
            Some Lab Setup data failed to load ({loadError}) — showing what loaded.
          </p>
        )}

        <div className="labsetup-grid grid gap-3 lg:grid-cols-[340px_1fr] items-start">
          <FlagBoard flags={flags} pending={pending} onToggle={onToggle} />
          <div className="labsetup-centerpiece flex flex-col gap-3 min-w-0">
            <EstimatePanel estimate={estimate} loading={estimating} />
            <RecommenderPanel rec={rec} />
            <CapabilityTable cap={cap} />
          </div>
        </div>
      </div>

      <div className="sticky bottom-0 border-t border-lab-border bg-lab-bg/95 backdrop-blur px-4 py-2">
        <div className="max-w-[1600px] mx-auto">
          <ApplyBar diff={diff} onApply={onApply} result={applyResult} busy={busy} />
        </div>
      </div>
    </div>
  );
}
