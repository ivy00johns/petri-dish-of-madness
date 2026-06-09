/**
 * RunComparison (W11a EM-086, frontend-inspector.md §8) — cross-run AWI
 * comparison: TWO runs' `GET /api/analytics?run_id=` summaries side by side.
 *
 * Renders the SAME nine agent-welfare indicators the AWIDashboard shows, as
 * per-run columns plus a simple numeric delta (B − A) — deliberately NO
 * composite score (weighting nine welfare dimensions embeds values), and no
 * new chart machinery: numbers side-by-side is the contract's minimum viable,
 * formatted by the dashboard's own pct/compact helpers so the figures read
 * identically everywhere. Below the indicators, each run's per-model table.
 *
 * The backend dict is snake_case (event-log.md §7 get_analytics); it is parsed
 * defensively into the typed AwiSummary view-model — absent/odd fields become
 * zeros, never a crash. Fetch failure per run renders a labeled error state.
 * Token-only styling (lab-* classes); §7 empty states throughout.
 */

import { useEffect, useMemo, useState } from 'react';
import { inspectorApi } from './api';
import type { RunRow } from './api';
import type { AwiSummary, AwiByModel } from './types';
import { pct, compact, sumValues, avgValues } from './AWIDashboard';

// ── snake_case backend dict → typed AwiSummary (defensive, zero-defaulting) ──

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}
function asNum(v: unknown, fallback = 0): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}
function numRecord(v: unknown): Record<string, number> {
  const out: Record<string, number> = {};
  if (isObj(v)) {
    for (const [k, val] of Object.entries(v)) {
      if (typeof val === 'number' && Number.isFinite(val)) out[k] = val;
    }
  }
  return out;
}

/** Lift the backend get_analytics dict into the AwiSummary view-model. */
export function parseApiAnalytics(raw: Record<string, unknown>): AwiSummary {
  const population: Array<{ tick: number; alive: number }> = [];
  if (Array.isArray(raw.population)) {
    for (const p of raw.population) {
      if (isObj(p)) population.push({ tick: asNum(p.tick), alive: asNum(p.alive) });
    }
    population.sort((a, b) => a.tick - b.tick);
  }

  const crime = isObj(raw.crime) ? raw.crime : {};
  const tools = isObj(raw.tool_exploration) ? raw.tool_exploration : {};
  const space = isObj(raw.space_exploration) ? raw.space_exploration : {};
  const gov = isObj(raw.governance) ? raw.governance : {};
  const expr = isObj(raw.public_expression) ? raw.public_expression : {};
  const fabric = isObj(raw.social_fabric) ? raw.social_fabric : {};
  const economy = isObj(raw.economy) ? raw.economy : {};
  const constitution = isObj(raw.constitution) ? raw.constitution : {};

  const byModel: Record<string, AwiByModel> = {};
  if (isObj(raw.by_model)) {
    for (const [name, m] of Object.entries(raw.by_model)) {
      if (!isObj(m)) continue;
      byModel[name] = {
        alive: asNum(m.alive),
        dead: asNum(m.dead),
        crimes: asNum(m.crimes),
        gives: asNum(m.gives),
        proposals: asNum(m.proposals),
        passed: asNum(m.passed),
        rejected: asNum(m.rejected), // optional in event-log.md §7 — defaults 0
        creditShare: asNum(m.credit_share),
      };
    }
  }

  const usageByProfile: AwiSummary['usage']['byProfile'] = {};
  const usage = isObj(raw.usage) ? raw.usage : {};
  if (isObj(usage.by_profile)) {
    for (const [name, u] of Object.entries(usage.by_profile)) {
      if (!isObj(u)) continue;
      usageByProfile[name] = {
        requests: asNum(u.requests),
        inputTokens: asNum(u.input_tokens),
        outputTokens: asNum(u.output_tokens),
      };
    }
  }

  return {
    population,
    crime: { byKind: numRecord(crime.by_kind) },
    toolExploration: { byAgent: numRecord(tools.by_agent) },
    spaceExploration: { byAgent: numRecord(space.by_agent) },
    governance: {
      participation: asNum(gov.participation),
      proposed: asNum(gov.proposed),
      passed: asNum(gov.passed),
      rejected: asNum(gov.rejected),
    },
    publicExpression: { say: asNum(expr.say), proposeRule: asNum(expr.propose_rule) },
    socialFabric: { edges: asNum(fabric.edges), byType: numRecord(fabric.by_type) },
    economy: {
      gini: asNum(economy.gini),
      throughput: asNum(economy.throughput),
      byAgent: numRecord(economy.by_agent),
    },
    constitution: {
      activeRules: asNum(constitution.active_rules),
      amendments: asNum(constitution.amendments),
    },
    byModel,
    usage: { byProfile: usageByProfile },
  };
}

