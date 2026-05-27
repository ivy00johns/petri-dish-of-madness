/**
 * ModelLegend — maps profile color → model name.
 * The key to reading who's who in the chaos.
 */

import type { ModelProfile } from '../../types';

interface ModelLegendProps {
  profiles: ModelProfile[];
}

export function ModelLegend({ profiles }: ModelLegendProps) {
  return (
    <div className="flex flex-col">
      <div className="lab-header">MODEL LEGEND</div>
      <div className="p-2 space-y-1">
        {profiles.length === 0 ? (
          <div className="font-mono text-xs text-lab-dim py-1">NO PROFILES</div>
        ) : (
          profiles.map(p => (
            <div
              key={p.name}
              className="flex items-center gap-2 py-1 px-1.5 border border-transparent hover:border-lab-border/50 transition-colors duration-150"
            >
              {/* Color swatch */}
              <div
                className="w-3 h-3 shrink-0 rounded-sm"
                style={{ backgroundColor: p.color }}
                aria-hidden="true"
              />

              {/* Profile name */}
              <span
                className="font-mono text-xs font-semibold tracking-wide"
                style={{ color: p.color }}
              >
                {p.name}
              </span>

              {/* Model ID */}
              <span className="font-mono text-[10px] text-lab-muted truncate flex-1 text-right">
                {p.model_id}
              </span>

              {/* Availability dot */}
              <div
                className="w-1.5 h-1.5 rounded-full shrink-0"
                style={{ backgroundColor: p.available ? '#27ae60' : '#3a3a50' }}
                title={p.available ? 'Available' : 'Unavailable'}
              />
            </div>
          ))
        )}
      </div>
    </div>
  );
}
