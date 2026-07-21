import type { ApplyResult } from '../../types';

interface DiffRow { flag: string; from: boolean; to: boolean; }

export function ApplyBar({ diff, onApply, result, busy }: {
  diff: DiffRow[]; onApply: () => void; result: ApplyResult | null; busy: boolean;
}) {
  const nothing = diff.length === 0;
  return (
    <div className="labsetup-applybar border border-lab-border-bright bg-lab-surface px-3 py-2 flex flex-wrap items-center gap-3">
      {nothing ? (
        <span className="font-mono text-[10px] text-lab-muted">No pending changes.</span>
      ) : (
        <ul className="labsetup-diff flex flex-wrap items-center gap-1.5">
          {diff.map((d) => (
            <li key={d.flag} className="font-mono text-[10px] text-lab-muted border border-lab-border px-1.5 py-0.5">
              <span className="text-lab-text">{d.flag}</span>{': '}
              {String(d.from)} → <strong className="text-lab-acid">{String(d.to)}</strong>
            </li>
          ))}
        </ul>
      )}
      <button
        disabled={nothing || busy}
        onClick={onApply}
        className={[
          'font-mono text-[10px] uppercase tracking-wide px-3 py-1 border transition-colors',
          nothing || busy
            ? 'text-lab-dim border-lab-border cursor-not-allowed'
            : 'text-lab-acid border-lab-acid-dim hover:bg-lab-acid hover:text-lab-bg',
        ].join(' ')}
      >
        {busy ? 'Applying…' : 'Apply & restart'}
      </button>
      {result && (
        result.ok === false ? (
          <p className="labsetup-applymsg font-mono text-[10px] text-lab-danger" role="alert">
            Apply failed: {result.error}
          </p>
        ) : (
          <p className="labsetup-applymsg font-mono text-[10px] text-lab-muted-bright" role="status">
            {result.message}
            {result.restart_required && <span className="text-lab-warn"> (restart ./dev to bake)</span>}
          </p>
        )
      )}
    </div>
  );
}