// ── per-run analytics fetch state ─────────────────────────────────────────────

type RunAnalytics =
  | { status: 'loading' }
  | { status: 'failed' }
  | { status: 'ready'; summary: AwiSummary };

function useRunAnalytics(runId: number): RunAnalytics {
  const [state, setState] = useState<RunAnalytics>({ status: 'loading' });
  useEffect(() => {
    let alive = true;
    setState({ status: 'loading' });
    void inspectorApi.runAnalytics(runId).then((raw) => {
      if (!alive) return;
      setState(raw === null ? { status: 'failed' } : { status: 'ready', summary: parseApiAnalytics(raw) });
    });
    return () => {
      alive = false;
    };
  }, [runId]);
  return state;
}

// ── the nine indicator rows (label + numeric extractor + formatter) ──────────

interface IndicatorRow {
  label: string;
  /** Numeric value (drives the delta column). */
  value: (s: AwiSummary) => number;
  format: (n: number) => string;
  hint?: string;
}

const INDICATOR_ROWS: IndicatorRow[] = [
  {
    label: 'Population',
    value: (s) => s.population[s.population.length - 1]?.alive ?? 0,
    format: (n) => String(Math.round(n)),
    hint: 'agents alive at the run end',
  },
  {
    label: 'Crime',
    value: (s) => sumValues(s.crime.byKind),
    format: compact,
    hint: 'total crime events',
  },
  {
    label: 'Exploration',
    value: (s) => avgValues(s.toolExploration.byAgent),
    format: (n) => n.toFixed(1),
    hint: 'unique tools per agent (avg)',
  },
  {
    label: 'Governance',
    value: (s) => s.governance.participation,
    format: pct,
    hint: 'vote participation',
  },
  {
    label: 'Public expression',
    value: (s) => s.publicExpression.say,
    format: compact,
    hint: 'speech events',
  },
  {
    label: 'Social fabric',
    value: (s) => s.socialFabric.edges,
    format: (n) => String(Math.round(n)),
    hint: 'relationship edges',
  },
  {
    label: 'Economy (gini)',
    value: (s) => s.economy.gini,
    format: (n) => n.toFixed(2),
    hint: '0 = equal · →1 = unequal',
  },
  {
    label: 'Constitution',
    value: (s) => s.constitution.activeRules,
    format: (n) => String(Math.round(n)),
    hint: 'active rules',
  },
  {
    label: 'Token usage',
    value: (s) => Object.values(s.usage.byProfile).reduce((acc, u) => acc + u.requests, 0),
    format: compact,
    hint: 'llm requests',
  },
];

/** Signed delta, formatted with the row's own formatter. */
function formatDelta(row: IndicatorRow, a: number, b: number): string {
  const d = b - a;
  if (d === 0) return '±0';
  return `${d > 0 ? '+' : '−'}${row.format(Math.abs(d))}`;
}

// ── component ─────────────────────────────────────────────────────────────────

export interface RunComparisonProps {
  runA: RunRow;
  runB: RunRow;
  onClose: () => void;
}

