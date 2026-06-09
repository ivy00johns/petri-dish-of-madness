/**
 * InspectorLayout — the 2D analysis annex (frontend-inspector.md §0/§4).
 *
 * This is the full-2D screen reached at /inspector. It mounts NO Three.js
 * <Canvas> and never touches WebGL — visiting it lets the GPU rest while you
 * dissect a run. The panels below are W5 placeholders; each is wired to the
 * backend read API (event-log.md §7) at W6:
 *
 *   Replay (EM-055) · Decision Trace (EM-056) · Governance (EM-057)
 *   Social Graph (EM-058) · AWI Dashboard (EM-059)
 *
 * The 3D cozy village remains the PRIMARY experience at "/"; this is the
 * analysis annex, not a demotion of it.
 */

import type { WorldState, WorldEvent } from '../types';

interface InspectorPanel {
  key: string;
  title: string;
  item: string;
  blurb: string;
  /** Spans two columns in the responsive grid (wide time-series surfaces). */
  wide?: boolean;
}

const PANELS: InspectorPanel[] = [
  {
    key: 'replay',
    title: 'Replay',
    item: 'EM-055',
    blurb:
      'Scrub the run on a timeline — play / pause / step / speed, with a top-down Canvas2D map and event markers color-coded by type.',
    wide: true,
  },
  {
    key: 'decision-trace',
    title: 'Decision Trace',
    item: 'EM-056',
    blurb:
      'Pick a turn to unfold its linked chain: perceived → memory_retrieved → llm_call → reasoning → action_chosen → action_resolved, with model, tokens, and state deltas.',
  },
  {
    key: 'governance',
    title: 'Governance History',
    item: 'EM-057',
    blurb:
      'Proposal lifecycle timeline and downstream-consequence links — the failures made visible.',
  },
  {
    key: 'social-graph',
    title: 'Social Graph',
    item: 'EM-058',
    blurb:
      'Force-directed graph of agents (colored by model) and their relationships, time-scrubbable, frozen once the layout settles.',
  },
  {
    key: 'awi-dashboard',
    title: 'AWI Dashboard',
    item: 'EM-059',
    blurb:
      'Nine agent-welfare indicators side by side plus the model-vs-model cut — no composite score.',
    wide: true,
  },
];

interface InspectorLayoutProps {
  /** Live world projection (used for the run summary strip). */
  world: WorldState | null;
  /**
   * Rolling event history (event-log.md §3 / useSimulation history ref). Wired
   * to the panels at W6; surfaced here so the screen reflects real run depth.
   */
  history: WorldEvent[];
  mockMode: boolean;
}

export function InspectorLayout({ world, history, mockMode }: InspectorLayoutProps) {
  const aliveAgents = world?.agents.filter((a) => a.alive).length ?? 0;
  const totalAgents = world?.agents.length ?? 0;

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
        <SummaryStat label="TICK" value={String(world?.tick ?? 0).padStart(4, '0')} />
        <SummaryStat label="DAY" value={String(world?.day ?? 0)} />
        <SummaryStat label="AGENTS" value={`${aliveAgents}/${totalAgents}`} />
        <SummaryStat label="RULES" value={String(world?.rules.length ?? 0)} />
        <SummaryStat label="HISTORY" value={`${history.length} events`} />
        {mockMode && (
          <span className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-acid text-lab-acid bg-lab-acid/10">
            MOCK
          </span>
        )}
      </div>

      {/* Panel grid */}
      <div className="flex-1 min-h-0 overflow-y-auto p-4">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 auto-rows-min">
          {PANELS.map((panel) => (
            <InspectorPanelCard key={panel.key} panel={panel} />
          ))}
        </div>

        <p className="mt-4 font-mono text-[10px] text-lab-dim leading-relaxed">
          These analysis views are wired to the backend event log at W6. The
          rolling event history is already accumulating from the live feed.
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

function InspectorPanelCard({ panel }: { panel: InspectorPanel }) {
  return (
    <section
      className={`lab-panel flex flex-col min-h-[9rem] ${panel.wide ? 'lg:col-span-2' : ''}`}
      aria-label={`${panel.title} panel (coming in W6)`}
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <span>{panel.title}</span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          {panel.item}
        </span>
      </div>
      <div className="flex-1 flex flex-col items-center justify-center gap-2 px-4 py-6 text-center">
        <p className="font-mono text-xs text-lab-muted leading-relaxed max-w-prose">
          {panel.blurb}
        </p>
        <span className="font-mono text-[10px] uppercase tracking-widest text-lab-dim border border-lab-border px-2 py-0.5">
          Wired at W6
        </span>
      </div>
    </section>
  );
}
