import type { CapabilityResponse } from '../../types';

const TAG: Record<string, { label: string; cls: string }> = {
  clean: { label: '● clean', cls: 'text-lab-acid' },
  reasoning: { label: '▲ reasoning', cls: 'text-lab-warn' },
  unknown: { label: '? unknown', cls: 'text-lab-muted' },
};

export function CapabilityTable({ cap }: { cap: CapabilityResponse | null }) {
  return (
    <section className="border border-lab-border bg-lab-bg" aria-label="lane capability">
      <div className="px-3 py-1.5 border-b border-lab-border bg-lab-surface">
        <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-lab-text">
          Lane capability
        </span>
      </div>
      {!cap ? (
        <p className="font-mono text-[10px] text-lab-muted p-3">Loading lanes…</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="labsetup-capability w-full border-collapse font-mono text-[10px]">
            <thead>
              <tr className="text-lab-muted uppercase tracking-wide">
                <th className="text-left font-medium py-1 px-3">Lane</th>
                <th className="text-left font-medium py-1 px-2">Provider</th>
                <th className="text-left font-medium py-1 px-2">Cost</th>
                <th className="text-right font-medium py-1 px-2">Context</th>
                <th className="text-right font-medium py-1 px-3">Reliability</th>
              </tr>
            </thead>
            <tbody>
              {cap.lanes.map((l) => {
                const tag = TAG[l.reliability] ?? { label: l.reliability, cls: 'text-lab-muted' };
                return (
                  <tr key={l.id} data-reliability={l.reliability}
                      className="border-t border-lab-border text-lab-text">
                    <td className="py-1 px-3">{l.id}</td>
                    <td className="py-1 px-2 text-lab-muted">{l.provider}</td>
                    <td className={`py-1 px-2 ${l.free ? 'text-lab-acid' : 'text-lab-warn'}`}>
                      {l.free ? 'free' : 'paid'}
                    </td>
                    <td className="py-1 px-2 text-right tabular-nums text-lab-muted">
                      {l.context_window ? `${Math.floor(l.context_window / 1000)}k` : '—'}
                    </td>
                    <td className={`py-1 px-3 text-right ${tag.cls}`}>{tag.label}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
