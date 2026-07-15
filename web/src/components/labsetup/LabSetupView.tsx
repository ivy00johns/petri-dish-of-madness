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
      <div className="labsetup">
        <p role="alert" className="labsetup-loaderror">
          Couldn’t load Lab Setup — is the backend running? ({loadError})
        </p>
      </div>
    );
  }
  if (!flags) return <div className="labsetup"><p>Loading Lab Setup…</p></div>;
  return (
    <div className="labsetup">
      <h2>Lab Setup — compose the next run</h2>
      <div className="labsetup-grid">
        <FlagBoard flags={flags} pending={pending} onToggle={onToggle} />
        <div className="labsetup-centerpiece">
          <EstimatePanel estimate={estimate} loading={estimating} />
          <RecommenderPanel rec={rec} />
        </div>
        <CapabilityTable cap={cap} />
      </div>
      <ApplyBar diff={diff} onApply={onApply} result={applyResult} busy={busy} />
    </div>
  );
}
