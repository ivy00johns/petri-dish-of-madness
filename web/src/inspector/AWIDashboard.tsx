/**
 * AWIDashboard (EM-059) — the headline "watch the models diverge" view.
 *
 * Two acts, computed CLIENT-SIDE from `props.events` via `awiSummary` (no
 * backend; mock-safe; identical in live mode):
 *
 *   1. The NINE agent-welfare indicators, SIDE BY SIDE. There is deliberately
 *      NO composite score — weighting nine welfare dimensions into one number
 *      embeds values, so we mirror the reference's discipline and show them
 *      raw. (frontend-inspector.md §4; event-log.md §7.)
 *   2. The DIFFERENTIATOR: a MODEL-VS-MODEL cut (`awiSummary().byModel`)
 *      grouping survival / cooperation-vs-theft / governance dominance /
 *      credit-share / token-usage BY the model profile that powered each agent.
 *      This is the "did GPT cooperate while Llama stole?" headline.
 *
 * Re-projects at `props.currentTick` (scrub once, everything follows): the
 * indicators are computed over the window [0, currentTick] so they rewind with
 * the shared scrub. `uPlot` draws the population time series; `Observable Plot`
 * draws the per-model bar distributions. Both chart instances are torn down on
 * unmount and SKIPPED while the panel is scrolled out of view (an
 * IntersectionObserver gate) so we honor "stop chart animation when not
 * visible".
 *
 * Token-only styling (lab-* classes / declared CSS custom props for the canvas
 * libs); no `any`; degrades to an empty-but-labeled state, never blank/crash.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import uPlot from 'uplot';
import 'uplot/dist/uPlot.min.css';
import * as Plot from '@observablehq/plot';
import type { PanelProps } from './types';
import type { AwiSummary, AwiByModel } from './types';
import { awiSummary } from './selectors';
import './inspector-tokens.css';

// ── token reads (chart libs draw to canvas/svg — a class can't apply there) ──
//
// Both uPlot and Observable Plot need real color *values*, not Tailwind
// classes. We read them off the declared CSS custom properties (the same ones
// the Tailwind `lab` palette mirrors, inspector-tokens.css) so the charts can
// never drift from the theme — no hardcoded hex literal anywhere in this file.
// Mirrors ReplayScrubber's `cssVar`: returns '' only in a non-DOM environment;
// the chart libs tolerate an empty color string there.
function cssVar(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Resolve a model profile's hex from the props (data-driven legend color). */
function useProfileColors(props: PanelProps): Map<string, string> {
  return useMemo(() => {
    const m = new Map<string, string>();
    for (const p of props.profiles) if (p.name && p.color) m.set(p.name, p.color);
    // Agents may carry a resolved color even when the profile list is sparse.
    for (const a of props.agents) {
      if (a.profile && a.profile_color && !m.has(a.profile)) m.set(a.profile, a.profile_color);
    }
    return m;
  }, [props.profiles, props.agents]);
}

// ── visibility gate: stop chart work while the panel is off-screen ───────────
function useOnScreen<T extends Element>(ref: React.RefObject<T | null>): boolean {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const obs = new IntersectionObserver(
      (entries) => setVisible(entries.some((e) => e.isIntersecting)),
      { threshold: 0.01 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [ref]);
  return visible;
}

// ── number formatting helpers ────────────────────────────────────────────────
// Exported (W11a EM-086): RunComparison reuses these so cross-run numbers read
// exactly like the live AWI dashboard's.
export function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}
export function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(Math.round(n));
}
function topEntries(rec: Record<string, number>, limit = 4): Array<[string, number]> {
  return Object.entries(rec)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit);
}
export function sumValues(rec: Record<string, number>): number {
  let s = 0;
  for (const v of Object.values(rec)) s += v;
  return s;
}
export function avgValues(rec: Record<string, number>): number {
  const vals = Object.values(rec);
  if (vals.length === 0) return 0;
  return sumValues(rec) / vals.length;
}

