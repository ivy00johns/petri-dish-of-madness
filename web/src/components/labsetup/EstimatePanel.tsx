// web/src/components/labsetup/EstimatePanel.tsx
import type { EstimateResult } from '../../types';

export function EstimatePanel({ estimate, loading }: {
  estimate: EstimateResult | null; loading: boolean;
}) {
  if (loading) return <p>Estimating…</p>;
  if (!estimate) return <p>Toggle a flag to estimate.</p>;
  if (!estimate.ok) {
    return (
      <div className="labsetup-estimate error" role="alert">
        <strong>Couldn’t estimate.</strong> <span>{estimate.error}</span>
      </div>
    );
  }
  const total = estimate.total_input_tokens ?? 0;
  const max = Math.max(1, ...(estimate.breakdown ?? []).map((r) => r.tokens));
  return (
    <div className="labsetup-estimate">
      <div className="labsetup-total">
        ≈ {total.toLocaleString()} input tokens
        <small> · output budget {estimate.output_budget} · {estimate.tokenizer}</small>
      </div>
      <ul className="labsetup-breakdown">
        {(estimate.breakdown ?? []).map((r) => (
          <li key={r.key}>
            <span className="labsetup-bd-key">{r.key}</span>
            <span className="labsetup-bd-bar" style={{ width: `${(r.tokens / max) * 100}%` }} />
            <span className="labsetup-bd-n">{r.tokens.toLocaleString()}</span>
          </li>
        ))}
      </ul>
      {estimate.base_note && <p className="labsetup-note">{estimate.base_note}</p>}
    </div>
  );
}
