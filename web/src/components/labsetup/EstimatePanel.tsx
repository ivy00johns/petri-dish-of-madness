import type { EstimateResult } from '../../types';

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <section className="labsetup-estimate border border-lab-border-bright bg-lab-bg">
      <div className="px-3 py-1.5 border-b border-lab-border bg-lab-surface">
        <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-lab-text">
          Prompt-size estimate
        </span>
      </div>
      {children}
    </section>
  );
}

export function EstimatePanel({ estimate, loading }: {
  estimate: EstimateResult | null; loading: boolean;
}) {
  if (loading) {
    return <Shell><p className="font-mono text-[10px] text-lab-muted p-3 animate-pulse">Estimating…</p></Shell>;
  }
  if (!estimate) {
    return <Shell><p className="font-mono text-[10px] text-lab-muted p-3">Toggle a flag to estimate.</p></Shell>;
  }
  if (!estimate.ok) {
    return (
      <Shell>
        <div className="p-3 font-mono text-[10px]" role="alert">
          <strong className="text-lab-danger uppercase tracking-wide">Couldn’t estimate.</strong>{' '}
          <span className="text-lab-muted-bright">{estimate.error}</span>
        </div>
      </Shell>
    );
  }
  const total = estimate.total_input_tokens ?? 0;
  const rows = estimate.breakdown ?? [];
  const max = Math.max(1, ...rows.map((r) => r.tokens));
  return (
    <Shell>
      <div className="p-3">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-3xl font-bold tabular-nums text-lab-acid leading-none">
            ≈ {total.toLocaleString()}
          </span>
          <span className="font-mono text-[10px] uppercase tracking-wide text-lab-muted">input tokens</span>
        </div>
        <div className="mt-1 font-mono text-[9px] text-lab-dim">
          output budget {estimate.output_budget} · tokenizer {estimate.tokenizer}
        </div>

        <ul className="labsetup-breakdown mt-3 flex flex-col gap-1">
          {rows.map((r) => (
            <li key={r.key} className="grid grid-cols-[7rem_1fr_auto] items-center gap-2">
              <span className={`font-mono text-[10px] truncate ${r.key === 'base' ? 'text-lab-muted-bright' : 'text-lab-text'}`}>
                {r.key}
              </span>
              <span className="h-2 bg-lab-chrome border border-lab-border overflow-hidden">
                <span
                  className={`block h-full ${r.key === 'base' ? 'bg-lab-border-bright' : 'bg-lab-acid-dim'}`}
                  style={{ width: `${Math.max(2, (r.tokens / max) * 100)}%` }}
                />
              </span>
              <span className="font-mono text-[10px] tabular-nums text-lab-muted w-14 text-right">
                {r.tokens.toLocaleString()}
              </span>
            </li>
          ))}
        </ul>

        {estimate.base_note && (
          <p className="mt-3 font-mono text-[9px] text-lab-dim italic">{estimate.base_note}</p>
        )}
      </div>
    </Shell>
  );
}
