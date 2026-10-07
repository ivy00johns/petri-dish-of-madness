/**
 * ArenaPanel (EM-112 + EM-119 + EM-343) — the Model-Family Arena on the Runs tab.
 *
 * Two halves, one panel (plus the EM-343 failure taxonomy on every run card):
 *  • STANDINGS (EM-119): every run stamped with `runs.model_family` grouped
 *    by family — civilization-outcome cards (population / laws passed /
 *    buildings completed / crimes / credits) + population sparklines, with
 *    family-level per-run means. Zero-LLM; compared after the fact.
 *  • TOURNAMENT (EM-112): launch + spectate the SEQUENTIAL parallel-worlds
 *    bake-off — cast every agent from one family, run that world for a tick
 *    budget, reset into the next family; never concurrent (free-tier
 *    key-pool protection). Progress polls GET /api/arena/tournament while
 *    running; abort is a labeled action, never a throw.
 *  • FAILURE TAXONOMY (EM-343): every run card also shows its TRUE
 *    action_rejected / provider_error / parse_failure counts + shares and its
 *    failures-per-turn rate, read off the event log server-side (pre-EM-340
 *    runs have their overloaded rows re-derived from the payload) — where run
 *    23/26's single "parse failure" number finally reads as three.
 *  • FAILURE CURVE (EM-345): each run card also draws those failures OVER
 *    TICKS as ≤48 even-width bucket sums stacked by kind, so a provider outage
 *    reads as a SPIKE (a bucketed sum survives the downsample; a sampled point
 *    would drop a one-tick outage).
 *  • PER-AGENT CUT (EM-346): each run card can expand "by agent" to the same
 *    taxonomy keyed by actor — a per-agent rate that is NOT uniform means ONE
 *    route/model is broken (run 23: ada 30% vs vesper 5.7%), while a flat
 *    spread means the provider (or the world) failed everyone equally (run 26:
 *    ~16-18% each). This is WHY the taxonomy is exposed per agent: the run
 *    total alone can't tell those two failures apart.
 *  • FAMILY ROLLUP (EM-347): each family block also shows its
 *    failures POOLED across its runs, so the panel answers "which family fails
 *    differently" (shares + failures-per-turn, comparable across families).
 *
 * In MOCK MODE the backend calls fail (no backend) and the panel renders its
 * labeled zero states — the arena data is inherently cross-run/persisted, so
 * there is no mock-only rolling-history projection (unlike feed panels).
 * Off the replay surface entirely: not synced to currentTick.
 *
 * Styling is token-based lab-* classes (LaneHealthPanel idiom): dark panels,
 * mono chips, acid-green accents — no hardcoded hex outside the token map (the
 * failure-curve segments use the declared CSS custom-property tokens).
 */

import { useCallback, useEffect, useState } from 'react';
import {
  inspectorApi,
  type ArenaRun,
  type ArenaSummary,
  type FailureCurvePoint,
  type FailureTaxonomy,
  type FailureTaxonomyCore,
  type TournamentStatus,
} from './api';

type OutcomeKey = keyof ArenaRun['outcomes'];

const OUTCOME_LABELS: Record<OutcomeKey, string> = {
  population: 'pop',
  laws_passed: 'laws',
  buildings: 'bldgs',
  crimes: 'crimes',
  credits: 'credits',
};

function compact(n: number): string {
  if (!Number.isFinite(n)) return '0';
  if (Math.abs(n) >= 10000) return `${(n / 1000).toFixed(1)}k`;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

/** Torn-down {tick, alive} points → a tiny inline SVG polyline. */
function Sparkline({ points }: { points: Array<{ tick: number; alive: number }> }) {
  if (points.length < 2) return <span className="text-[10px] opacity-50">no series</span>;
  const maxTick = points[points.length - 1].tick || 1;
  const maxAlive = Math.max(...points.map((p) => p.alive), 1);
  const W = 100;
  const H = 24;
  const d = points
    .map(
      (p, i) =>
        `${i === 0 ? 'M' : 'L'}${((p.tick / maxTick) * W).toFixed(1)},${(
          H - (p.alive / maxAlive) * (H - 2) - 1
        ).toFixed(1)}`,
    )
    .join('');
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-6"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <path d={d} fill="none" stroke="currentColor" strokeWidth="1.5" className="opacity-80" />
    </svg>
  );
}