export default function RunComparison({ runA, runB, onClose }: RunComparisonProps) {
  const a = useRunAnalytics(runA.id);
  const b = useRunAnalytics(runB.id);

  const ready = a.status === 'ready' && b.status === 'ready';

  return (
    <div className="border border-lab-border-bright bg-lab-bg" aria-label="Cross-run AWI comparison (EM-086)">
      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-lab-border bg-lab-surface">
        <span className="font-mono text-[10px] font-bold uppercase tracking-widest text-lab-text">
          Compare · run #{runA.id} vs run #{runB.id}
        </span>
        <span className="font-mono text-[9px] text-lab-dim normal-case">
          9 AWI indicators · no composite score
        </span>
        <button
          type="button"
          onClick={onClose}
          className="font-mono text-[10px] px-2 py-0.5 border border-lab-border text-lab-muted hover:text-lab-text hover:border-lab-border-bright"
        >
          close
        </button>
      </div>

      {!ready ? (
        <div className="p-4 text-center">
          <span className="font-mono text-[10px] uppercase tracking-widest text-lab-muted border border-lab-border px-2 py-0.5">
            {a.status === 'failed' || b.status === 'failed'
              ? `couldn't load analytics for run #${a.status === 'failed' ? runA.id : runB.id}`
              : 'loading run analytics…'}
          </span>
        </div>
      ) : (
        <div className="flex flex-col gap-3 p-3">
          {(runA.event_count === 0 || runB.event_count === 0) && (
            <p className="font-mono text-[9px] text-lab-warn">
              run #{runA.event_count === 0 ? runA.id : runB.id} has no events — its
              indicators read as zeros.
            </p>
          )}

          {/* The nine indicators: per-run columns + numeric delta. */}
          <div className="overflow-x-auto">
            <table className="w-full border-collapse font-mono text-[10px]">
              <thead>
                <tr className="text-lab-muted uppercase tracking-wide">
                  <th className="text-left font-medium py-1 pr-2">indicator</th>
                  <th className="text-right font-medium py-1 px-2">run #{runA.id}</th>
                  <th className="text-right font-medium py-1 px-2">run #{runB.id}</th>
                  <th className="text-right font-medium py-1 pl-2" title="run B minus run A">
                    Δ
                  </th>
                </tr>
              </thead>
              <tbody>
                {INDICATOR_ROWS.map((row) => {
                  const va = row.value(a.summary);
                  const vb = row.value(b.summary);
                  return (
                    <tr key={row.label} className="border-t border-lab-border text-lab-text">
                      <td className="py-1 pr-2" title={row.hint}>
                        {row.label}
                      </td>
                      <td className="text-right tabular-nums py-1 px-2">{row.format(va)}</td>
                      <td className="text-right tabular-nums py-1 px-2">{row.format(vb)}</td>
                      <td
                        className={`text-right tabular-nums py-1 pl-2 ${
                          vb === va ? 'text-lab-dim' : 'text-lab-acid'
                        }`}
                      >
                        {formatDelta(row, va, vb)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Per-model cut, one table per run. */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <ModelTable title={`run #${runA.id} · by model`} summary={a.summary} />
            <ModelTable title={`run #${runB.id} · by model`} summary={b.summary} />
          </div>
        </div>
      )}
    </div>
  );
}

function ModelTable({ title, summary }: { title: string; summary: AwiSummary }) {
  const rows = useMemo(
    () =>
      (Object.entries(summary.byModel) as Array<[string, AwiByModel]>).sort((x, y) => {
        const popX = x[1].alive + x[1].dead;
        const popY = y[1].alive + y[1].dead;
        return popY - popX || y[1].creditShare - x[1].creditShare;
      }),
    [summary.byModel],
  );

  return (
    <div className="border border-lab-border p-2 min-w-0">
      <span className="font-mono text-[9px] uppercase tracking-wider text-lab-muted">{title}</span>
      {rows.length === 0 ? (
        <p className="font-mono text-[10px] text-lab-dim mt-1">no per-model data in this run</p>
      ) : (
        <div className="overflow-x-auto mt-1">
          <table className="w-full border-collapse font-mono text-[10px]">
            <thead>
              <tr className="text-lab-muted uppercase tracking-wide">
                <th className="text-left font-medium py-0.5 pr-2">model</th>
                <th className="text-right font-medium py-0.5 px-1" title="alive / total agents">
                  alive
                </th>
                <th className="text-right font-medium py-0.5 px-1">crimes</th>
                <th className="text-right font-medium py-0.5 px-1">gives</th>
                <th
                  className="text-right font-medium py-0.5 px-1"
                  title="proposals passed / proposed"
                >
                  gov
                </th>
                <th className="text-right font-medium py-0.5 pl-1" title="share of total credits">
                  credit
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(([name, m]) => (
                <tr key={name} className="border-t border-lab-border text-lab-text">
                  <td className="py-0.5 pr-2 truncate max-w-[12ch]" title={name}>
                    {name}
                  </td>
                  <td className="text-right tabular-nums py-0.5 px-1">
                    {m.alive}/{m.alive + m.dead}
                  </td>
                  <td className="text-right tabular-nums py-0.5 px-1">{m.crimes}</td>
                  <td className="text-right tabular-nums py-0.5 px-1">{m.gives}</td>
                  <td className="text-right tabular-nums py-0.5 px-1" title={`${m.proposals} proposed · ${m.passed} passed · ${m.rejected} rejected`}>
                    {m.proposals > 0 ? `${m.passed}/${m.proposals}` : '—'}
                  </td>
                  <td className="text-right tabular-nums py-0.5 pl-1">{pct(m.creditShare)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