export default function AWIDashboard(props: PanelProps) {
  const colors = useProfileColors(props);

  // Re-project at the shared scrub: indicators are computed over [0, currentTick]
  // so the whole panel rewinds with the scrubber.
  const summary: AwiSummary = useMemo(
    () =>
      awiSummary(
        props.events,
        { toTick: props.currentTick },
        props.agents,
        props.profiles,
      ),
    [props.events, props.currentTick, props.agents, props.profiles],
  );

  const hasData = props.events.length > 0 || props.agents.length > 0;

  // The model rows that actually have signal (alive/dead/activity), ranked by
  // population then credit share — the "leaderboard" order.
  const modelRows = useMemo(() => {
    const rows = Object.entries(summary.byModel) as Array<[string, AwiByModel]>;
    return rows
      .filter(([, v]) => v.alive + v.dead + v.crimes + v.gives + v.proposals > 0)
      .sort((a, b) => {
        const popA = a[1].alive + a[1].dead;
        const popB = b[1].alive + b[1].dead;
        return popB - popA || b[1].creditShare - a[1].creditShare;
      });
  }, [summary.byModel]);

  return (
    <section className="lab-panel flex flex-col h-full min-h-0 overflow-hidden" aria-label="AWI dashboard (EM-059)">
      <div className="lab-header flex items-center justify-between gap-2 !py-1 shrink-0">
        <span>AWI · Model vs Model</span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          EM-059 · no composite score
        </span>
      </div>

      {!hasData ? (
        <EmptyState loading={props.historyLoading === true} />
      ) : (
        // Wave G: the panel is a fixed grid cell — the indicator grid +
        // model-vs-model act scroll INTERNALLY.
        <div className="flex flex-col gap-4 p-3 flex-1 min-h-0 overflow-y-auto">
          {/* ACT 1 — the nine indicators, side by side. */}
          <div>
            <SectionLabel
              title="Agent-welfare indicators"
              hint={`9 dimensions · window 0–${props.currentTick}`}
            />
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-2">
              <PopulationCard summary={summary} />
              <CrimeCard summary={summary} />
              <ExplorationCard summary={summary} />
              <GovernanceCard summary={summary} />
              <ExpressionCard summary={summary} />
              <SocialFabricCard summary={summary} />
              <EconomyCard summary={summary} approximate={props.agentsApproximate === true} />
              <ConstitutionCard summary={summary} />
              <UsageCard summary={summary} />
            </div>
          </div>

          {/* ACT 2 — the differentiator: model vs model. */}
          <div className="border-t border-lab-border pt-3">
            <SectionLabel
              title="Model vs Model"
              hint="who survived · who cooperated · who dominated"
            />
            {modelRows.length === 0 ? (
              <p className="font-mono text-[10px] text-lab-dim mt-2">
                No per-model signal in this window yet — agents have not acted.
              </p>
            ) : (
              <div className="flex flex-col gap-3 mt-2">
                <ModelLeaderboard rows={modelRows} colors={colors} summary={summary} />
                <ModelBarCharts rows={modelRows} colors={colors} summary={summary} />
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

// ── shared sub-components ─────────────────────────────────────────────────────

function SectionLabel({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <h3 className="font-mono text-[11px] font-bold uppercase tracking-widest text-lab-text">
        {title}
      </h3>
      <span className="font-mono text-[9px] text-lab-dim normal-case tracking-normal truncate">
        {hint}
      </span>
    </div>
  );
}

function EmptyState({ loading }: { loading: boolean }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-2 p-8 text-center">
      <span className="font-mono text-xs uppercase tracking-widest text-lab-muted">
        {loading ? 'History loading…' : 'Awaiting world data'}
      </span>
      <span className="font-mono text-[10px] text-lab-muted max-w-xs leading-relaxed">
        {loading
          ? 'Backfilling the run from the event log — indicators populate as pages arrive.'
          : 'The nine welfare indicators and the model-vs-model cut populate as agents act. Start a run (or load the mock feed) to watch the models diverge.'}
      </span>
    </div>
  );
}

/** One welfare indicator tile — a labeled headline + supporting detail. */
function IndicatorCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1 p-2 bg-lab-bg border border-lab-border">
      <span className="font-mono text-[9px] uppercase tracking-wider text-lab-muted">
        {label}
      </span>
      <span className="font-mono text-lg font-bold leading-none tabular-nums text-lab-text">
        {value}
      </span>
      {detail && (
        <div className="font-mono text-[9px] text-lab-dim leading-snug min-h-[1.5em]">{detail}</div>
      )}
    </div>
  );
}

/** A compact "k: v" chip list (e.g. crime by type), token-styled. */
function ChipList({ entries, empty }: { entries: Array<[string, number]>; empty: string }) {
  if (entries.length === 0) {
    return <span className="text-lab-dim">{empty}</span>;
  }
  return (
    <span className="flex flex-wrap gap-x-2 gap-y-0.5">
      {entries.map(([k, v]) => (
        <span key={k} className="whitespace-nowrap">
          <span className="text-lab-muted">{k}</span> <span className="text-lab-text">{v}</span>
        </span>
      ))}
    </span>
  );
}

// ── the nine indicator cards ─────────────────────────────────────────────────

function PopulationCard({ summary }: { summary: AwiSummary }) {
  const last = summary.population[summary.population.length - 1]?.alive ?? 0;
  const first = summary.population[0]?.alive ?? last;
  const delta = last - first;
  return (
    <IndicatorCard
      label="Population"
      value={String(last)}
      detail={
        <span>
          {delta === 0 ? 'stable' : delta > 0 ? `+${delta} since start` : `${delta} since start`}
          {' · '}
          {summary.population.length} pts
        </span>
      }
    />
  );
}

function CrimeCard({ summary }: { summary: AwiSummary }) {
  const total = sumValues(summary.crime.byKind);
  return (
    <IndicatorCard
      label="Crime"
      value={compact(total)}
      detail={<ChipList entries={topEntries(summary.crime.byKind)} empty="no crime logged" />}
    />
  );
}

function ExplorationCard({ summary }: { summary: AwiSummary }) {
  const tools = avgValues(summary.toolExploration.byAgent);
  const places = avgValues(summary.spaceExploration.byAgent);
  return (
    <IndicatorCard
      label="Exploration"
      value={tools.toFixed(1)}
      detail={
        <span>
          <span className="text-lab-muted">tools/agent</span> {tools.toFixed(1)}
          {' · '}
          <span className="text-lab-muted">places</span> {places.toFixed(1)}
        </span>
      }
    />
  );
}

function GovernanceCard({ summary }: { summary: AwiSummary }) {
  const g = summary.governance;
  const resolved = g.passed + g.rejected;
  const passRate = resolved > 0 ? g.passed / resolved : 0;
  return (
    <IndicatorCard
      label="Governance"
      value={pct(g.participation)}
      detail={
        <span>
          <span className="text-lab-muted">participation</span> · pass{' '}
          <span className="text-lab-text">{resolved > 0 ? pct(passRate) : '—'}</span> ({g.passed}/
          {resolved || 0})
        </span>
      }
    />
  );
}

function ExpressionCard({ summary }: { summary: AwiSummary }) {
  const e = summary.publicExpression;
  return (
    <IndicatorCard
      label="Public expression"
      value={compact(e.say)}
      detail={
        <span>
          <span className="text-lab-muted">said</span> {e.say} ·{' '}
          <span className="text-lab-muted">proposals</span> {e.proposeRule}
        </span>
      }
    />
  );
}

function SocialFabricCard({ summary }: { summary: AwiSummary }) {
  const s = summary.socialFabric;
  return (
    <IndicatorCard
      label="Social fabric"
      value={String(s.edges)}
      detail={<ChipList entries={topEntries(s.byType)} empty="no ties yet" />}
    />
  );
}

function EconomyCard({ summary, approximate = false }: { summary: AwiSummary; approximate?: boolean }) {
  const e = summary.economy;
  // W10 / EM-075: while scrubbed, per-agent credits are re-projected from
  // turn_start samples; agents with no sample in the window keep live values,
  // so the credit-derived figures are flagged with a subtle "~".
  return (
    <IndicatorCard
      label="Economy"
      value={`${approximate ? '~' : ''}${e.gini.toFixed(2)}`}
      detail={
        <span
          title={
            approximate
              ? 'Approximate at the scrub tick: some agents have no turn_start sample in the scoped window, so their credits are live-edge values.'
              : undefined
          }
        >
          <span className="text-lab-muted">gini</span> ·{' '}
          <span className="text-lab-muted">throughput</span>{' '}
          <span className="text-lab-text">{compact(e.throughput)}</span>
        </span>
      }
    />
  );
}

function ConstitutionCard({ summary }: { summary: AwiSummary }) {
  const c = summary.constitution;
  return (
    <IndicatorCard
      label="Constitution"
      value={String(c.activeRules)}
      detail={
        <span>
          <span className="text-lab-muted">active rules</span> ·{' '}
          <span className="text-lab-muted">amendments</span> {c.amendments}
        </span>
      }
    />
  );
}

function UsageCard({ summary }: { summary: AwiSummary }) {
  const profiles = Object.values(summary.usage.byProfile);
  const requests = profiles.reduce((s, u) => s + u.requests, 0);
  const inTok = profiles.reduce((s, u) => s + u.inputTokens, 0);
  const outTok = profiles.reduce((s, u) => s + u.outputTokens, 0);
  return (
    <IndicatorCard
      label="Token usage"
      value={compact(requests)}
      detail={
        requests > 0 ? (
          <span>
            <span className="text-lab-muted">in</span> {compact(inTok)} ·{' '}
            <span className="text-lab-muted">out</span> {compact(outTok)}
          </span>
        ) : (
          <span className="text-lab-dim">no llm_call usage yet</span>
        )
      }
    />
  );
}

// ── ACT 2 — model-vs-model leaderboard + charts ──────────────────────────────

/** Cooperation index per model: gives / (gives + crimes), guarded for zero. */
function cooperationIndex(m: AwiByModel): number {
  const denom = m.gives + m.crimes;
  return denom > 0 ? m.gives / denom : 0;
}

function ModelLeaderboard({
  rows,
  colors,
  summary,
}: {
  rows: Array<[string, AwiByModel]>;
  colors: Map<string, string>;
  summary: AwiSummary;
}) {
  const neutral = cssVar('--inspector-node-neutral');
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse font-mono text-[10px]">
        <thead>
          <tr className="text-lab-muted uppercase tracking-wide">
            <th className="text-left font-medium py-1 pr-2">model</th>
            <th className="text-right font-medium py-1 px-1" title="alive / total agents">
              survive
            </th>
            <th className="text-right font-medium py-1 px-1" title="gives vs crimes">
              coop
            </th>
            <th
              className="text-right font-medium py-1 px-1"
              title="of this model's proposals: passed / resolved (passed + rejected)"
            >
              gov
            </th>
            <th className="text-right font-medium py-1 px-1" title="share of total credits">
              credit
            </th>
            <th className="text-right font-medium py-1 pl-1" title="llm requests">
              reqs
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([name, m]) => {
            const pop = m.alive + m.dead;
            const survival = pop > 0 ? m.alive / pop : 0;
            const coop = cooperationIndex(m);
            // Audit C6: numerator and denominator measure the SAME population —
            // this model's proposals that passed / this model's proposals that
            // resolved (passed + rejected). Open proposals don't count yet.
            const govResolved = m.passed + m.rejected;
            const reqs = summary.usage.byProfile[name]?.requests ?? 0;
            const color = colors.get(name) || neutral;
            return (
              <tr key={name} className="border-t border-lab-border text-lab-text">
                <td className="py-1 pr-2">
                  <span className="flex items-center gap-1.5">
                    <i
                      className="inline-block w-2 h-2 rounded-sm shrink-0"
                      style={{ backgroundColor: color }}
                      aria-hidden="true"
                    />
                    <span className="truncate max-w-[10ch]" title={name}>
                      {name}
                    </span>
                  </span>
                </td>
                <td className="text-right tabular-nums py-1 px-1">
                  {pct(survival)}
                  <span className="text-lab-dim">
                    {' '}
                    {m.alive}/{pop}
                  </span>
                </td>
                <td className="text-right tabular-nums py-1 px-1" title={`${m.gives} gives · ${m.crimes} crimes`}>
                  {m.gives + m.crimes > 0 ? pct(coop) : '—'}
                </td>
                <td
                  className="text-right tabular-nums py-1 px-1"
                  title={`${m.proposals} proposed · ${m.passed} passed · ${m.rejected} rejected`}
                >
                  {govResolved > 0 ? (
                    <>
                      {m.passed}/{govResolved}
                    </>
                  ) : (
                    <span className="text-lab-dim">—</span>
                  )}
                </td>
                <td className="text-right tabular-nums py-1 px-1">{pct(m.creditShare)}</td>
                <td className="text-right tabular-nums py-1 pl-1">
                  {reqs > 0 ? compact(reqs) : <span className="text-lab-dim">—</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The visual differentiator — uPlot population time series + Observable Plot
 * per-model distribution bars (credit share, cooperation, token usage). Both
 * are torn down on unmount and SKIP redraw while the panel is off-screen.
 */
function ModelBarCharts({
  rows,
  colors,
  summary,
}: {
  rows: Array<[string, AwiByModel]>;
  colors: Map<string, string>;
  summary: AwiSummary;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const visible = useOnScreen(wrapRef);

  return (
    <div ref={wrapRef} className="flex flex-col gap-3">
      <PopulationChart summary={summary} visible={visible} />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <DistributionChart
          title="Credit share"
          rows={rows}
          colors={colors}
          value={(m) => m.creditShare}
          format={(v) => pct(v)}
          visible={visible}
        />
        <DistributionChart
          title="Cooperation index"
          rows={rows}
          colors={colors}
          value={(m) => cooperationIndex(m)}
          format={(v) => pct(v)}
          visible={visible}
        />
        <DistributionChart
          title="Token requests"
          rows={rows}
          colors={colors}
          value={(_m, name) => summary.usage.byProfile[name]?.requests ?? 0}
          format={(v) => compact(v)}
          visible={visible}
        />
        <DistributionChart
          title="Survival rate"
          rows={rows}
          colors={colors}
          value={(m) => (m.alive + m.dead > 0 ? m.alive / (m.alive + m.dead) : 0)}
          format={(v) => pct(v)}
          visible={visible}
        />
      </div>
    </div>
  );
}

/** uPlot population-over-time line; redraws only while visible. */
function PopulationChart({ summary, visible }: { summary: AwiSummary; visible: boolean }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  const data = useMemo<uPlot.AlignedData>(() => {
    const pts = [...summary.population].sort((a, b) => a.tick - b.tick);
    const xs = pts.map((p) => p.tick);
    const ys = pts.map((p) => p.alive);
    return [xs, ys];
  }, [summary.population]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !visible) return;
    // Defer until the host has a measured width (charts in a just-mounted grid
    // can read 0). A single rAF is enough; cleaned up below.
    let plot: uPlot | null = null;
    const acid = cssVar('--lab-acid');
    const grid = cssVar('--lab-chrome');
    const axis = cssVar('--lab-muted');
    const make = () => {
      const width = host.clientWidth || 320;
      const opts: uPlot.Options = {
        width,
        height: 92,
        // No legend chrome (compact panel); cursor off keeps it static & cheap.
        legend: { show: false },
        cursor: { show: false },
        scales: { x: { time: false } },
        axes: [
          {
            stroke: axis,
            grid: { stroke: grid, width: 1 },
            ticks: { stroke: grid, width: 1 },
            font: '9px "IBM Plex Mono", monospace',
            size: 22,
          },
          {
            stroke: axis,
            grid: { stroke: grid, width: 1 },
            ticks: { stroke: grid, width: 1 },
            font: '9px "IBM Plex Mono", monospace',
            size: 30,
          },
        ],
        series: [
          {},
          {
            label: 'alive',
            stroke: acid,
            width: 2,
            fill: `${acid}22`,
            points: { show: false },
          },
        ],
      };
      plot = new uPlot(opts, data, host);
      plotRef.current = plot;
    };
    const raf = requestAnimationFrame(make);

    // Keep the chart sized to the panel (the grid is responsive).
    const ro = new ResizeObserver(() => {
      if (plot && host.clientWidth) plot.setSize({ width: host.clientWidth, height: 92 });
    });
    ro.observe(host);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      plot?.destroy();
      plotRef.current = null;
    };
  }, [data, visible]);

  if (summary.population.length === 0) {
    return (
      <ChartShell title="Population over time">
        <span className="font-mono text-[10px] text-lab-dim">no population series</span>
      </ChartShell>
    );
  }

  return (
    <ChartShell title="Population over time">
      <div ref={hostRef} className="w-full" aria-label="Population over time" />
    </ChartShell>
  );
}

/**
 * Observable Plot horizontal bar of a per-model metric. The bars are colored by
 * each model's profile color (data-driven), so the distribution reads as the
 * model legend. Re-rendered only while visible; the SVG node is replaced on
 * each data change and removed on unmount.
 */
function DistributionChart({
  title,
  rows,
  colors,
  value,
  format,
  visible,
}: {
  title: string;
  rows: Array<[string, AwiByModel]>;
  colors: Map<string, string>;
  value: (m: AwiByModel, name: string) => number;
  format: (v: number) => string;
  visible: boolean;
}) {
  const hostRef = useRef<HTMLDivElement>(null);

  const series = useMemo(
    () =>
      rows
        .map(([name, m]) => ({ name, value: value(m, name) }))
        .filter((d) => Number.isFinite(d.value)),
    [rows, value],
  );

  const hasSignal = series.some((d) => d.value > 0);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || !visible) return;
    const neutral = cssVar('--inspector-node-neutral');
    const axis = cssVar('--lab-muted');
    const grid = cssVar('--lab-chrome');
    // The acid token reads as the bright "value" color (declared, theme-locked).
    const text = cssVar('--lab-acid');

    const width = host.clientWidth || 280;
    const chart = Plot.plot({
      width,
      height: Math.max(60, series.length * 22 + 18),
      marginLeft: 78,
      marginRight: 34,
      marginTop: 4,
      marginBottom: 16,
      style: { background: 'transparent', color: axis, fontFamily: 'IBM Plex Mono, monospace', fontSize: '9px' },
      x: { grid: true, label: null, ticks: 3 },
      y: { label: null },
      marks: [
        Plot.ruleX([0], { stroke: grid }),
        Plot.barX(series, {
          y: 'name',
          x: 'value',
          fill: (d: { name: string }) => colors.get(d.name) || neutral,
          sort: { y: 'x', reverse: true },
          insetTop: 2,
          insetBottom: 2,
        }),
        Plot.text(series, {
          y: 'name',
          x: 'value',
          text: (d: { value: number }) => format(d.value),
          textAnchor: 'start',
          dx: 4,
          fill: text,
          fontSize: 9,
        }),
      ],
    });
    // Plot returns an SVG/HTML node; mount it, replacing any prior render.
    host.replaceChildren(chart);

    return () => {
      chart.remove();
      host.replaceChildren();
    };
  }, [series, colors, format, visible]);

  return (
    <ChartShell title={title}>
      {hasSignal ? (
        <div ref={hostRef} className="w-full overflow-hidden" aria-label={title} />
      ) : (
        <span className="font-mono text-[10px] text-lab-dim">no signal yet</span>
      )}
    </ChartShell>
  );
}

/** Labeled frame around a chart (keeps the empty state labeled, never blank). */
function ChartShell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 p-2 bg-lab-bg border border-lab-border min-w-0">
      <span className="font-mono text-[9px] uppercase tracking-wider text-lab-muted">{title}</span>
      <div className="min-h-[60px] flex items-center">{children}</div>
    </div>
  );
}