const OUTCOME_KEYS = Object.keys(OUTCOME_LABELS) as OutcomeKey[];

const FAILURE_LABELS: Array<[keyof FailureTaxonomy['counts'], string]> = [
  ['action_rejected', 'rej'],
  ['provider_error', 'prov'],
  ['parse_failure', 'parse'],
];

function pct(share: number): string {
  return `${Math.round(share * 100)}%`;
}

/**
 * EM-343 — the per-run (or per-agent / per-family) failure taxonomy line: the
 * TRUE shares, not the raw kind tally (a pre-EM-340 run's overloaded rows are
 * re-derived server-side). Shows the per-kind count + share of the failure
 * total and the failures-per-turn rate; the tooltip carries the denominators
 * and how much came from history. `prefix` labels a per-agent line with its
 * actor id.
 */
function FailureTaxonomyLine({ f, testid, prefix }: {
  f: FailureTaxonomyCore;
  testid: string;
  prefix?: string;
}) {
  const lead = prefix ? `${prefix} ` : '';
  if (f.total === 0) {
    return (
      <div className="font-mono text-[10px] opacity-50 truncate" data-testid={testid}>
        {lead}fails {f.turns > 0 ? `0/${f.turns} turns` : 'none'}
      </div>
    );
  }
  const title =
    `${prefix ? `${prefix} — ` : ''}true failure taxonomy off the event log — ` +
    `${f.total} of ${f.turns} llm calls ` +
    `(${(f.failure_rate * 100).toFixed(1)}%/turn): ` +
    FAILURE_LABELS.map(([k]) => `${k} ${f.counts[k]} (${pct(f.shares[k])})`).join(', ') +
    (f.legacy_rows_reclassified > 0
      ? `; ${f.legacy_rows_reclassified} pre-EM-340 row(s) re-derived from payload`
      : '');
  return (
    <div
      className="font-mono text-[10px] opacity-70 truncate"
      data-testid={testid}
      title={title}
    >
      {lead}fails{' '}
      {FAILURE_LABELS.map(([k, l]) => `${l} ${f.counts[k]} (${pct(f.shares[k])})`).join(' · ')}
      {' · '}
      {(f.failure_rate * 100).toFixed(1)}%/turn
    </div>
  );
}

/** EM-345 — the stacked per-kind curve segments, bottom-up, in token colors. */
const FAILURE_SEGMENTS: Array<[keyof FailureCurvePoint, string]> = [
  ['provider_error', 'var(--lab-danger)'],
  ['action_rejected', 'var(--lab-warn)'],
  ['parse_failure', 'var(--lab-text)'],
];

/** Sum of one curve bucket across the three kinds. */
function curveTotal(p: FailureCurvePoint): number {
  return p.action_rejected + p.provider_error + p.parse_failure;
}

/**
 * EM-345 — the per-turn failure curve: the run's failures over ticks as ≤48
 * even-width bucket SUMS, stacked by kind, so a provider outage reads as a
 * SPIKE (the bucket that swallowed the outage stands tall and red) rather than
 * the run's single "parse failure" number. Bucket SUMS — not sampled points —
 * are why a one-tick spike survives the downsample.
 */
