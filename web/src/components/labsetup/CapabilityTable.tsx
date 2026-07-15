import type { CapabilityResponse } from '../../types';

const TAG_LABEL: Record<string, string> = {
  clean: '✓ clean', reasoning: '⚠ reasoning', unknown: '? unknown',
};

export function CapabilityTable({ cap }: { cap: CapabilityResponse | null }) {
  if (!cap) return <p>Loading lanes…</p>;
  return (
    <table className="labsetup-capability" aria-label="lane capability">
      <thead>
        <tr><th>Lane</th><th>Provider</th><th>Cost</th><th>Context</th><th>Reliability</th></tr>
      </thead>
      <tbody>
        {cap.lanes.map((l) => (
          <tr key={l.id} data-reliability={l.reliability}>
            <td>{l.id}</td>
            <td>{l.provider}</td>
            <td>{l.free ? 'free' : 'paid'}</td>
            <td>{l.context_window ? `${(l.context_window / 1000) | 0}k` : '—'}</td>
            <td>{TAG_LABEL[l.reliability] ?? l.reliability}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
