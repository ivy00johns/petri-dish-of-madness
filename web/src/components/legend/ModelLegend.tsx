/**
 * ModelLegend — maps profile color → model name.
 * The key to reading who's who in the chaos.
 *
 * EM-104: collapsible — with 8 profiles the legend eats serious vertical space
 * in the controls column, so the header is now a disclosure button. Collapsed
 * it shows just "MODELS (N)"; the state persists to localStorage and defaults
 * to expanded.
 */

import { useEffect, useState } from 'react';
import type { ModelProfile } from '../../types';

interface ModelLegendProps {
  profiles: ModelProfile[];
}

const COLLAPSE_KEY = 'em.legend.collapsed';

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

export function ModelLegend({ profiles }: ModelLegendProps) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
  }, [collapsed]);

  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
        title={collapsed ? 'Expand the model legend' : 'Collapse the model legend'}
        className="lab-header w-full flex items-center justify-between cursor-pointer
                   hover:text-lab-acid transition-colors duration-100 text-left"
      >
        <span>MODELS ({profiles.length})</span>
        <span aria-hidden="true" className="text-[10px]">{collapsed ? '▸' : '▾'}</span>
      </button>

      {!collapsed && (
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
                  className={`w-1.5 h-1.5 rounded-full shrink-0 ${p.available ? 'bg-lab-acid-dim' : 'bg-lab-dim'}`}
                  title={p.available ? 'Available' : 'Unavailable'}
                />
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