function FailureCurve({ points, testid }: { points: FailureCurvePoint[]; testid: string }) {
  if (points.length < 2) {
    return <div className="font-mono text-[10px] opacity-50" data-testid={testid}>no failure curve</div>;
  }
  const peak = Math.max(...points.map(curveTotal));
  if (peak === 0) {
    return (
      <div className="font-mono text-[10px] opacity-50" data-testid={testid}>
        flat — no failures over the run
      </div>
    );
  }
  const W = 100;
  const H = 24;
  const bw = W / points.length;
  const tallest = points.reduce((a, b) => (curveTotal(a) >= curveTotal(b) ? a : b));
  const title =
    `failures per tick bucket — ${points.length} bucket(s) over the run; ` +
    `peak t${tallest.tick}: prov ${tallest.provider_error}, ` +
    `rej ${tallest.action_rejected}, parse ${tallest.parse_failure}`;
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-6"
      preserveAspectRatio="none"
      role="img"
      aria-label={title}
      data-testid={testid}
    >
      <title>{title}</title>
      {points.map((p, i) => {
        let y = H;
        const rects = [];
        for (const [kind, color] of FAILURE_SEGMENTS) {
          const h = (p[kind] / peak) * H;
          if (h > 0) {
            rects.push(
              <rect key={kind} x={i * bw} y={y - h} width={bw} height={h} fill={color} />,
            );
          }
          y -= h;
        }
        return rects;
      })}
    </svg>
  );
}

/**
 * EM-346 — the per-agent failure cut, collapsed by default. Answers "which
 * agent fails differently": a per-agent rate that is NOT uniform means ONE
 * route/model is broken; a flat spread across the cast means the provider (or
 * the world) failed everyone equally. Clean agents (total 0) stay listed so
 * the spread is readable rather than only the failing tail.
 */
