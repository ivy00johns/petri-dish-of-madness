/**
 * ExtinctionBanner (EM-071 UI) — total extinction finally gets its UX moment.
 *
 * Audit A2: a run where every villager starved kept showing RUNNING green with
 * only the animals acting. This component gives the run an ending:
 *
 *   • a prominent danger banner on "/" — "EXTINCTION — the last villager has
 *     died at tick T", plus the paused state when the backend auto-paused
 *     (`world_extinct.payload.auto_paused`, world.auto_pause_on_extinction);
 *   • an end-of-run summary card — ticks survived, the deaths in order, rules
 *     passed/rejected, crime count, and the top credit holder — computed from
 *     the event history with the pure projections in lib/extinction.ts
 *     (selector style, mock-safe).
 *
 * W11b (EM-107): renders through BannerFade inside the TopBannerLayer overlay
 * — appearing/clearing (a NEW RUN reset clears it) never reflows the app;
 * enter/exit is an opacity-only fade.
 *
 * Token-only styling (lab-danger register).
 */

import { useMemo, useState } from 'react';
import type { WorldState, WorldEvent } from '../types';
import { computeExtinction, computeRunSummary } from '../lib/extinction';
import { BannerFade } from './BannerFade';

export function ExtinctionBanner({
  world,
  events,
  onReset,
}: {
  world: WorldState | null;
  events: WorldEvent[];
  /**
   * EM-084: start a NEW RUN (POST /api/control/reset via useSimulation.reset).
   * The run is already over here, so this CTA is one-click — no confirm. The
   * reset clears the local history, which dismisses this banner.
   */
  onReset?: () => void;
}) {
  const extinction = useMemo(() => computeExtinction(world, events), [world, events]);
  const summary = useMemo(
    () => (extinction ? computeRunSummary(world, events, extinction.tick) : null),
    [world, events, extinction],
  );
  const [showSummary, setShowSummary] = useState(true);

  // EM-107: presence is managed by BannerFade (opacity-only enter/exit, kept
  // mounted through the exit fade); a never-extinct run renders nothing.
  const present = extinction !== null && summary !== null;

  return (
    <BannerFade show={present}>
      {present && (
    <div role="alert" className="border-b border-lab-danger bg-lab-danger/10">
      {/* The headline strip. */}
      <div className="flex items-center gap-3 px-4 py-2">
        <span className="font-mono text-sm text-lab-danger shrink-0" aria-hidden="true">
          ☠
        </span>
        <p className="flex-1 min-w-0 font-mono text-xs text-lab-danger leading-snug">
          <span className="font-bold uppercase tracking-widest">Extinction</span>
          {' — '}the last villager has died at tick{' '}
          <span className="font-bold tabular-nums">{extinction.tick}</span>.
          {extinction.autoPaused && (
            <span className="ml-2 font-mono text-[10px] font-bold uppercase tracking-wide px-1.5 py-px border border-lab-danger">
              simulation paused
            </span>
          )}
        </p>
        <button
          type="button"
          onClick={() => setShowSummary((s) => !s)}
          className="shrink-0 font-mono text-[10px] uppercase tracking-wide px-1.5 py-0.5 border border-lab-danger text-lab-danger hover:bg-lab-danger/20 transition-colors rounded-sm"
          aria-expanded={showSummary}
        >
          {showSummary ? 'hide summary' : 'end-of-run summary'}
        </button>
        {/* EM-084: the prominent restart CTA — no more restarting the service
            to get a fresh run. Acid register so it reads as THE next action. */}
        {onReset && (
          <button
            type="button"
            onClick={onReset}
            className="shrink-0 font-mono text-[11px] font-bold uppercase tracking-widest px-3 py-1 border border-lab-acid text-lab-acid bg-lab-acid/10 hover:bg-lab-acid/25 transition-colors rounded-sm"
            title="Rebuild the world from config and start a fresh run"
          >
            ⟲ NEW RUN
          </button>
        )}
      </div>

      {/* End-of-run summary card. */}
      {showSummary && (
        <div className="px-4 pb-3">
          <div className="lab-panel border-lab-danger/60 p-3 flex flex-col gap-2">
            <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-lab-danger">
              End of run
            </span>
            <div className="flex flex-wrap gap-x-6 gap-y-1.5">
              <SummaryStat label="ticks survived" value={String(summary.ticksSurvived)} />
              <SummaryStat
                label="rules passed / rejected"
                value={`${summary.rulesPassed} / ${summary.rulesRejected}`}
              />
              <SummaryStat label="crimes" value={String(summary.crimes)} />
              <SummaryStat
                label="top credit holder"
                value={
                  summary.topCreditHolder
                    ? `${summary.topCreditHolder.name} (¢${summary.topCreditHolder.credits})`
                    : '—'
                }
              />
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="font-mono text-[9px] uppercase tracking-wider text-lab-muted">
                deaths, in order
              </span>
              {summary.deaths.length === 0 ? (
                <span className="font-mono text-[10px] text-lab-dim">
                  no agent_died events in the loaded history
                </span>
              ) : (
                <p className="font-mono text-[10px] text-lab-text leading-relaxed">
                  {summary.deaths.map((d, i) => (
                    <span key={`${d.name}-${d.tick}-${i}`}>
                      {i > 0 && <span className="text-lab-dim"> → </span>}
                      {d.name}
                      <span className="text-lab-muted tabular-nums"> @t{d.tick}</span>
                    </span>
                  ))}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
      )}
    </BannerFade>
  );
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5 min-w-0">
      <span className="font-mono text-[9px] uppercase tracking-wider text-lab-muted shrink-0">
        {label}
      </span>
      <span className="font-mono text-xs font-bold tabular-nums text-lab-text truncate">
        {value}
      </span>
    </div>
  );
}
