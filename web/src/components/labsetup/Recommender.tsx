import type { Recommendation, Verdict } from '../../types';

const VERDICT_STYLE: Record<Verdict, string> = {
  free_clean_ok: 'border-lab-acid-dim text-lab-acid bg-lab-acid/5',
  free_at_risk: 'border-lab-warn text-lab-warn bg-lab-warn/5',
  needs_paid: 'border-lab-danger text-lab-danger bg-lab-danger/5',
};

export function RecommenderPanel({ rec }: { rec: Recommendation | null }) {
  if (!rec) return null;
  const verdictCls = VERDICT_STYLE[rec.verdict] ?? 'border-lab-border text-lab-text';
  return (
    <section className="labsetup-recommender border border-lab-border bg-lab-bg" data-verdict={rec.verdict}>
      <div className="px-3 py-1.5 border-b border-lab-border bg-lab-surface">
        <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-lab-text">
          Recommendation
        </span>
      </div>
      <div className="p-3 flex flex-col gap-3">
        <p className={`labsetup-verdict font-mono text-[11px] leading-snug px-2 py-1.5 border ${verdictCls}`} role="status">
          {rec.banner}
        </p>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <h4 className="font-mono text-[9px] uppercase tracking-wider text-lab-muted mb-1">
              Safe · clean lanes
            </h4>
            <ul className="flex flex-wrap gap-1">
              {rec.safe.length === 0
                ? <li className="font-mono text-[10px] text-lab-dim">none</li>
                : rec.safe.map((l) => (
                  <li key={l} className="font-mono text-[10px] text-lab-acid border border-lab-acid-dim px-1.5 py-0.5">{l}</li>
                ))}
            </ul>
          </div>
          <div>
            <h4 className="font-mono text-[9px] uppercase tracking-wider text-lab-muted mb-1">
              Risky · truncate-prone
            </h4>
            <ul className="flex flex-wrap gap-1">
              {rec.risky.length === 0
                ? <li className="font-mono text-[10px] text-lab-dim">none</li>
                : rec.risky.map((l) => (
                  <li key={l} className="font-mono text-[10px] text-lab-warn border border-lab-border px-1.5 py-0.5">{l}</li>
                ))}
            </ul>
          </div>
        </div>

        {rec.castPinRisks.length > 0 && (
          <div className="border border-lab-warn/40 bg-lab-warn/5 p-2">
            <h4 className="font-mono text-[9px] uppercase tracking-wider text-lab-warn mb-1">
              Cast pins at risk on this combo
            </h4>
            <ul className="flex flex-col gap-0.5">
              {rec.castPinRisks.map((c) => (
                <li key={c.agent} className="font-mono text-[10px] text-lab-muted-bright">
                  {c.agent} → {c.lane}: {c.reason}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
