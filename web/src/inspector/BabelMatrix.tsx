/**
 * BabelMatrix (EM-314) — dyadic inter-model social physics.
 *
 * A ZERO-LLM N×N heatmap: rows are the ACTOR's model, columns the model of the
 * agent it acted upon. Each cell is that dyad's positive-outcome rate (trades
 * settled vs. declined, lessons landed vs. failed), mined retroactively from the
 * event log by the backend (`GET /api/babel-matrix`, fingerprint.dyadic). The
 * science question: is cooperation a property of the agent, or of the
 * RELATIONSHIP between two weight-sets? Only a mixed-model society answers it.
 *
 * FEED/VIEWER chrome, strictly OFF the replay surface: read-only, no sim
 * feedback. Gated behind BABEL_MATRIX_ENABLED (the frontend half of
 * `babel_matrix.enabled`, default OFF) — when off, InspectorLayout never mounts
 * this panel, so the tree is byte-identical to before.
 *
 * HONEST CONFIDENCE: thin dyad samples are FADED (colour intensity scales with
 * n) and the cell title carries the Wilson 95% interval, so a 2-of-2 streak
 * never masquerades as a confident 100%. CLICK-THROUGH: selecting a cell lists
 * its receipts — the exact events, model chips on both ends — turning a finding
 * into quotable, replayable evidence rather than a chart alone.
 *
 * Token-only styling (lab-* classes / --lab-* custom props). The sole inline
 * styles are the DATA-DRIVEN per-cell colour + opacity and the config-sourced
 * model-chip colour — computed values a static class cannot express, mirroring
 * the sanctioned cssVar escape hatch the AWI/SocialGraph panels use.
 */
import { useEffect, useMemo, useState } from 'react';
import { inspectorApi } from './api';
import type { BabelCell, BabelMatrix as BabelMatrixData, BabelReceipt } from './api';
import type { ModelProfile } from '../types';
import './inspector-tokens.css';

/**
 * Frontend half of the `babel_matrix.enabled` flag — mirrors the
 * ROAD_MESH_ENABLED / GRAPH_LOTS_ENABLED const pattern.
 * Default ON since the EM-314 live sign-off (2026-10-03): the panel mounts in
 * the Inspector and the backend endpoint is enabled at boot via
 * PETRIDISH_BABEL_MATRIX_ENABLED (flip both together — the backend half is
 * boot-env, the frontend half is this const).
 */
export const BABEL_MATRIX_ENABLED = true;

/** n at which a cell reaches full colour intensity (below it, faded = thin). */
const CONFIDENCE_FULL_N = 12;
/** Floor so a 1-sample cell is still faintly visible, not invisible. */
const MIN_CELL_ALPHA = 0.16;

/** Confidence shading ∈ [MIN_CELL_ALPHA, 1] from the dyad's sample size. */
function confidence(total: number): number {
  if (total <= 0) return 0;
  return Math.max(MIN_CELL_ALPHA, Math.min(1, total / CONFIDENCE_FULL_N));
}

/** Data-driven cell colour: danger (0% cooperation) → acid (100%). Tokens only. */
function rateColor(rate: number): string {
  const pct = Math.round(Math.max(0, Math.min(1, rate)) * 100);
  return `color-mix(in srgb, var(--lab-acid) ${pct}%, var(--lab-danger))`;
}

/** Model → chip colour from the live legend (config-sourced), else a token. */
function modelColor(model: string, profiles: ModelProfile[]): string {
  const p = profiles.find((x) => x.name === model);
  return p?.color || 'var(--lab-muted)';
}

/** Index cells by "actor→target" for O(1) grid lookup. The `\x1f` (unit
 *  separator) ESCAPE keeps the key collision-proof against any printable
 *  model name — as an escape sequence, never a raw byte, which would make
 *  the file binary to git. */
