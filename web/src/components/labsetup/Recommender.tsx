import type { Recommendation } from '../../types';

export function RecommenderPanel({ rec }: { rec: Recommendation | null }) {
  if (!rec) return null;
  return (
    <div className="labsetup-recommender" data-verdict={rec.verdict}>
      <p className="labsetup-verdict" role="status">{rec.banner}</p>
      <div className="labsetup-lanesets">
        <div><h4>Safe</h4><ul>{rec.safe.map((l) => <li key={l}>{l}</li>)}</ul></div>
        <div><h4>Risky</h4><ul>{rec.risky.map((l) => <li key={l}>{l}</li>)}</ul></div>
      </div>
      {rec.castPinRisks.length > 0 && (
        <div className="labsetup-pinrisks">
          <h4>Cast pins at risk on this combo</h4>
          <ul>
            {rec.castPinRisks.map((c) => (
              <li key={c.agent}>{c.agent} → {c.lane}: {c.reason}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
