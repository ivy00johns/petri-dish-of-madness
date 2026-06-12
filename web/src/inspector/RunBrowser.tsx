/**
 * RunBrowser (W11a EM-086, frontend-inspector.md §8) — the persisted-run
 * browser panel.
 *
 * Lists every run from GET /api/runs, NEWEST FIRST: run id, humanized
 * started_at, status, max_tick, event_count, and the agent roster from
 * config_summary (name + profile chip). The ACTIVE chip comes from `is_active`
 * ONLY — the stored `status` column is documented-unreliable (crashes leave
 * dead runs "running" forever) and is rendered as secondary text, never as a
 * liveness signal.
 *
 * Selecting a past run puts the inspector into ARCHIVE MODE (the layout owns
 * `selectedRunId`); selecting the active run (or the viewed run again) returns
 * to live. A per-run "cmp" toggle picks TWO runs for the cross-run AWI
 * comparison (RunComparison, rendered inline above the list).
 *
 * W11b (EM-101): archived rows get FORK — an inline tick input (defaulting
 * to the run's max_tick) that POSTs /api/runs/fork; on 201 the list refreshes
 * (the new run lands on top, newest-first) and a notice names it. Any run
 * with `forked_from` wears a lineage chip "↩ #N @ tick T". Failures (404 /
 * 400 / unreachable) render inline, labeled — never thrown.
 *
 * §7 empty-state rules: loading, fetch-failure ("no backend — live session
 * only"), and zero-runs states are all labeled — never a blank or a crash.
 * Mock mode short-circuits the fetch entirely. Token-only styling.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { inspectorApi } from './api';
import type { RunRow, RunConfigAgent } from './api';
import RunComparison from './RunComparison';

export interface RunBrowserProps {
  /** Mock mode (no backend): render the labeled live-session-only state. */
  mockMode: boolean;
  /** The run the inspector is viewing (null = live). */
  selectedRunId: number | null;
  /** Select a past run (archive mode) or null to return to live. */
  onSelectRun: (run: RunRow | null) => void;
}

type RunsState =
  | { status: 'loading' }
  | { status: 'unreachable' } // fetch failed / endpoint absent → live only
  | { status: 'ready'; runs: RunRow[] };