function cellMap(cells: BabelCell[]): Map<string, BabelCell> {
  const m = new Map<string, BabelCell>();
  for (const c of cells) m.set(`${c.actor}\x1f${c.target}`, c);
  return m;
}

function pct(rate: number | null): string {
  return rate === null ? '—' : `${Math.round(rate * 100)}%`;
}

interface BabelMatrixProps {
  /** Run to analyse; null = the active run (omit run_id → backend default). */
  runId: number | null;
  /** Live legend, for config-sourced model-chip colours. */
  profiles: ModelProfile[];
}

export default function BabelMatrix({ runId, profiles }: BabelMatrixProps) {
  const [data, setData] = useState<BabelMatrixData | null>(null);
  const [loading, setLoading] = useState(true);
  const [family, setFamily] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ actor: string; target: string } | null>(null);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setSelected(null);
    inspectorApi
      .babelMatrix(runId ?? undefined, { family: family ?? undefined })
      .then((m) => {
        if (!live) return;
        setData(m);
        setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [runId, family]);

  const byCell = useMemo(() => cellMap(data?.cells ?? []), [data]);
  const models = data?.models ?? [];
  const familyTabs = useMemo(() => data?.families ?? [], [data]);

  const selectedCell = selected
    ? byCell.get(`${selected.actor}\x1f${selected.target}`) ?? null
    : null;

  // ── Empty / disabled / loading states (labeled, never a blank grid) ─────────
  if (loading && data === null) {
    return <Shell><Note>loading dyadic outcomes…</Note></Shell>;
  }
  if (data === null) {
    return (
      <Shell>
        <Note>
          The Babel Matrix is disabled or unreachable. Enable it with{' '}
          <code className="text-lab-acid">babel_matrix.enabled</code> (backend:{' '}
          <code className="text-lab-acid">PETRIDISH_BABEL_MATRIX_ENABLED=1</code>).
        </Note>
      </Shell>
    );
  }
  if (models.length === 0) {
    return (
      <Shell totals={data.totals}>
        <Note>
          No dyadic outcomes with known models on both ends yet. Mixed-model
          casts produce this data as agents trade and teach across model lines.
        </Note>
      </Shell>
    );
  }

  return (
    <Shell totals={data.totals} familyTabs={familyTabs} family={family} onFamily={setFamily}>
      <div className="flex-1 min-h-0 overflow-auto p-2">
        {/* The N×N grid. Corner label + column headers, then a row per actor. */}
        <div
          className="grid gap-px w-max"
          style={{ gridTemplateColumns: `auto repeat(${models.length}, minmax(2.75rem, 1fr))` }}
          role="table"
          aria-label="Dyadic model-vs-model outcome matrix"
        >
          <div
            className="font-mono text-[8px] text-lab-dim uppercase tracking-wide px-1 flex items-end justify-end"
            aria-hidden
          >
            actor ↓ / on →
          </div>
          {models.map((col) => (
            <div
              key={`h-${col}`}
              className="font-mono text-[9px] text-lab-muted text-center px-1 py-0.5 truncate"
              title={col}
              role="columnheader"
            >
              <span
                className="inline-block w-2 h-2 rounded-sm align-middle mr-0.5"
                style={{ background: modelColor(col, profiles) }}
                aria-hidden
              />
              {col}
            </div>
          ))}

          {models.map((row) => (
            <MatrixRow
              key={`r-${row}`}
              row={row}
              cols={models}
              byCell={byCell}
              profiles={profiles}
              selected={selected}
              onSelect={(actor, target) => setSelected({ actor, target })}
            />
          ))}
        </div>
      </div>

      {/* Receipts drawer — the click-through evidence for the selected dyad. */}
      {selectedCell && (
        <ReceiptsDrawer
          cell={selectedCell}
          profiles={profiles}
          onClose={() => setSelected(null)}
        />
      )}
    </Shell>
  );
}

// ── Row of cells ─────────────────────────────────────────────────────────────