function FailureByAgent({ f, testidPrefix }: { f: FailureTaxonomy; testidPrefix: string }) {
  const actors = Object.keys(f.by_agent).sort(
    (a, b) =>
      f.by_agent[b].failure_rate - f.by_agent[a].failure_rate || a.localeCompare(b),
  );
  if (actors.length === 0) return null;
  return (
    <details className="mt-0.5">
      <summary className="font-mono text-[10px] opacity-60 cursor-pointer">
        by agent ({actors.length})
      </summary>
      <div className="flex flex-col gap-0.5 mt-0.5">
        {actors.map((a) => (
          <FailureTaxonomyLine
            key={a}
            f={f.by_agent[a]}
            testid={`${testidPrefix}-${a}`}
            prefix={a}
          />
        ))}
      </div>
    </details>
  );
}
export default function ArenaPanel() {
  const [arena, setArena] = useState<ArenaSummary | null>(null);
  const [arenaLoaded, setArenaLoaded] = useState(false);
  const [tStatus, setTStatus] = useState<TournamentStatus | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [ticksPerFamily, setTicksPerFamily] = useState(40);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const loadArena = useCallback(async () => {
    const data = await inspectorApi.arena();
    setArena(data);
    setArenaLoaded(true);
  }, []);

  const loadStatus = useCallback(async () => {
    setTStatus(await inspectorApi.tournamentStatus());
  }, []);

  useEffect(() => {
    void loadArena();
    void loadStatus();
  }, [loadArena, loadStatus]);

  // Poll tournament progress while running (and refresh the standings when it
  // settles — the sweep just stamped whole new runs). Polling stops when idle.
  useEffect(() => {
    if (tStatus?.status !== 'running') return;
    const iv = setInterval(() => {
      void (async () => {
        const next = await inspectorApi.tournamentStatus();
        setTStatus(next);
        if (next.status !== 'running') void loadArena();
      })();
    }, 2000);
    return () => clearInterval(iv);
  }, [tStatus?.status, loadArena]);

  const toggleFamily = (fam: string) => {
    setSelected((cur) => (cur.includes(fam) ? cur.filter((f) => f !== fam) : [...cur, fam]));
  };

  const start = async () => {
    setStarting(true);
    setActionMsg(null);
    const res = await inspectorApi.startTournament(selected, ticksPerFamily);
    setStarting(false);
    if (res.ok) {
      setSelected([]);
      await loadStatus();
    } else {
      setActionMsg(res.message);
    }
  };

  const abort = async () => {
    setActionMsg(null);
    const res = await inspectorApi.abortTournament();
    if (!res.ok) setActionMsg(res.message);
  };

  const running = tStatus?.status === 'running';
  const families = arena?.families ?? [];
  const contactRuns = arena?.contact_runs ?? [];

  return (
    <section
      aria-label="Model-Family Arena (EM-119)"
      data-testid="arena-panel"
      className="min-w-0"
    >
      <header className="flex items-baseline justify-between gap-2 mb-1">
        <h3 className="text-xs font-semibold uppercase tracking-wide">Model-Family Arena</h3>
        <div className="flex items-baseline gap-2">
          {tStatus && tStatus.status === 'running' && (
            <span
              className="font-mono text-[10px] px-1 rounded"
              data-testid="arena-progress"
            >
              {tStatus.current_family ?? '…'} · {tStatus.ticks_done_in_current}/
              {tStatus.ticks_per_family}
            </span>
          )}
          {tStatus?.status === 'error' && (
            <span className="font-mono text-[10px] text-red-400">
              tournament error
            </span>
          )}
          <button
            type="button"
            className="text-[10px] px-1 rounded hover:opacity-80"
            onClick={() => void loadArena()}
          >
            ↻ refresh
          </button>
        </div>
      </header>

      {/* ── Tournament controls (EM-112) ─────────────────────────────── */}
      <div className="mb-2 p-2 rounded border border-current/10">
        <div className="flex flex-wrap items-center gap-1 mb-1">
          {families.length === 0 && arenaLoaded && (
            <span className="text-[10px] opacity-60">
              no castable families yet — run a stamped tournament (below) or check
              /api/arena
            </span>
          )}
          {families.map((f) => (
            <button
              key={f.family}
              type="button"
              data-testid={`arena-family-chip-${f.family}`}
              aria-pressed={selected.includes(f.family)}
              onClick={() => toggleFamily(f.family)}
              disabled={running}
              className={`font-mono text-[10px] px-1.5 py-0.5 rounded border ${
                selected.includes(f.family) ? 'border-current' : 'border-current/25 opacity-70'
              } ${running ? 'cursor-not-allowed' : ''}`}
            >
              {f.family} ({f.runs.length})
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1 text-[10px]">
            ticks/family
            <input
              type="number"
              min={1}
              max={500}
              value={ticksPerFamily}
              disabled={running}
              onChange={(e) => {
                const v = Number(e.target.value);
                setTicksPerFamily(Number.isFinite(v) ? v : 40);
              }}
              className="w-16 font-mono text-[10px] px-1 rounded border border-current/25 bg-transparent"
              aria-label="Ticks per family"
            />
          </label>
          {running ? (
            <button
              type="button"
              className="text-[10px] font-mono px-2 py-0.5 rounded border border-red-400/50 hover:opacity-80"
              onClick={() => void abort()}
            >
              abort
            </button>
          ) : (
            <button
              type="button"
              data-testid="arena-start"
              className="text-[10px] font-mono px-2 py-0.5 rounded border border-current/40 hover:opacity-80 disabled:opacity-40"
              disabled={selected.length === 0 || ticksPerFamily < 1 || ticksPerFamily > 500 || starting}
              onClick={() => void start()}
            >
              run tournament ({selected.length})
            </button>
          )}
        </div>
        {tStatus?.status !== 'running' && tStatus && tStatus.status !== 'idle' && (
          <div className="mt-1 text-[10px] opacity-70" data-testid="arena-tournament-summary">
            last sweep: {tStatus.status} —{' '}
            {tStatus.results
              .map((r) => `${r.family} ${r.status} (${r.ticks_run}t)`)
              .join('; ') || 'no families ran'}
            {tStatus.error ? ` — ${tStatus.error}` : ''}
          </div>
        )}
        {actionMsg && (
          <div className="mt-1 text-[10px] text-red-400" role="alert">
            {actionMsg}
          </div>
        )}
      </div>

      {/* ── Standings (EM-119) ───────────────────────────────────────── */}
      {families.length === 0 ? (
        <div className="text-[10px] opacity-60 p-2">
          {arenaLoaded
            ? 'no family-stamped runs yet — start a tournament to seed the stage'
            : 'no backend — the arena reads persisted runs'}
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-2 min-w-0">
          {families.map((fam) => (
            <div
              key={fam.family}
              data-testid={`arena-family-${fam.family}`}
              className="min-w-0 rounded border border-current/10 p-2"
            >
              <div className="flex items-baseline justify-between mb-1">
                <span className="font-mono text-xs font-semibold">{fam.family}</span>
                <span className="text-[10px] opacity-60">
                  {fam.runs.length} run{fam.runs.length === 1 ? '' : 's'}
                </span>
              </div>
              {/* family means row */}
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 mb-1">
                {OUTCOME_KEYS.map((k) => (
                  <span key={k} className="text-[10px]" title={`avg per run — ${OUTCOME_LABELS[k]}`}>
                    {OUTCOME_LABELS[k]}{' '}
                    <span className="font-mono">
                      {compact(fam.avg_per_run[k] ?? 0)}
                    </span>
                  </span>
                ))}
              </div>
              {/* EM-347 — the family's failures pooled across its runs (shares +
                  per-turn rate), the "which family fails differently" read-off */}
              <FailureTaxonomyLine
                f={fam.failures}
                testid={`arena-family-failures-${fam.family}`}
                prefix="family"
              />
              <div className="flex flex-col gap-1">
                {fam.runs.map((r) => (
                  <div
                    key={r.run_id}
                    className="rounded border border-current/10 px-1.5 py-1 min-w-0"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-[10px] opacity-80">
                        run #{r.run_id} · tick {r.max_tick}
                      </span>
                      <span className="font-mono text-[10px] opacity-60">
                        {OUTCOME_KEYS.map(
                          (k) => `${OUTCOME_LABELS[k]} ${compact(r.outcomes[k] ?? 0)}`,
                        ).join('  ')}
                      </span>
                    </div>
                    <Sparkline points={r.population_sparkline} />
                    <FailureCurve points={r.failures.curve} testid={`arena-run-curve-${r.run_id}`} />
                    <FailureTaxonomyLine f={r.failures} testid={`arena-run-failures-${r.run_id}`} />
                    <FailureByAgent f={r.failures} testidPrefix={`arena-agent-failures-${r.run_id}`} />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── Contact runs (EM-334) — the First Contact comparison ────── */}
      {contactRuns.length > 0 && (
        <div className="mt-2" data-testid="arena-contact-runs">
          <div className="text-[10px] uppercase tracking-wide opacity-70 mb-1">
            First Contact runs
          </div>
          <div className="flex flex-col gap-1">
            {contactRuns.map((c) => (
              <div
                key={c.run_id}
                data-testid={`arena-contact-run-${c.run_id}`}
                className="rounded border border-current/10 px-1.5 py-1 min-w-0"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[10px] opacity-80">
                    run #{c.run_id} · tick {c.max_tick} ·{' '}
                    <span className="font-mono">
                      {c.family_a || '?'} vs {c.family_b || '?'}
                    </span>
                    {c.name_b ? <span className="opacity-60"> (town B: {c.name_b})</span> : null}
                  </span>
                  <span className="font-mono text-[10px] opacity-60">
                    {OUTCOME_KEYS.map(
                      (k) => `${OUTCOME_LABELS[k]} ${compact(c.outcomes[k] ?? 0)}`,
                    ).join('  ')}
                  </span>
                </div>
                <div className="font-mono text-[10px] opacity-70">
                  {Object.entries(c.population_by_town)
                    .map(([town, n]) => `${town} ${n}`)
                    .join(' · ') || 'no towns yet'}
                  {c.contact_made
                    ? ` · 🌍 first contact t${c.contact_made.tick}`
                    : ' · no crossing yet'}
                  {c.ledger
                    ? ` · ${c.ledger.crossings} crossings`
                    : ''}
                </div>
                <FailureCurve points={c.failures.curve} testid={`arena-contact-curve-${c.run_id}`} />
                <FailureTaxonomyLine
                  f={c.failures}
                  testid={`arena-contact-failures-${c.run_id}`}
                />
                <FailureByAgent f={c.failures} testidPrefix={`arena-contact-agent-${c.run_id}`} />
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
