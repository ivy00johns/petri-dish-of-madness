/**
 * InspectorLayout — the 2D analysis annex (frontend-inspector.md §0/§4/§7,
 * v1.1.0 §1–4 / EM-069).
 *
 * Full-2D screen reached at /inspector. Mounts NO Three.js <Canvas> and never
 * touches WebGL — visiting it lets the GPU rest while you dissect a run.
 *
 * It OWNS the shared scrub position (`currentTick`, default = maxTick = latest)
 * and the run's `maxTick`. The ReplayScrubber drives `currentTick`; every other
 * panel re-projects AT `currentTick` (scrub once, everything follows). All data
 * panels receive the SAME PanelProps bag.
 *
 * Deep replay (v1.1.0, NORMATIVE):
 *   • History arrives already BACKFILLED from GET /api/events (useSimulation
 *     pages the log on mount and merges the WS stream, deduped by seq), so a
 *     fresh page load mid-run renders the full run. While that backfill is in
 *     flight (`historyLoading`) the panels label it; if the memory cap dropped
 *     older events (`historyTruncated`) a notice says so.
 *   • Seeking to a tick the client history can't faithfully project (loading /
 *     truncated) fetches GET /api/replay?tick=T (useReplayMaterials) and folds
 *     the strict-left delta onto base.state through the SAME replayStateAt
 *     selector, via the snapshots prop + merged delta events.
 *   • While scrubbed (not pinned to the live edge) the panels receive SCOPED
 *     events (tick <= currentTick) and agents re-projected at the scrub tick —
 *     live-edge data never bleeds into a replayed view (audit C8).
 *
 * The 3D cozy village remains the PRIMARY experience at "/"; this is the
 * analysis annex, not a demotion of it.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { WorldState, WorldEvent } from '../types';
import type { PanelProps } from './types';
import {
  maxTick as selectMaxTick,
  replayStateAt,
  activeRuleCount,
  dayAt,
  agentEconomyAt,
} from './selectors';
import type { ReplaySnapshot } from './selectors';
import { useReplayMaterials } from './useReplayMaterials';
import type { RoutingHealth } from '../hooks/useRoutingHealth';
import { ReplayScrubber } from './ReplayScrubber';
import DecisionTrace from './DecisionTrace';
import GovernanceHistory from './GovernanceHistory';
import SocialGraph from './SocialGraph';
import AWIDashboard from './AWIDashboard';
import AnimalChaosFeed from './AnimalChaosFeed';

interface InspectorLayoutProps {
  /** Live world projection (run summary strip + agents/profiles/places). */
  world: WorldState | null;
  /** Backfilled + rolling event history (newest-first) — primary data source. */
  history: WorldEvent[];
  /** True while the /api/events backfill is still paging in (EM-069). */
  historyLoading?: boolean;
  /** True when older events were dropped at the memory cap (EM-069). */
  historyTruncated?: boolean;
  mockMode: boolean;
  /**
   * Live seek into the deep-replay window (frontend-inspector.md v1.1.0 §3):
   * App passes useSimulation.seekTick, which pauses the engine so the scrubbed
   * projection is stable. In mock mode the panels re-project from `history`.
   */
  onSeekTick?: (tick: number) => void;
  /** EM-072: compact routing-degraded note in the status strip. */
  routingHealth?: RoutingHealth;
}