function MatrixRow({
  row,
  cols,
  byCell,
  profiles,
  selected,
  onSelect,
}: {
  row: string;
  cols: string[];
  byCell: Map<string, BabelCell>;
  profiles: ModelProfile[];
  selected: { actor: string; target: string } | null;
  onSelect: (actor: string, target: string) => void;
}) {
  return (
    <>
      <div
        className="font-mono text-[9px] text-lab-muted text-right pr-1.5 flex items-center justify-end gap-1 truncate"
        title={row}
        role="rowheader"
      >
        <span
          className="inline-block w-2 h-2 rounded-sm shrink-0"
          style={{ background: modelColor(row, profiles) }}
          aria-hidden
        />
        <span className="truncate">{row}</span>
      </div>
      {cols.map((col) => {
        const cell = byCell.get(`${row}\x1f${col}`) ?? null;
        const isSel = selected?.actor === row && selected?.target === col;
        return (
          <MatrixCell
            key={`${row}-${col}`}
            row={row}
            col={col}
            cell={cell}
            selected={isSel}
            onSelect={onSelect}
          />
        );
      })}
    </>
  );
}

// ── One cell ─────────────────────────────────────────────────────────────────

function MatrixCell({
  row,
  col,
  cell,
  selected,
  onSelect,
}: {
  row: string;
  col: string;
  cell: BabelCell | null;
  selected: boolean;
  onSelect: (actor: string, target: string) => void;
}) {
  if (cell === null || cell.total === 0) {
    return (
      <div
        className="min-h-[2.25rem] bg-lab-surface/40 flex items-center justify-center font-mono text-[9px] text-lab-dim"
        role="cell"
        title={`${row} → ${col}: no outcomes`}
        aria-label={`${row} to ${col}: no outcomes`}
      >
        ·
      </div>
    );
  }
  const rate = cell.rate ?? 0;
  const ci =
    cell.ci_lo !== null && cell.ci_hi !== null
      ? ` · 95% CI ${pct(cell.ci_lo)}–${pct(cell.ci_hi)}`
      : '';
  const title = `${row} → ${col}: ${cell.positive}/${cell.total} positive (${pct(cell.rate)})${ci}`;
  return (
    <button
      type="button"
      role="cell"
      aria-pressed={selected}
      aria-label={title}
      title={title}
      onClick={() => onSelect(row, col)}
      className={`relative min-h-[2.25rem] flex flex-col items-center justify-center font-mono leading-none transition-shadow ${
        selected ? 'ring-2 ring-lab-text z-10' : 'hover:ring-1 hover:ring-lab-border-bright'
      }`}
      style={{ background: 'var(--lab-surface)' }}
    >
      {/* Data-driven colour wash; opacity encodes confidence (thin = faded). */}
      <span
        aria-hidden
        className="absolute inset-0"
        style={{ background: rateColor(rate), opacity: confidence(cell.total) }}
      />
      <span className="relative text-[11px] text-lab-text font-semibold tabular-nums drop-shadow">
        {pct(cell.rate)}
      </span>
      <span className="relative text-[8px] text-lab-text/80 tabular-nums">n={cell.total}</span>
    </button>
  );
}

// ── Receipts drawer ──────────────────────────────────────────────────────────

function ReceiptsDrawer({
  cell,
  profiles,
  onClose,
}: {
  cell: BabelCell;
  profiles: ModelProfile[];
  onClose: () => void;
}) {
  return (
    <div className="shrink-0 border-t border-lab-border max-h-[42%] flex flex-col min-h-0">
      <div className="lab-header flex items-center justify-between gap-2 !py-1 shrink-0">
        <span className="font-mono text-[10px] text-lab-muted uppercase tracking-wide flex items-center gap-1.5">
          <Chip label={cell.actor} color={modelColor(cell.actor, profiles)} />
          <span className="text-lab-dim">→</span>
          <Chip label={cell.target} color={modelColor(cell.target, profiles)} />
          <span className="text-lab-text ml-1">
            {cell.positive}/{cell.total} · {pct(cell.rate)}
          </span>
        </span>
        <button
          type="button"
          onClick={onClose}
          className="font-mono text-[10px] text-lab-dim hover:text-lab-text px-1"
          aria-label="close receipts"
        >
          ✕
        </button>
      </div>
      <ul className="flex-1 min-h-0 overflow-auto divide-y divide-lab-border/60">
        {cell.receipts.map((r) => (
          <ReceiptRow key={r.seq} receipt={r} />
        ))}
      </ul>
    </div>
  );
}