export default function RunBrowser({ mockMode, selectedRunId, onSelectRun }: RunBrowserProps) {
  const [state, setState] = useState<RunsState>({ status: 'loading' });
  const [reloadKey, setReloadKey] = useState(0);
  /** Compare picks, oldest pick first; capped at two. */
  const [compareIds, setCompareIds] = useState<number[]>([]);
  /** EM-101: "forked run #A @ T → run #B" notice after a successful fork. */
  const [forkNotice, setForkNotice] = useState<string | null>(null);

  // A successful fork refreshes the list (the new run is MAX(id), so it
  // surfaces at the top, newest-first) and announces what was created.
  const handleForked = useCallback((sourceId: number, tick: number, newRunId: number | null) => {
    setForkNotice(
      newRunId !== null
        ? `forked run #${sourceId} @ tick ${tick} → run #${newRunId} created (paused — press play to run it)`
        : `forked run #${sourceId} @ tick ${tick} — new run created (paused); it tops the refreshed list`,
    );
    setReloadKey((k) => k + 1);
  }, []);

  useEffect(() => {
    if (mockMode) return; // labeled no-backend state below; nothing to fetch
    let alive = true;
    setState({ status: 'loading' });
    void inspectorApi.runs().then((runs) => {
      if (!alive) return;
      setState(runs === null ? { status: 'unreachable' } : { status: 'ready', runs });
    });
    return () => {
      alive = false;
    };
  }, [mockMode, reloadKey]);

  const toggleCompare = useCallback((id: number) => {
    setCompareIds((cur) => {
      if (cur.includes(id)) return cur.filter((x) => x !== id);
      // Third pick replaces the oldest, keeping exactly-two reachable fast.
      return cur.length >= 2 ? [cur[1], id] : [...cur, id];
    });
  }, []);

  const runs = state.status === 'ready' ? state.runs : [];
  const compareRuns = useMemo(
    () =>
      compareIds.length === 2
        ? (compareIds
            .map((id) => runs.find((r) => r.id === id))
            .filter((r): r is RunRow => r !== undefined) as RunRow[])
        : [],
    [compareIds, runs],
  );

  return (
    <section className="lab-panel flex flex-col h-full min-h-0 overflow-hidden" aria-label="Run browser (EM-086)">
      <div className="lab-header flex items-center justify-between gap-2 !py-1 shrink-0">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">Run Browser</h2>
        <span className="flex items-center gap-2 font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          <span>EM-086 · archive &amp; compare</span>
          {!mockMode && (
            <button
              type="button"
              onClick={() => setReloadKey((k) => k + 1)}
              className="px-1.5 border border-lab-border text-lab-muted hover:text-lab-text hover:border-lab-border-bright"
              title="Re-fetch the run list"
            >
              refresh
            </button>
          )}
        </span>
      </div>

      {/* EM-101: post-fork notice (dismissible). */}
      {forkNotice && (
        <div
          role="status"
          className="flex items-center gap-2 px-3 py-1.5 border-b border-lab-acid bg-lab-acid/10"
        >
          <span className="font-mono text-[10px] text-lab-acid" aria-hidden="true">⑂</span>
          <span className="flex-1 min-w-0 font-mono text-[10px] text-lab-acid leading-snug">
            {forkNotice}
          </span>
          <button
            type="button"
            onClick={() => setForkNotice(null)}
            aria-label="Dismiss the fork notice"
            className="shrink-0 font-mono text-[9px] px-1.5 border border-lab-acid text-lab-acid hover:bg-lab-acid/20"
          >
            ✕
          </button>
        </div>
      )}

      {/* Cross-run AWI comparison, once two runs are picked. */}
      {compareRuns.length === 2 && (
        <div className="p-3 border-b border-lab-border">
          <RunComparison
            runA={compareRuns[0]}
            runB={compareRuns[1]}
            onClose={() => setCompareIds([])}
          />
        </div>
      )}

      {mockMode ? (
        <BrowserNotice
          headline="no backend — live session only"
          body="Mock mode has no persisted runs: the run browser, archive mode and cross-run comparison need the backend's event log. The live panels above keep working from the in-memory mock feed."
        />
      ) : state.status === 'loading' ? (
        <BrowserNotice headline="loading runs…" body="Fetching the persisted run list from /api/runs." />
      ) : state.status === 'unreachable' ? (
        <BrowserNotice
          headline="no backend — live session only"
          body="Couldn't reach /api/runs (backend down, or pre-W11a without the runs endpoint). Live panels keep working; hit refresh once the backend is up."
        />
      ) : runs.length === 0 ? (
        <BrowserNotice
          headline="no persisted runs yet"
          body="Runs appear here as the backend persists them — start the loop and this list fills in, newest first."
        />
      ) : (
        // Wave G: the list scrolls INTERNALLY inside the panel's grid cell
        // (the old free-height max-h-[24rem] block could push the page).
        <ul className="flex flex-col divide-y divide-lab-border overflow-y-auto flex-1 min-h-0 max-h-[24rem]">
          {runs.map((run) => (
            <RunListRow
              key={run.id}
              run={run}
              viewing={selectedRunId === run.id}
              comparing={compareIds.includes(run.id)}
              onView={() => {
                // The active run IS the live session; viewing the already-
                // viewed run again also returns to live (toggle semantics).
                if (run.is_active || selectedRunId === run.id) onSelectRun(null);
                else onSelectRun(run);
              }}
              onToggleCompare={() => toggleCompare(run.id)}
              onForked={handleForked}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

// ── one run row ───────────────────────────────────────────────────────────────

function RunListRow({
  run,
  viewing,
  comparing,
  onView,
  onToggleCompare,
  onForked,
}: {
  run: RunRow;
  viewing: boolean;
  comparing: boolean;
  onView: () => void;
  onToggleCompare: () => void;
  /** EM-101: a fork of this run succeeded (newRunId null = unparsable 201). */
  onForked: (sourceId: number, tick: number, newRunId: number | null) => void;
}) {
  const roster: RunConfigAgent[] = Array.isArray(run.config_summary.agents)
    ? run.config_summary.agents
    : [];

  // ── EM-101 fork affordance (archived rows): inline tick input → POST ──────
  const [forkOpen, setForkOpen] = useState(false);
  const [forkTick, setForkTick] = useState(String(run.max_tick));
  const [forking, setForking] = useState(false);
  const [forkError, setForkError] = useState<string | null>(null);

  const submitFork = async () => {
    const tick = Number(forkTick);
    if (!Number.isInteger(tick) || tick < 0 || tick > run.max_tick) {
      setForkError(`tick must be an integer in 0–${run.max_tick}`);
      return;
    }
    setForking(true);
    setForkError(null);
    const result = await inspectorApi.forkRun(run.id, tick);
    setForking(false);
    if (result.ok) {
      setForkOpen(false);
      onForked(run.id, tick, result.runId);
    } else {
      setForkError(result.message);
    }
  };

  return (
    <li className={`px-3 py-2 flex flex-col gap-1.5 ${viewing ? 'bg-lab-chrome' : ''}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-mono text-xs font-bold text-lab-text tabular-nums">#{run.id}</span>

        {/* ACTIVE = is_active ONLY (the contract's liveness rule). */}
        {run.is_active ? (
          <span
            className="font-mono text-[9px] font-bold px-1.5 py-0.5 border border-lab-acid text-lab-acid bg-lab-acid/10 uppercase tracking-wider"
            title="The loop holds this run (is_active) — this is the live session."
          >
            active
          </span>
        ) : (
          <span className="font-mono text-[9px] px-1.5 py-0.5 border border-lab-border text-lab-muted uppercase tracking-wider">
            archived
          </span>
        )}

        {/* EM-101: lineage chip — this run was forked from another. */}
        {typeof run.forked_from === 'number' && (
          <span
            className="font-mono text-[9px] px-1.5 py-0.5 border border-lab-border-bright text-lab-text uppercase tracking-wider"
            title={`Forked from run #${run.forked_from}${run.forked_at_tick != null ? ` at tick ${run.forked_at_tick}` : ''} — its tick-0 state is the parent's replayed state.`}
          >
            ↩ #{run.forked_from}
            {run.forked_at_tick != null && <span className="text-lab-muted normal-case"> @ tick {run.forked_at_tick}</span>}
          </span>
        )}

        <span className="font-mono text-[10px] text-lab-muted" title={run.started_at}>
          {humanizeTimestamp(run.started_at)}
        </span>

        {/* Stored status — secondary text at most; NEVER a liveness signal. */}
        {run.status && (
          <span
            className="font-mono text-[9px] text-lab-dim"
            title="Stored status column — unreliable for liveness (crashes leave dead runs 'running'); ACTIVE above comes from is_active."
          >
            status:{run.status}
          </span>
        )}

        <span className="font-mono text-[10px] text-lab-muted tabular-nums ml-auto">
          tick <span className="text-lab-text">{run.max_tick}</span> ·{' '}
          <span className="text-lab-text">{run.event_count}</span> events
        </span>

        <button
          type="button"
          onClick={onToggleCompare}
          className={`font-mono text-[9px] px-1.5 py-0.5 border uppercase tracking-wider ${
            comparing
              ? 'border-lab-acid text-lab-acid bg-lab-acid/10'
              : 'border-lab-border text-lab-muted hover:text-lab-text hover:border-lab-border-bright'
          }`}
          title="Pick two runs to compare their AWI summaries side by side."
        >
          cmp
        </button>

        {/* EM-101: FORK — archived runs only (the live run is still writing). */}
        {!run.is_active && (
          <button
            type="button"
            onClick={() => {
              setForkOpen((v) => !v);
              setForkTick(String(run.max_tick));
              setForkError(null);
            }}
            aria-expanded={forkOpen}
            className={`font-mono text-[9px] px-1.5 py-0.5 border uppercase tracking-wider ${
              forkOpen
                ? 'border-lab-acid text-lab-acid bg-lab-acid/10'
                : 'border-lab-border text-lab-muted hover:text-lab-text hover:border-lab-border-bright'
            }`}
            title="Fork this run at a tick into a NEW paused run (POST /api/runs/fork)."
          >
            ⑂ fork
          </button>
        )}

        <button
          type="button"
          onClick={onView}
          className={`font-mono text-[9px] px-1.5 py-0.5 border uppercase tracking-wider ${
            viewing
              ? 'border-lab-acid text-lab-acid bg-lab-acid/10'
              : 'border-lab-border-bright text-lab-text hover:border-lab-acid hover:text-lab-acid'
          }`}
          title={
            run.is_active
              ? 'This is the live session — view it live.'
              : viewing
                ? 'Currently viewing this archived run — click to return to live.'
                : 'Open this run in archive mode (panels show only this run).'
          }
        >
          {run.is_active ? 'live' : viewing ? 'viewing ⏎' : 'view'}
        </button>
      </div>

      {/* EM-101: the inline fork form — tick defaults to max_tick. */}
      {forkOpen && (
        <div className="flex flex-wrap items-center gap-2 border border-lab-border rounded-sm px-2 py-1.5 bg-lab-bg">
          <label
            htmlFor={`fork-tick-${run.id}`}
            className="font-mono text-[9px] uppercase tracking-wider text-lab-muted"
          >
            fork at tick
          </label>
          <input
            id={`fork-tick-${run.id}`}
            type="number"
            min={0}
            max={run.max_tick}
            value={forkTick}
            onChange={(e) => setForkTick(e.target.value)}
            disabled={forking}
            className="lab-input w-20 text-[10px] py-0.5 tabular-nums"
          />
          <span className="font-mono text-[9px] text-lab-dim tabular-nums">/ {run.max_tick}</span>
          <button
            type="button"
            onClick={() => void submitFork()}
            disabled={forking}
            className="font-mono text-[9px] font-bold px-2 py-0.5 border border-lab-acid text-lab-acid bg-lab-acid/10 hover:bg-lab-acid/20 uppercase tracking-wider disabled:opacity-40"
            aria-label={`Fork run ${run.id} at the chosen tick`}
          >
            {forking ? 'forking…' : '⑂ fork run'}
          </button>
          <button
            type="button"
            onClick={() => setForkOpen(false)}
            disabled={forking}
            aria-label="Cancel the fork"
            className="font-mono text-[9px] px-1.5 py-0.5 border border-lab-border text-lab-muted hover:text-lab-text"
          >
            ✕
          </button>
          {forkError && (
            <span role="alert" className="basis-full font-mono text-[9px] text-lab-warn leading-snug">
              ⚠ {forkError}
            </span>
          )}
        </div>
      )}

      {/* Agent roster from config_summary: name + profile chip. */}
      {roster.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {roster.map((a, i) => (
            <span
              key={`${a.name}-${i}`}
              className="font-mono text-[9px] px-1.5 py-0.5 border border-lab-border text-lab-muted"
            >
              {a.name}
              {a.profile && <span className="text-lab-dim"> · {a.profile}</span>}
            </span>
          ))}
        </div>
      ) : (
        <span className="font-mono text-[9px] text-lab-dim">no agent roster in config summary</span>
      )}
    </li>
  );
}

// ── labeled notice (the §7 empty-state idiom) ────────────────────────────────

function BrowserNotice({ headline, body }: { headline: string; body: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-6 text-center">
      <span className="font-mono text-[11px] uppercase tracking-widest text-lab-muted border border-lab-border px-2 py-0.5">
        {headline}
      </span>
      <p className="font-mono text-[10px] text-lab-muted leading-relaxed max-w-prose">{body}</p>
    </div>
  );
}

// ── started_at humanizer ──────────────────────────────────────────────────────

/** "2026-06-09 14:32 · 3h ago" — falls back to the raw string when unparsable. */
export function humanizeTimestamp(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso || '—';
  const pad = (n: number) => String(n).padStart(2, '0');
  const abs = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const deltaS = Math.max(0, Math.floor((now.getTime() - d.getTime()) / 1000));
  let rel: string;
  if (deltaS < 60) rel = 'just now';
  else if (deltaS < 3600) rel = `${Math.floor(deltaS / 60)}m ago`;
  else if (deltaS < 86400) rel = `${Math.floor(deltaS / 3600)}h ago`;
  else rel = `${Math.floor(deltaS / 86400)}d ago`;
  return `${abs} · ${rel}`;
}
