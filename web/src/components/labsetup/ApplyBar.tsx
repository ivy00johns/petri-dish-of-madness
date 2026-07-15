import type { ApplyResult } from '../../types';

interface DiffRow { flag: string; from: boolean; to: boolean; }

export function ApplyBar({ diff, onApply, result, busy }: {
  diff: DiffRow[]; onApply: () => void; result: ApplyResult | null; busy: boolean;
}) {
  const nothing = diff.length === 0;
  return (
    <div className="labsetup-applybar">
      {nothing ? (
        <span>No pending changes.</span>
      ) : (
        <ul className="labsetup-diff">
          {diff.map((d) => (
            <li key={d.flag}>{d.flag}: {String(d.from)} → <strong>{String(d.to)}</strong></li>
          ))}
        </ul>
      )}
      <button disabled={nothing || busy} onClick={onApply}>
        {busy ? 'Applying…' : 'Apply & restart'}
      </button>
      {result && (
        result.ok === false ? (
          <p className="labsetup-applymsg error" role="alert">Apply failed: {result.error}</p>
        ) : (
          <p className="labsetup-applymsg" role="status">
            {result.message}{result.restart_required ? ' (restart ./dev to bake)' : ''}
          </p>
        )
      )}
    </div>
  );
}