function ReceiptRow({ receipt }: { receipt: BabelReceipt }) {
  return (
    <li className="px-3 py-1 flex items-start gap-2">
      <span
        className={`font-mono text-[11px] shrink-0 mt-px ${
          receipt.positive ? 'text-lab-acid' : 'text-lab-danger'
        }`}
        aria-hidden
      >
        {receipt.positive ? '✓' : '✗'}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-mono text-[11px] text-lab-text leading-snug break-words">
          {receipt.text || receipt.kind}
        </p>
        <p className="font-mono text-[9px] text-lab-dim tabular-nums">
          tick {receipt.tick} · {receipt.kind}
          {receipt.routed_via ? ` · via ${receipt.routed_via}` : ''}
        </p>
      </div>
    </li>
  );
}

// ── Small shared bits ────────────────────────────────────────────────────────

function Chip({ label, color }: { label: string; color: string }) {
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[10px] text-lab-text normal-case">
      <span className="inline-block w-2 h-2 rounded-sm" style={{ background: color }} aria-hidden />
      {label}
    </span>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 min-h-[6rem] flex items-center justify-center p-4">
      <p className="font-mono text-[10px] text-lab-muted leading-relaxed max-w-prose text-center">
        {children}
      </p>
    </div>
  );
}

function Shell({
  children,
  totals,
  familyTabs,
  family,
  onFamily,
}: {
  children: React.ReactNode;
  totals?: BabelMatrixData['totals'];
  familyTabs?: string[];
  family?: string | null;
  onFamily?: (f: string | null) => void;
}) {
  return (
    <section
      className="lab-panel flex flex-col h-full min-h-0 overflow-hidden"
      aria-label="Babel Matrix — dyadic inter-model social physics (EM-314)"
    >
      <div className="lab-header flex items-center justify-between gap-2 !py-1 shrink-0">
        <span className="font-mono text-[11px] text-lab-text uppercase tracking-wide">
          Babel Matrix
          <span className="text-lab-dim normal-case tracking-normal ml-1">· dyadic model chemistry</span>
        </span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">EM-314</span>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1 border-b border-lab-border shrink-0">
        {totals && (
          <span className="font-mono text-[10px] text-lab-muted tabular-nums">
            <span className="text-lab-text">{totals.outcomes}</span> outcomes ·{' '}
            <span className="text-lab-text">{totals.positive}</span> positive ·{' '}
            <span className="text-lab-text">{totals.cells}</span> dyads
          </span>
        )}
        {familyTabs && familyTabs.length > 0 && onFamily && (
          <span className="flex items-center gap-1" role="group" aria-label="outcome family filter">
            <FamilyTab label="all" active={!family} onClick={() => onFamily(null)} />
            {familyTabs.map((f) => (
              <FamilyTab key={f} label={f} active={family === f} onClick={() => onFamily(f)} />
            ))}
          </span>
        )}
        <span className="font-mono text-[9px] text-lab-dim ml-auto">
          rate = positive ÷ total · faded = thin sample
        </span>
      </div>

      {children}
    </section>
  );
}

function FamilyTab({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`font-mono text-[9px] uppercase tracking-wide px-1.5 py-0.5 border ${
        active
          ? 'border-lab-acid text-lab-acid'
          : 'border-lab-border text-lab-muted hover:text-lab-text'
      }`}
    >
      {label}
    </button>
  );
}
