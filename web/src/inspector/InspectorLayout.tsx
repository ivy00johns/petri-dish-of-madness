/**
 * InspectorLayout — the 2D analysis annex (frontend-inspector.md §0/§4/§7,
 * v1.1.0 §1–4 / EM-069, v1.2.0 §8 / EM-086).
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
 * Archive mode (v1.2.0 §8 / EM-086, NORMATIVE):
 *   • `selectedRunId` (null = live, today's behavior byte-identical) is set by
 *     the RunBrowser. While a PAST run is selected, the WS/live rolling-history
 *     merge is DISABLED: every panel reads ONLY the selected run's data —
 *     events backfilled via /api/events?run_id= (useArchiveHistory, the same
 *     keyset pagination), the agent roster reconstructed from those events +
 *     the run's config_summary (archiveAgents), geometry/snapshots via
 *     /api/replay?run_id= (per EM-086 note 2, past-run places come from the
 *     run's snapshots, never the live places table).
 *   • A persistent "Viewing run #N (archived) — ⏎ back to live" banner sits at
 *     the top; the scrubber's bounds come from the selected run's max_tick.
 *   • Returning to live restores current behavior exactly: all archive state
 *     is keyed to `selectedRunId`, so clearing it drops every archived source
 *     synchronously (no stale archived data bleeding into the live view).
 *
 * The 3D cozy village remains the PRIMARY experience at "/"; this is the
 * analysis annex, not a demotion of it.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { WorldState, WorldEvent } from '../types';
import type { PanelProps } from './types';
import {
  maxTick as selectMaxTick,
  activeRuleCount,
  dayAt,
  archiveAgents,
} from './selectors';
import type { ReplaySnapshot } from './selectors';
import {
  createEconomyProjector,
  createReplayProjector,
  shouldEngageReplayMaterials,
} from './projections';
import type { EconomyProjector, ReplayProjector } from './projections';
import { ErrorBoundary } from './ErrorBoundary';
import { useReplayMaterials } from './useReplayMaterials';
import { useArchiveHistory } from './useArchiveHistory';
import type { RunRow } from './api';
import type { RoutingHealth } from '../hooks/useRoutingHealth';
import { ReplayScrubber, ReplayMapPanel } from './ReplayScrubber';
import DecisionTrace from './DecisionTrace';
import GovernanceHistory from './GovernanceHistory';
import SocialGraph from './SocialGraph';
import AWIDashboard from './AWIDashboard';
import AnimalChaosFeed, { isAnimalEvent } from './AnimalChaosFeed';
import RunBrowser from './RunBrowser';

interface InspectorLayoutProps {
  /** Live world projection (run summary strip + agents/profiles/places). */
  world: WorldState | null;
  /** Backfilled + rolling event history (newest-first) — primary data source. */
  history: WorldEvent[];
  /** True while the /api/events backfill is still paging in (EM-069). */
  historyLoading?: boolean;
  /** True when older events were dropped at the memory cap (EM-069). */
  historyTruncated?: boolean;
  /**
   * Wave F (EM-194): the run's TOTAL event count (GET /api/events/stats) —
   * drives the backfill progress label and the cap-honesty notice
   * ("showing the newest 50,000 of 99,140"). null/absent = unknown.
   */
  historyTotal?: number | null;
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
  historyTotal = null,
  mockMode,
  onSeekTick,
  routingHealth,
}: InspectorLayoutProps) {
  // Wave F (EM-194): incremental scrub projectors — persistent fold cursors
  // (created once per mount) so a scrub step folds only the events BETWEEN the
  // two ticks instead of re-running the full O(n) selectors. Results are equal
  // to the full folds by construction (they share the selector fold steps).
  const projectorsRef = useRef<{ economy: EconomyProjector; replay: ReplayProjector } | null>(null);
  if (projectorsRef.current === null) {
    projectorsRef.current = { economy: createEconomyProjector(), replay: createReplayProjector() };
  }
  const projectors = projectorsRef.current;
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

  // ── Archive mode (W11a EM-086, contract §8) ─────────────────────────────────
  // null = live (everything below behaves exactly as pre-W11a). Selecting a
  // past run swaps EVERY data source to run-scoped fetches; the live props
  // (history/world) are not read by any archived branch.
  const [archivedRun, setArchivedRun] = useState<RunRow | null>(null);
  const selectedRunId: number | null = archivedRun?.id ?? null;
  const archived = archivedRun !== null;

  // The selected run's full event log via /api/events?run_id= (keyset-paged).
  const archive = useArchiveHistory(selectedRunId);

  // Effective event source: the WS/live merge is DISABLED while archived.
  const effHistory = archived ? archive.events : history;

  // Effective agent roster: the live `world` describes the ACTIVE run, so an
  // archived view reconstructs its roster from the run's own events + the
  // RunRow config_summary (profiles stay live — model colors are stable config).
  const effAgents = useMemo(
    () =>
      archivedRun
        ? archiveAgents(archive.events, archivedRun.config_summary.agents ?? [], profiles)
        : agents,
    [archive.events, archivedRun, profiles, agents],
  );
  // Live buildings/animals/places belong to the active run; archived views get
  // them ONLY from the run's snapshots (folded below via replayStateAt).
  const effBuildings = useMemo(() => (archived ? [] : buildings), [archived, buildings]);
  const effAnimals = useMemo(() => (archived ? [] : animals), [archived, animals]);
  const effPlaces = useMemo(
    () => (archived ? [] : places),
    [archived, places],
  );

  // Scrubber bounds: live = history ∪ world tick; archived = the selected
  // run's max_tick (RunRow) ∪ its fetched events (contract §8c).
  const maxTick = useMemo(() => {
    if (archivedRun) return Math.max(archivedRun.max_tick, selectMaxTick(archive.events));
    return Math.max(selectMaxTick(history), world?.tick ?? 0);
  }, [archivedRun, archive.events, history, world]);

  // Shared scrub position. Default = maxTick = the latest tick; it follows the
  // live edge until the user scrubs back, then stays pinned where they left it.
  const [currentTick, setCurrentTick] = useState(maxTick);
  const pinnedRef = useRef(false);
  useEffect(() => {
    if (!pinnedRef.current) setCurrentTick(maxTick);
  }, [maxTick]);

  // Crossing the live ⇄ archive boundary unpins and snaps to the NEW mode's
  // latest tick, so a live scrub position never leaks into an archived view
  // (or vice versa) — part of §8's "returning to live restores behavior
  // exactly" requirement.
  const prevRunRef = useRef(selectedRunId);
  useEffect(() => {
    if (prevRunRef.current === selectedRunId) return;
    prevRunRef.current = selectedRunId;
    pinnedRef.current = false;
    setCurrentTick(maxTick);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId]);

  const handleSeek = (tick: number) => {
    const clamped = Math.max(0, Math.min(maxTick, tick));
    // If the user scrubs to the latest tick, resume following; otherwise pin.
    pinnedRef.current = clamped < maxTick;
    setCurrentTick(clamped);
    // Live engine seek is a LIVE-mode affordance; browsing an archive must
    // not pause/seek the running simulation.
    if (!archived) onSeekTick?.(clamped);
  };

  // Scrubbed = projecting the past (not pinned to the advancing live edge).
  const scrubbed = currentTick < maxTick;
  // Projecting = the panels re-project state from events instead of trusting
  // live world fields. Always true in archive mode (there IS no live edge for
  // a past run — even its final tick is an event-folded projection).
  const projecting = scrubbed || archived;

  // ── Deep replay (v1.1.0 §2): /api/replay when history can't project ────────
  // Live: only when the client history is unfaithful (loading / truncated —
  // wave F cap-honesty: a pre-cap scrub range must engage snapshot+delta,
  // never project from a hole). Archived: always — the run's snapshots are
  // the ONLY geometry source (EM-086 note 2: past-run places come from
  // snapshot state_json). Extracted pure (projections.ts) and unit-tested.
  const needsReplayMaterials = shouldEngageReplayMaterials({
    mockMode,
    archived,
    scrubbed,
    historyLoading,
    historyTruncated,
  });
  const { materials: replay, fetching: replayFetching } = useReplayMaterials(
    needsReplayMaterials,
    currentTick,
    selectedRunId,
  );

  const replaySnapshots = useMemo<ReplaySnapshot[]>(
    () => (replay?.snapshot ? [replay.snapshot] : []),
    [replay],
  );

  // Full event pool: history merged with the replay delta, deduped by seq.
  // Unscoped — the scrubber's marker rail spans the whole run.
  const mergedEvents = useMemo(() => {
    const delta = replay?.events ?? [];
    if (delta.length === 0) return effHistory;
    const seen = new Set(effHistory.map((e) => e.seq));
    const extra = delta.filter((e) => !seen.has(e.seq));
    return extra.length > 0 ? [...extra, ...effHistory] : effHistory;
  }, [effHistory, replay]);

  // C8: while projecting the panels get a SCOPED slice (tick <= currentTick),
  // so the advancing live edge never grows into a replayed projection.
  const panelEvents = useMemo(
    () => (projecting ? mergedEvents.filter((e) => e.tick <= currentTick) : mergedEvents),
    [mergedEvents, projecting, currentTick],
  );

  // W10 / audit C7: the time-projected replay frame at the scrub tick. The
  // scrubber's `buildings` prop was live-only (the C7 bug: a scrubbed map drew
  // TODAY's building status); while scrubbed it now receives the building
  // state folded from snapshot + construction events at tick T (replayStateAt
  // owns the fold; the live roster contributes display metadata only). In
  // archive mode the frame is ALWAYS computed (snapshot-sourced geometry).
  // Wave F: computed via the INCREMENTAL projector — a scrub step folds only
  // the events between the two ticks (equal to the full replayStateAt fold).
  const scrubFrame = useMemo(
    () =>
      projecting
        ? projectors.replay.at(
            mergedEvents,
            replaySnapshots,
            currentTick,
            effAgents,
            effPlaces,
            effBuildings,
            effAnimals,
          )
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projecting, mergedEvents, replaySnapshots, currentTick, effAgents, effPlaces, effBuildings, effAnimals],
  );
  const scrubberBuildings = scrubFrame ? scrubFrame.buildings : effBuildings;

  // W10 / EM-075: per-agent energy/credits re-projected at the scrub tick.
  // Approach (see agentEconomyAt): the latest `turn_start` ≤ T carries an
  // authoritative {energy, credits} sample for its agent (event-log.md §3);
  // later `action_resolved.state_deltas` by the same agent fold on top. That
  // is exact at turn granularity — engine-internal energy decay and
  // target-side economy transfers are not per-agent evented, so agents WITHOUT
  // a turn_start in the scoped window keep their live values and the panels
  // mark the economy figures approximate ("~", with an explanatory title).
  // Wave F: incremental projector — equal to agentEconomyAt(panelEvents)
  // (the scoped fold), but a scrub step folds only the tick delta.
  const economyAtTick = useMemo(
    () => (projecting ? projectors.economy.at(mergedEvents, currentTick) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projecting, mergedEvents, currentTick],
  );

  // Death ticks depend only on the merged pool — computed once per history
  // change, NOT per scrub step (wave F: keep the scrub hot path O(delta)).
  const deathTick = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of mergedEvents) {
      if (e.kind === 'agent_died' && e.actor_id) m.set(e.actor_id, e.tick);
    }
    return m;
  }, [mergedEvents]);

  // C8: agents re-projected at the scrub tick (alive recomputed from deaths,
  // energy/credits from turn samples) so live-edge state doesn't read back
  // into the past.
  const panelAgents = useMemo(() => {
    if (!projecting) return effAgents;
    return effAgents.map((a) => {
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
  }, [effAgents, deathTick, projecting, currentTick, economyAtTick]);

  // True when ≥1 agent's scrubbed energy/credits fell back to live values.
  const agentsApproximate =
    projecting && effAgents.some((a) => !(economyAtTick?.get(a.id)?.sampled ?? false));

  // While archived the live backfill flags don't apply — the archive fetch
  // carries its own loading state.
  const effHistoryLoading = archived ? archive.loading : historyLoading;

  const panelProps: PanelProps = {
    events: panelEvents,
    agents: panelAgents,
    profiles,
    currentTick,
    maxTick,
    historyLoading: effHistoryLoading,
    agentsApproximate,
  };

  // W10: the status strip follows the SCRUB tick while replaying (audit:
  // "strip mixes scrub tick with live agent count"). Agents alive at T come
  // from the re-projected panel agents; DAY from the latest turn_start ≤ T;
  // RULES = rules ACTIVE at T from the scoped governance lifecycle. HISTORY
  // stays live (it describes the in-memory window, not the projection).
  const aliveAgents = (projecting ? panelAgents : effAgents).filter((a) => a.alive).length;
  const totalAgents = effAgents.length;
  const stripDay = projecting ? dayAt(panelEvents, archived ? 0 : world?.day ?? 0) : world?.day ?? 0;
  const stripRules = projecting
    ? activeRuleCount(panelEvents)
    : (world?.rules ?? []).filter((r) => r.status === 'active').length;

  // §8: empty archived run / missing snapshots → labeled, never blank.
  const archiveEmpty = archived && !archive.loading && !archive.failed && archive.events.length === 0;
  const archiveNoSnapshots =
    archived && !replayFetching && !archive.loading && replaySnapshots.length === 0;

  // ── Wave G (EM-197): empty-panel collapse signals ──────────────────────────
  // A zero-data panel renders as a slim strip and its column siblings reclaim
  // the space. Computed from the SAME scoped pool the panels project from.
  const govEventCount = useMemo(
    () => panelEvents.filter((e) => GOV_KINDS.has(e.kind)).length,
    [panelEvents],
  );
  const chaosEventCount = useMemo(
    () => panelEvents.filter((e) => isAnimalEvent(e) && e.tick <= currentTick).length,
    [panelEvents, currentTick],
  );

  return (
    // EM-082 a11y: the annex is the route's main landmark (the live route's
    // <main> is the world view inside LiveLayout).
    //
    // Wave G (EM-197) layout law: the annex is VIEWPORT-FIT — h-dvh clamped by
    // the app frame (max-h-full), overflow-hidden so the PAGE never scrolls at
    // ≥1024px. Header / archive banner / status strip / scrub strip are fixed
    // chrome; the panel grid below absorbs the remaining viewport and every
    // panel scrolls internally.
    <main className="flex flex-col h-dvh max-h-full min-h-0 overflow-hidden bg-lab-bg text-lab-text">
      {/* Annex header */}
      <div className="lab-header flex items-center justify-between gap-2 shrink-0">
        <span>INSPECTOR · ANALYSIS ANNEX</span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          2D analysis — the 3D village is the live view
        </span>
      </div>

      {/* §8b: the persistent, obvious archive-mode affordance. Sits ABOVE the
          summary strip, outside the scroll body, so it can never scroll away. */}
      {archivedRun && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 border-b border-lab-acid bg-lab-acid/10 shrink-0">
          <span className="font-mono text-[11px] font-bold uppercase tracking-widest text-lab-acid">
            Viewing run #{archivedRun.id} (archived)
          </span>
          <span className="font-mono text-[10px] text-lab-muted">
            live feed disabled — panels show only this run
          </span>
          {archive.loading && (
            <span className="font-mono text-[10px] text-lab-acid">
              loading run history…
              {archive.total !== null &&
                ` ${archive.events.length.toLocaleString()} / ${archive.total.toLocaleString()} events`}
            </span>
          )}
          {archive.truncated && !archive.loading && archive.total !== null && (
            <span
              className="font-mono text-[10px] font-bold text-lab-warn"
              title="The run is larger than the in-memory page cap; the newest events are shown. Scrubbed ticks beyond the window load via /api/replay."
            >
              showing the newest {archive.events.length.toLocaleString()} of{' '}
              {archive.total.toLocaleString()} events
            </span>
          )}
          {archive.failed && (
            <span className="font-mono text-[10px] font-bold text-lab-warn">
              couldn't load run #{archivedRun.id} — backend unreachable or unknown run
            </span>
          )}
          {archiveEmpty && (
            <span className="font-mono text-[10px] text-lab-warn">
              this run recorded no events — panels show their empty states
            </span>
          )}
          {archiveNoSnapshots && (
            <span
              className="font-mono text-[10px] text-lab-muted"
              title="Past-run map geometry comes from the run's snapshots (the live places table belongs to the active run); without one, positions are approximate."
            >
              no snapshot at this tick — map geometry approximate
            </span>
          )}
          <button
            type="button"
            onClick={() => setArchivedRun(null)}
            className="ml-auto font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-acid text-lab-acid bg-lab-bg hover:bg-lab-acid/20 uppercase tracking-wider"
          >
            ⏎ back to live
          </button>
        </div>
      )}

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
          title={projecting ? 'Sim day at the scrub tick (latest turn_start ≤ T).' : undefined}
        />
        <SummaryStat
          label="AGENTS"
          value={`${aliveAgents}/${totalAgents}`}
          accent={scrubbed}
          title={projecting ? 'Agents alive at the scrub tick.' : 'Agents alive now.'}
        />
        <SummaryStat
          label="RULES"
          value={String(stripRules)}
          accent={scrubbed}
          title={projecting ? 'Rules active at the scrub tick.' : 'Rules active now.'}
        />
        <SummaryStat label="HISTORY" value={`${effHistory.length} events`} />
        {scrubbed && (
          <span className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-acid text-lab-acid bg-lab-acid/10">
            REPLAY @ {currentTick} / {maxTick}
          </span>
        )}
        {effHistoryLoading && (
          <span className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-border-bright text-lab-muted">
            {/* Wave F (EM-194): honest tail-first progress — newest events
                render first; the figure tracks the background backfill. */}
            {!archived && historyTotal !== null
              ? `BACKFILLING ${history.length.toLocaleString()} / ${historyTotal.toLocaleString()} EVENTS…`
              : 'HISTORY LOADING…'}
          </span>
        )}
        {!archived && historyTruncated && (
          <span
            className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-warn text-lab-warn"
            title="Older events were dropped at the in-memory history cap; scrubbed ticks beyond the window load via /api/replay."
          >
            {historyTotal !== null && historyTotal > history.length
              ? `SHOWING THE NEWEST ${history.length.toLocaleString()} OF ${historyTotal.toLocaleString()} — OLDER TICKS VIA REPLAY`
              : 'HISTORY TRUNCATED — OLDEST EVENTS VIA REPLAY'}
          </span>
        )}
        {replayFetching && (
          <span className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-acid text-lab-acid">
            FETCHING REPLAY…
          </span>
        )}
        {!archived && routingHealth?.degraded && routingHealth.model && (
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

      {/* Scrub strip — FIXED chrome (wave G): drives the shared currentTick.
          It reads the UNSCOPED merged pool so the marker rail spans the run. */}
      <ErrorBoundary name="Replay Scrubber">
        <ReplayScrubber
          events={mergedEvents}
          currentTick={currentTick}
          maxTick={maxTick}
          onSeek={handleSeek}
        />
      </ErrorBoundary>

      {/* ── The panel grid (wave G, EM-197) ──────────────────────────────────
          Sized to the REMAINING viewport. ≥1280px: three balanced columns —
          [map+social+runs | trace+chaos | governance+AWI]; 1024–1279px: two
          columns with the governance/AWI pair as a bottom band; <1024px:
          panels stack and ONLY here may the area scroll (the small-screen
          fallback — the app's MinWidthGate already gates this range).
          Every panel is a cell with INTERNAL overflow; each mounts inside its
          own ErrorBoundary (wave F, EM-151) so one crash never blanks the
          annex. Each column is a flex stack so a collapsed empty panel's
          space is reclaimed by its siblings. */}
      <div
        data-testid="inspector-grid"
        className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3
                   lg:grid-rows-[minmax(0,3fr)_minmax(0,2fr)] xl:grid-rows-[minmax(0,1fr)]
                   gap-2 p-2 overflow-y-auto lg:overflow-hidden"
      >
        {/* Column A — replay map + social graph + run browser. */}
        <div className="flex flex-col gap-2 min-h-0 min-w-0">
          <PanelCell weight="lg:flex-[3]">
            <ErrorBoundary name="Replay Map">
              <ReplayMapPanel
                events={mergedEvents}
                agents={effAgents}
                profiles={profiles}
                places={effPlaces}
                buildings={scrubberBuildings}
                animals={effAnimals}
                currentTick={currentTick}
                maxTick={maxTick}
                snapshots={replaySnapshots}
              />
            </ErrorBoundary>
          </PanelCell>
          <PanelCell weight="lg:flex-[4]">
            <ErrorBoundary name="Social Graph">
              <SocialGraph {...panelProps} />
            </ErrorBoundary>
          </PanelCell>
          <PanelCell weight="lg:flex-[3]">
            {/* W11a (EM-086): past runs, archive mode entry, cross-run AWI. */}
            <ErrorBoundary name="Run Browser">
              <RunBrowser
                mockMode={mockMode}
                selectedRunId={selectedRunId}
                onSelectRun={setArchivedRun}
              />
            </ErrorBoundary>
          </PanelCell>
        </div>

        {/* Column B — decision trace + the chaos feed. */}
        <div className="flex flex-col gap-2 min-h-0 min-w-0">
          <PanelCell weight="lg:flex-[3]">
            <ErrorBoundary name="Decision Trace">
              <DecisionTrace {...panelProps} />
            </ErrorBoundary>
          </PanelCell>
          <CollapsibleCell
            title="Animal Chaos Feed"
            count={chaosEventCount}
            empty={chaosEventCount === 0}
            zeroNote="no critter mischief yet — the cat & dog's antics stream here"
            weight="lg:flex-[2]"
          >
            <ErrorBoundary name="Animal Chaos Feed">
              <AnimalChaosFeed {...panelProps} />
            </ErrorBoundary>
          </CollapsibleCell>
        </div>

        {/* Column C — governance + AWI. At the 2-column breakpoint this column
            becomes the bottom band (spanning both columns); at ≥1280px it is
            the third column. Stacked in BOTH cases so a collapsed governance
            strip stays slim and AWI reclaims the full band. */}
        <div className="flex flex-col gap-2 min-h-0 min-w-0 lg:col-span-2 xl:col-span-1">
          <CollapsibleCell
            title="Governance · Laws"
            count={govEventCount}
            empty={govEventCount === 0}
            zeroNote="no laws yet — proposals from Town Hall appear here"
            weight="lg:flex-[2]"
          >
            <ErrorBoundary name="Governance History">
              <GovernanceHistory {...panelProps} />
            </ErrorBoundary>
          </CollapsibleCell>
          <PanelCell weight="lg:flex-[3]">
            <ErrorBoundary name="AWI Dashboard">
              <AWIDashboard {...panelProps} />
            </ErrorBoundary>
          </PanelCell>
        </div>
      </div>
    </main>
  );
}

// ── Wave G (EM-197) layout cells ─────────────────────────────────────────────

// Stacked-fallback sizing (<1024px, behind the MinWidthGate): cells take real
// heights and the grid area page-scrolls. At ≥1024px cells are pure flex
// shares of the viewport-bounded column (min-h-0 so internals scroll).
const CELL_BASE =
  'min-h-[16rem] max-h-[70vh] lg:min-h-0 lg:max-h-none min-w-0 flex flex-col';

/** A fixed grid/flex cell: the panel inside scrolls internally. */
function PanelCell({ weight, children }: { weight: string; children: ReactNode }) {
  return <div className={`${CELL_BASE} ${weight}`}>{children}</div>;
}

// Governance lifecycle kinds — drives the empty-collapse signal.
const GOV_KINDS = new Set<string>(['rule_proposed', 'rule_vote', 'rule_passed', 'rule_rejected']);

/**
 * A cell that COLLAPSES to a slim strip while its panel has zero data
 * (contract §G2.2): title + zero-state counts + what-would-fill-it text + an
 * expand affordance. Collapsed, it is `shrink-0`, so flex siblings in the
 * column reclaim its space. Data arriving auto-expands it.
 */
function CollapsibleCell({
  title,
  count,
  empty,
  zeroNote,
  weight,
  children,
}: {
  title: string;
  count: number;
  empty: boolean;
  zeroNote: string;
  weight: string;
  children: ReactNode;
}) {
  const [forcedOpen, setForcedOpen] = useState(false);
  const collapsed = empty && !forcedOpen;

  if (collapsed) {
    return (
      <div
        role="region"
        aria-label={`${title} (empty, collapsed)`}
        className="shrink-0 min-w-0 flex items-center gap-2 px-2 py-1 lab-panel"
      >
        <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-lab-muted whitespace-nowrap">
          {title}
        </span>
        <span className="font-mono text-[10px] text-lab-dim tabular-nums shrink-0">{count}</span>
        <span className="font-mono text-[10px] text-lab-dim truncate min-w-0" title={zeroNote}>
          {zeroNote}
        </span>
        <button
          type="button"
          onClick={() => setForcedOpen(true)}
          aria-expanded={false}
          aria-label={`Expand the empty ${title} panel`}
          className="ml-auto shrink-0 font-mono text-[9px] font-bold uppercase tracking-wider px-1.5 py-px border border-lab-border text-lab-muted hover:border-lab-acid hover:text-lab-acid transition-colors cursor-pointer"
        >
          ▸ expand
        </button>
      </div>
    );
  }

  return (
    <div className={`${CELL_BASE} ${weight}`}>
      {empty && forcedOpen && (
        <button
          type="button"
          onClick={() => setForcedOpen(false)}
          aria-expanded={true}
          aria-label={`Collapse the empty ${title} panel`}
          className="shrink-0 font-mono text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 border border-lab-border bg-lab-surface text-lab-muted hover:border-lab-acid hover:text-lab-acid transition-colors cursor-pointer text-left"
        >
          ▾ collapse empty panel — {title}
        </button>
      )}
      <div className="flex-1 min-h-0 min-w-0 flex flex-col">{children}</div>
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