export function InspectorLayout({
  world,
  history,
  historyLoading = false,
  historyTruncated = false,
  mockMode,
  onSeekTick,
  routingHealth,
}: InspectorLayoutProps) {
  const agents = useMemo(() => world?.agents ?? [], [world]);
  const profiles = useMemo(() => world?.profiles ?? [], [world]);
  const places = useMemo(
    () => (world?.places ?? []).map((p) => ({ id: p.id, x: p.x, y: p.y, name: p.name })),
    [world],
  );
  // W7: buildings surface as small status markers on the replay mini-map.
  const buildings = useMemo(() => world?.buildings ?? [], [world]);
  // W8/D4: the animal roster — the replay fold's position fallback.
  const animals = useMemo(() => world?.animals ?? [], [world]);

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

  // Scrubbed = projecting the past (not pinned to the advancing live edge).
  const scrubbed = currentTick < maxTick;

  // ── Deep replay (v1.1.0 §2): /api/replay when history can't project ────────
  // The client history is faithful once the backfill finished un-truncated;
  // otherwise a scrubbed tick needs the backend's snapshot + strict-left delta.
  const needsReplayMaterials = !mockMode && scrubbed && (historyLoading || historyTruncated);
  const { materials: replay, fetching: replayFetching } = useReplayMaterials(
    needsReplayMaterials,
    currentTick,
  );

  const replaySnapshots = useMemo<ReplaySnapshot[]>(
    () => (replay?.snapshot ? [replay.snapshot] : []),
    [replay],
  );

  // Full event pool: history merged with the replay delta, deduped by seq.
  // Unscoped — the scrubber's marker rail spans the whole run.
  const mergedEvents = useMemo(() => {
    const delta = replay?.events ?? [];
    if (delta.length === 0) return history;
    const seen = new Set(history.map((e) => e.seq));
    const extra = delta.filter((e) => !seen.has(e.seq));
    return extra.length > 0 ? [...extra, ...history] : history;
  }, [history, replay]);

  // C8: while scrubbed the panels get a SCOPED slice (tick <= currentTick), so
  // the advancing live edge never grows into a replayed projection.
  const panelEvents = useMemo(
    () => (scrubbed ? mergedEvents.filter((e) => e.tick <= currentTick) : mergedEvents),
    [mergedEvents, scrubbed, currentTick],
  );

  // W10 / audit C7: the time-projected replay frame at the scrub tick. The
  // scrubber's `buildings` prop was live-only (the C7 bug: a scrubbed map drew
  // TODAY's building status); while scrubbed it now receives the building
  // state folded from snapshot + construction events at tick T (replayStateAt
  // owns the fold; the live roster contributes display metadata only).
  const scrubFrame = useMemo(
    () =>
      scrubbed
        ? replayStateAt(mergedEvents, replaySnapshots, currentTick, agents, places, buildings, animals)
        : null,
    [scrubbed, mergedEvents, replaySnapshots, currentTick, agents, places, buildings, animals],
  );
  const scrubberBuildings = scrubFrame ? scrubFrame.buildings : buildings;

  // W10 / EM-075: per-agent energy/credits re-projected at the scrub tick.
  // Approach (see agentEconomyAt): the latest `turn_start` ≤ T carries an
  // authoritative {energy, credits} sample for its agent (event-log.md §3);
  // later `action_resolved.state_deltas` by the same agent fold on top. That
  // is exact at turn granularity — engine-internal energy decay and
  // target-side economy transfers are not per-agent evented, so agents WITHOUT
  // a turn_start in the scoped window keep their live values and the panels
  // mark the economy figures approximate ("~", with an explanatory title).
  const economyAtTick = useMemo(
    () => (scrubbed ? agentEconomyAt(panelEvents) : null),
    [scrubbed, panelEvents],
  );

  // C8: agents re-projected at the scrub tick (alive recomputed from deaths,
  // energy/credits from turn samples) so live-edge state doesn't read back
  // into the past.
  const panelAgents = useMemo(() => {
    if (!scrubbed) return agents;
    const deathTick = new Map<string, number>();
    for (const e of mergedEvents) {
      if (e.kind === 'agent_died' && e.actor_id) deathTick.set(e.actor_id, e.tick);
    }
    return agents.map((a) => {
      const died = deathTick.get(a.id);
      const alive = died === undefined ? a.alive : currentTick < died;
      const eco = economyAtTick?.get(a.id);
      if (!eco && alive === a.alive) return a;
      return {
        ...a,
        alive,
        energy: eco ? eco.energy : a.energy,
        credits: eco ? eco.credits : a.credits,
      };
    });
  }, [agents, mergedEvents, scrubbed, currentTick, economyAtTick]);

  // True when ≥1 agent's scrubbed energy/credits fell back to live values.
  const agentsApproximate =
    scrubbed && agents.some((a) => !(economyAtTick?.get(a.id)?.sampled ?? false));

  const panelProps: PanelProps = {
    events: panelEvents,
    agents: panelAgents,
    profiles,
    currentTick,
    maxTick,
    historyLoading,
    agentsApproximate,
  };

  // W10: the status strip follows the SCRUB tick while replaying (audit:
  // "strip mixes scrub tick with live agent count"). Agents alive at T come
  // from the re-projected panel agents; DAY from the latest turn_start ≤ T;
  // RULES = rules ACTIVE at T from the scoped governance lifecycle. HISTORY
  // stays live (it describes the in-memory window, not the projection).
  const aliveAgents = (scrubbed ? panelAgents : agents).filter((a) => a.alive).length;
  const totalAgents = agents.length;
  const stripDay = scrubbed ? dayAt(panelEvents, world?.day ?? 0) : world?.day ?? 0;
  const stripRules = scrubbed
    ? activeRuleCount(panelEvents)
    : (world?.rules ?? []).filter((r) => r.status === 'active').length;

  return (
    <div className="flex flex-col h-full min-h-0 overflow-hidden bg-lab-bg text-lab-text">
      {/* Annex header */}
      <div className="lab-header flex items-center justify-between gap-2 shrink-0">
        <span>INSPECTOR · ANALYSIS ANNEX</span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          2D analysis — the 3D village is the live view
        </span>
      </div>

      {/* Run summary strip. While scrubbed every projected stat (TICK/DAY/
          AGENTS/RULES) reflects the SCRUB tick and takes the same acid accent
          as the REPLAY badge — one glance separates a replayed projection from
          the live edge. HISTORY stays live (it describes the event window). */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2 border-b border-lab-border bg-lab-surface shrink-0">
        <SummaryStat label="TICK" value={String(currentTick).padStart(4, '0')} accent={scrubbed} />
        <SummaryStat
          label="DAY"
          value={String(stripDay)}
          accent={scrubbed}
          title={scrubbed ? 'Sim day at the scrub tick (latest turn_start ≤ T).' : undefined}
        />
        <SummaryStat
          label="AGENTS"
          value={`${aliveAgents}/${totalAgents}`}
          accent={scrubbed}
          title={scrubbed ? 'Agents alive at the scrub tick.' : 'Agents alive now.'}
        />
        <SummaryStat
          label="RULES"
          value={String(stripRules)}
          accent={scrubbed}
          title={scrubbed ? 'Rules active at the scrub tick.' : 'Rules active now.'}
        />
        <SummaryStat label="HISTORY" value={`${history.length} events`} />
        {scrubbed && (
          <span className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-acid text-lab-acid bg-lab-acid/10">
            REPLAY @ {currentTick} / {maxTick}
          </span>
        )}
        {historyLoading && (
          <span className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-border-bright text-lab-muted">
            HISTORY LOADING…
          </span>
        )}
        {historyTruncated && (
          <span
            className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-warn text-lab-warn"
            title="Older events were dropped at the in-memory history cap; scrubbed ticks beyond the window load via /api/replay."
          >
            HISTORY TRUNCATED — OLDEST EVENTS VIA REPLAY
          </span>
        )}
        {replayFetching && (
          <span className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-acid text-lab-acid">
            FETCHING REPLAY…
          </span>
        )}
        {routingHealth?.degraded && routingHealth.model && (
          <span
            className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-warn text-lab-warn"
            title={`All ${routingHealth.profileCount} profiles are being served by ${routingHealth.model} — model-vs-model comparison is not valid for this run.`}
          >
            ⚠ ROUTING DEGRADED → {routingHealth.model}
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
        {/* Replay scrubber drives the shared currentTick (full-width). It reads
            the UNSCOPED merged pool: the marker rail spans the whole run, and
            replayStateAt folds snapshot + delta internally up to currentTick. */}
        <ReplayScrubber
          events={mergedEvents}
          agents={agents}
          profiles={profiles}
          places={places}
          buildings={scrubberBuildings}
          animals={animals}
          currentTick={currentTick}
          maxTick={maxTick}
          snapshots={replaySnapshots}
          onSeek={handleSeek}
        />

        {/* Data panels — each re-projects AT currentTick. The 6th panel (W8) is
            the Animal Chaos Feed: the magenta critter-mischief stream. */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 auto-rows-fr">
          <DecisionTrace {...panelProps} />
          <GovernanceHistory {...panelProps} />
          <SocialGraph {...panelProps} />
          <AWIDashboard {...panelProps} />
          <AnimalChaosFeed {...panelProps} />
        </div>

        <p className="font-mono text-[10px] text-lab-dim leading-relaxed">
          Panels compute from the backfilled event history (mock-safe; deep ticks
          load via /api/replay). Scrub above; every panel follows the shared tick.
        </p>
      </div>
    </div>
  );
}

function SummaryStat({
  label,
  value,
  accent = false,
  title,
}: {
  label: string;
  value: string;
  /** W10: acid-tinted while the stat reflects a scrubbed (REPLAY) projection. */
  accent?: boolean;
  title?: string;
}) {
  return (
    <div className="flex items-center gap-1.5" title={title}>
      <span className="font-mono text-[10px] text-lab-muted">{label}</span>
      <span
        className={`font-mono text-xs font-bold tabular-nums ${accent ? 'text-lab-acid' : 'text-lab-text'}`}
      >
        {value}
      </span>
    </div>
  );
}
