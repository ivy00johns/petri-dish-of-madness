/**
 * InspectorLayout — the 2D analysis annex (frontend-inspector.md §0/§4/§7).
 *
 * Full-2D screen reached at /inspector. Mounts NO Three.js <Canvas> and never
 * touches WebGL — visiting it lets the GPU rest while you dissect a run.
 *
 * It OWNS the shared scrub position (`currentTick`, default = maxTick = latest)
 * and the run's `maxTick`. The ReplayScrubber drives `currentTick`; every other
 * panel re-projects AT `currentTick` (scrub once, everything follows). All four
 * data panels receive the SAME PanelProps bag:
 *
 *   { events, agents, profiles, currentTick, maxTick }
 *
 * The panels' PRIMARY data source is the client-side rolling history
 * (`useSimulation.history`) via the pure selectors in selectors.ts, so they
 * render in MOCK mode with no backend. The four panel imports are STUBS at this
 * stage; stage-2 agents replace DecisionTrace / GovernanceHistory / SocialGraph
 * / AWIDashboard in place against this exact PanelProps contract.
 *
 * The 3D cozy village remains the PRIMARY experience at "/"; this is the
 * analysis annex, not a demotion of it.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { WorldState, WorldEvent } from '../types';
import type { PanelProps } from './types';
import { maxTick as selectMaxTick } from './selectors';
import { ReplayScrubber } from './ReplayScrubber';
import DecisionTrace from './DecisionTrace';
import GovernanceHistory from './GovernanceHistory';
import SocialGraph from './SocialGraph';
import AWIDashboard from './AWIDashboard';

interface InspectorLayoutProps {
  /** Live world projection (run summary strip + agents/profiles/places). */
  world: WorldState | null;
  /** Rolling event history (newest-first) — the panels' primary data source. */
  history: WorldEvent[];
  mockMode: boolean;
  /**
   * Optional live seek into the deep-replay window (frontend-inspector.md §3).
   * In mock mode the panels re-project from `history` and this is a no-op.
   */
  onSeekTick?: (tick: number) => void;
}

export function InspectorLayout({ world, history, mockMode, onSeekTick }: InspectorLayoutProps) {
  const agents = useMemo(() => world?.agents ?? [], [world]);
  const profiles = useMemo(() => world?.profiles ?? [], [world]);
  const places = useMemo(
    () => (world?.places ?? []).map((p) => ({ id: p.id, x: p.x, y: p.y })),
    [world],
  );

  const maxTick = useMemo(() => Math.max(selectMaxTick(history), world?.tick ?? 0), [history, world]);

  // Shared scrub position. Default = maxTick = the latest tick; it follows the
  // live edge until the user scrubs back, then stays pinned where they left it.
  const [currentTick, setCurrentTick] = useState(maxTick);
  const pinnedRef = useRef(false);
  useEffect(() => {
    if (!pinnedRef.current) setCurrentTick(maxTick);
  }, [maxTick]);

  const handleSeek = (tick: number) => {
    const clamped = Math.max(0, Math.min(maxTick, tick));
    // If the user scrubs to the live edge, resume following; otherwise pin.
    pinnedRef.current = clamped < maxTick;
    setCurrentTick(clamped);
    onSeekTick?.(clamped);
  };

  const panelProps: PanelProps = { events: history, agents, profiles, currentTick, maxTick };

  const aliveAgents = agents.filter((a) => a.alive).length;
  const totalAgents = agents.length;

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden bg-lab-bg text-lab-text">
      {/* Annex header */}
      <div className="lab-header flex items-center justify-between gap-2 shrink-0">
        <span>INSPECTOR · ANALYSIS ANNEX</span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          2D analysis — the 3D village is the live view
        </span>
      </div>

      {/* Run summary strip */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2 border-b border-lab-border bg-lab-surface shrink-0">
        <SummaryStat label="TICK" value={String(currentTick).padStart(4, '0')} />
        <SummaryStat label="DAY" value={String(world?.day ?? 0)} />
        <SummaryStat label="AGENTS" value={`${aliveAgents}/${totalAgents}`} />
        <SummaryStat label="RULES" value={String(world?.rules.length ?? 0)} />
        <SummaryStat label="HISTORY" value={`${history.length} events`} />
        {currentTick < maxTick && (
          <span className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-acid text-lab-acid bg-lab-acid/10">
            REPLAY @ {currentTick} / {maxTick}
          </span>
        )}
        {mockMode && (
          <span className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-acid text-lab-acid bg-lab-acid/10">
            MOCK
          </span>
        )}
      </div>

      {/* Scrollable analysis body */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-4">
        {/* Replay scrubber drives the shared currentTick (full-width). */}
        <ReplayScrubber
          events={history}
          agents={agents}
          profiles={profiles}
          places={places}
          currentTick={currentTick}
          maxTick={maxTick}
          onSeek={handleSeek}
        />

        {/* Four data panels — each re-projects AT currentTick. */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 auto-rows-fr">
          <DecisionTrace {...panelProps} />
          <GovernanceHistory {...panelProps} />
          <SocialGraph {...panelProps} />
          <AWIDashboard {...panelProps} />
        </div>

        <p className="font-mono text-[10px] text-lab-dim leading-relaxed">
          Panels compute from the client-side rolling history (mock-safe, no
          backend). Scrub above; every panel follows the shared tick.
        </p>
      </div>
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-[10px] text-lab-muted">{label}</span>
      <span className="font-mono text-xs font-bold tabular-nums text-lab-text">{value}</span>
    </div>
  );
}
