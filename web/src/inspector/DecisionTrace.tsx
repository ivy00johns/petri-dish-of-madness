/**
 * DecisionTrace (EM-056) — "read the lab notebook".
 *
 * Make the model's thinking legible. A run's history is a stream of OTel-style
 * spans grouped by `turn_id` (event-log.md §3). One agent turn = one linked
 * chain, ordered:
 *
 *   turn_start → perceived → memory_retrieved → llm_call → reasoning →
 *   action_chosen → action_resolved   (+ any domain events the action caused)
 *
 * LEFT  — a list of recent turns (newest first), each a card colored by the
 *         acting agent's model profile, with its tick / agent / chosen tool /
 *         outcome. Click one to inspect it.
 * RIGHT — the selected turn unfolded as a vertical trace. Each span renders its
 *         kind-specific payload: the perceived summary + who was visible, the
 *         memory window used, the model + routed_via + tokens + latency + finish
 *         reason from the `llm_call` OTel keys, the reasoning text, the chosen
 *         tool + args, and the final outcome + state deltas — then the domain
 *         events the action caused, under the same turn.
 *
 * Data: `props.events` (the client-side rolling history) via the pure selectors
 * `turnIds()` / `turnTrace(events, turnId)`. Re-projects AT `props.currentTick`
 * (only turns whose head tick ≤ the scrub tick are shown) so the panel follows
 * the shared scrubber. No backend required; mock-safe.
 *
 * Token-only styling (lab-* classes / inspector tokens). The only inline style
 * is the data-driven profile color (an agent's model color from data), never a
 * hardcoded design literal — so design-token-guard stays clean. No `any`.
 */

import { useMemo, useState } from 'react';
import type { Agent } from '../types';
import type { PanelProps, TurnTrace, TraceSpan, TraceUsage } from './types';
import { turnIds, turnTrace } from './selectors';
import './inspector-tokens.css';

// The seven canonical chain kinds (event-log.md §3) — everything else in a
// turn's span list is a "domain event" the action caused.
const CHAIN_KINDS = new Set<string>([
  'turn_start',
  'perceived',
  'memory_retrieved',
  'llm_call',
  'reasoning',
  'action_chosen',
  'action_resolved',
]);

// A short, readable label per chain kind for the trace rail.
const KIND_LABEL: Record<string, string> = {
  turn_start: 'turn start',
  perceived: 'perceived',
  memory_retrieved: 'memory',
  llm_call: 'llm call',
  reasoning: 'reasoning',
  action_chosen: 'action chosen',
  action_resolved: 'resolved',
};

// Outcome → a lab-token classname for the badge (no hardcoded colors).
const OUTCOME_CLASS: Record<NonNullable<TurnTrace['outcome']>, string> = {
  ok: 'border-lab-acid text-lab-acid bg-lab-acid/10',
  gated: 'border-lab-warn text-lab-warn bg-lab-warn/10',
  failed: 'border-lab-danger text-lab-danger bg-lab-danger/10',
};

export default function DecisionTrace({ events, agents, profiles, currentTick, historyLoading }: PanelProps) {
  // Agent id → display name (the trace shows names, not raw ids).
  const agentName = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of agents) m.set(a.id, a.name);
    return m;
  }, [agents]);

  // Profile name → its model color (so a turn whose llm_call profile differs
  // from the live agent's still color-codes by the model that actually ran).
  const profileColor = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of agents) if (a.profile && a.profile_color) m.set(a.profile, a.profile_color);
    for (const p of profiles) if (p.name && p.color) m.set(p.name, p.color);
    return m;
  }, [agents, profiles]);

  // Recent turns up to the scrub tick (newest first). Re-projecting here keeps
  // the panel in lockstep with the shared scrubber (scrub back → fewer turns).
  const turns = useMemo(
    () => turnIds(events).filter((t) => t.tick <= currentTick),
    [events, currentTick],
  );

  // Selected turn — default to the newest visible one; if the selection scrolls
  // out of the projected window, fall back to the newest still-visible turn.
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const activeId = useMemo(() => {
    if (selectedId && turns.some((t) => t.turnId === selectedId)) return selectedId;
    return turns[0]?.turnId ?? null;
  }, [selectedId, turns]);

  const trace = useMemo(
    () => (activeId ? turnTrace(events, activeId) : null),
    [events, activeId],
  );

  return (
    <section className="lab-panel flex flex-col h-full min-h-[24rem]" aria-label="Decision trace (EM-056)">
      <div className="lab-header flex items-center justify-between gap-2">
        <span>Decision Trace</span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">EM-056</span>
      </div>

      {turns.length === 0 ? (
        historyLoading === true && events.length === 0 ? (
          <EmptyState
            title="History loading…"
            detail="Backfilling the run from the event log — recent turns appear as pages arrive."
          />
        ) : (
          <EmptyState
            title="No turns at this tick"
            detail="Each agent turn emits a linked span chain (perceived → llm_call → reasoning → action). Scrub forward, or wait for the run to advance."
          />
        )
      ) : (
        <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-[minmax(0,11rem)_minmax(0,1fr)]">
          {/* ── LEFT: recent-turn list ─────────────────────────────────────── */}
          <ul
            className="min-h-0 md:max-h-none max-h-40 overflow-y-auto border-b md:border-b-0 md:border-r border-lab-border divide-y divide-lab-border"
            aria-label="Recent turns"
          >
            {turns.slice(0, 80).map((t) => {
              const color =
                (t.agentId && profileColorForAgent(agents, t.agentId, profileColor)) || '';
              return (
                <li key={t.turnId}>
                  <TurnRow
                    active={t.turnId === activeId}
                    tick={t.tick}
                    name={(t.agentId && agentName.get(t.agentId)) || t.agentId || 'unknown'}
                    color={color}
                    onSelect={() => setSelectedId(t.turnId)}
                  />
                </li>
              );
            })}
          </ul>

          {/* ── RIGHT: the unfolded trace for the selected turn ─────────────── */}
          <div className="min-h-0 overflow-y-auto p-3">
            {trace ? (
              <TraceDetail
                trace={trace}
                accent={
                  (trace.profile && profileColor.get(trace.profile)) ||
                  (trace.agentId && profileColorForAgent(agents, trace.agentId, profileColor)) ||
                  ''
                }
                agentName={
                  (trace.agentId && agentName.get(trace.agentId)) || trace.agentId || 'unknown'
                }
              />
            ) : (
              <EmptyState title="Select a turn" detail="Pick a turn on the left to read its decision chain." />
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/** Resolve an agent's model color from its live profile (data-driven). */
function profileColorForAgent(
  agents: Agent[],
  agentId: string,
  profileColor: Map<string, string>,
): string {
  const a = agents.find((x) => x.id === agentId);
  if (!a) return '';
  return a.profile_color ?? (a.profile ? profileColor.get(a.profile) ?? '' : '');
}

// ── Left-rail row ──────────────────────────────────────────────────────────

function TurnRow({
  active,
  tick,
  name,
  color,
  onSelect,
}: {
  active: boolean;
  tick: number;
  name: string;
  color: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={
        'w-full text-left px-2.5 py-2 flex items-center gap-2 transition-colors ' +
        (active ? 'bg-lab-acid/10' : 'hover:bg-lab-chrome')
      }
    >
      {/* Profile color chip (data-driven; neutral token when unknown). */}
      <i
        className="inline-block w-1.5 h-6 rounded-sm shrink-0"
        style={{ backgroundColor: color || 'var(--inspector-node-neutral)' }}
        aria-hidden="true"
      />
      <span className="flex flex-col min-w-0">
        <span
          className={
            'font-mono text-[11px] truncate ' + (active ? 'text-lab-acid' : 'text-lab-text')
          }
        >
          {name}
        </span>
        <span className="font-mono text-[9px] text-lab-dim tabular-nums">tick {tick}</span>
      </span>
    </button>
  );
}

// ── Right-panel trace detail ─────────────────────────────────────────────────

function TraceDetail({
  trace,
  accent,
  agentName,
}: {
  trace: TurnTrace;
  accent: string;
  agentName: string;
}) {
  const accentColor = accent || 'var(--inspector-node-neutral)';
  return (
    <div className="flex flex-col gap-3">
      {/* Turn header: agent + tick + chosen tool + outcome, accented by model. */}
      <div
        className="flex flex-wrap items-center gap-2 border-l-2 pl-2.5"
        style={{ borderColor: accentColor }}
      >
        <span className="font-mono text-xs font-bold text-lab-text">{agentName}</span>
        <span className="font-mono text-[10px] text-lab-dim tabular-nums">tick {trace.tick}</span>
        {trace.chosenTool && (
          <span className="font-mono text-[10px] px-1.5 py-0.5 border border-lab-border text-lab-muted">
            {trace.chosenTool}
          </span>
        )}
        {trace.outcome && (
          <span
            className={
              'font-mono text-[10px] font-bold px-1.5 py-0.5 border uppercase tracking-wide ' +
              OUTCOME_CLASS[trace.outcome]
            }
          >
            {trace.outcome}
          </span>
        )}
        <span className="ml-auto font-mono text-[9px] text-lab-dim truncate max-w-[10rem]" title={trace.turnId}>
          {trace.turnId.slice(0, 8)}
        </span>
      </div>

      {/* Vertical trace: one span per row, accent spine on the left. */}
      <ol className="flex flex-col gap-1.5" aria-label="Span chain">
        {trace.spans.map((span) => (
          <SpanRow key={`${span.seq}-${span.kind}`} span={span} usage={trace.usage} accent={accentColor} />
        ))}
      </ol>

      {/* State deltas (the resolution's effect on the agent). */}
      {Object.keys(trace.stateDeltas).length > 0 && (
        <div className="flex flex-col gap-1 border-t border-lab-border pt-2">
          <span className="font-mono text-[9px] uppercase tracking-widest text-lab-dim">state deltas</span>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(trace.stateDeltas).map(([k, v]) => (
              <DeltaChip key={k} label={k} value={v} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// One span in the vertical trace. Chain kinds get a bespoke body; domain events
// (the action's consequences) render with the generic feed line.
function SpanRow({ span, usage, accent }: { span: TraceSpan; usage: TraceUsage | null; accent: string }) {
  const isChain = CHAIN_KINDS.has(span.kind);
  const label = KIND_LABEL[span.kind] ?? span.kind;
  return (
    <li className="flex gap-2">
      {/* Spine + node marker. */}
      <span className="flex flex-col items-center shrink-0 pt-1">
        <i
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: isChain ? accent : 'var(--inspector-node-neutral)' }}
          aria-hidden="true"
        />
        <i className="w-px flex-1 bg-lab-border mt-0.5" aria-hidden="true" />
      </span>

      <div className="flex-1 min-w-0 pb-1">
        <div className="flex items-center gap-2">
          <span
            className={
              'font-mono text-[9px] uppercase tracking-widest ' +
              (isChain ? 'text-lab-muted' : 'text-lab-dim')
            }
          >
            {label}
          </span>
          {!isChain && (
            <span className="font-mono text-[8px] px-1 py-px border border-lab-border text-lab-dim uppercase">
              caused
            </span>
          )}
          <span className="ml-auto font-mono text-[9px] text-lab-dim tabular-nums">#{span.seq}</span>
        </div>
        <SpanBody span={span} usage={usage} />
      </div>
    </li>
  );
}

function SpanBody({ span, usage }: { span: TraceSpan; usage: TraceUsage | null }) {
  switch (span.kind) {
    case 'turn_start':
      return <TurnStartBody payload={span.payload} text={span.text} />;
    case 'perceived':
      return <PerceivedBody payload={span.payload} text={span.text} />;
    case 'memory_retrieved':
      return <MemoryBody payload={span.payload} text={span.text} />;
    case 'llm_call':
      return <LlmCallBody usage={usage} text={span.text} />;
    case 'reasoning':
      return <ReasoningBody payload={span.payload} text={span.text} />;
    case 'action_chosen':
      return <ActionChosenBody payload={span.payload} />;
    case 'action_resolved':
      return <ActionResolvedBody text={span.text} />;
    default:
      // Domain event — the generic feed line is enough.
      return <p className="font-mono text-[11px] text-lab-text leading-snug">{span.text ?? span.kind}</p>;
  }
}

// ── per-kind span bodies ─────────────────────────────────────────────────────

function TurnStartBody({ payload, text }: { payload: Record<string, unknown>; text: string | null }) {
  const energy = numOf(payload['energy']);
  const credits = numOf(payload['credits']);
  const location = strOf(payload['location']);
  return (
    <div className="flex flex-col gap-0.5">
      {text && <p className="font-mono text-[11px] text-lab-muted leading-snug">{text}</p>}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] text-lab-dim tabular-nums">
        {location && <span>@ {location}</span>}
        {energy !== null && <span>energy {energy}</span>}
        {credits !== null && <span>credits {credits}</span>}
      </div>
    </div>
  );
}

function PerceivedBody({ payload, text }: { payload: Record<string, unknown>; text: string | null }) {
  const summary = strOf(payload['perceived_summary']);
  const visible = strArrOf(payload['visible_agents']);
  return (
    <div className="flex flex-col gap-0.5">
      <p className="font-mono text-[11px] text-lab-text leading-snug">{summary ?? text ?? '—'}</p>
      {visible.length > 0 && (
        <span className="font-mono text-[10px] text-lab-dim">
          sees {visible.length}: {visible.join(', ')}
        </span>
      )}
    </div>
  );
}

interface MemoryItem {
  ref?: string;
  tick?: number;
  kind?: string;
  text?: string;
}

function MemoryBody({ payload, text }: { payload: Record<string, unknown>; text: string | null }) {
  const memories = memoryItems(payload['memories']);
  if (memories.length === 0) {
    return <p className="font-mono text-[11px] text-lab-dim leading-snug">{text ?? 'no memories retrieved'}</p>;
  }
  return (
    <ul className="flex flex-col gap-0.5 mt-0.5">
      {memories.slice(0, 5).map((m, i) => (
        <li key={m.ref ?? i} className="font-mono text-[10px] text-lab-muted leading-snug flex gap-1.5">
          <span className="text-lab-dim tabular-nums shrink-0">
            {m.kind ?? 'mem'}
            {m.tick !== undefined ? ` @${m.tick}` : ''}
          </span>
          <span className="text-lab-text truncate">{m.text ?? m.ref ?? '—'}</span>
        </li>
      ))}
    </ul>
  );
}

function LlmCallBody({ usage, text }: { usage: TraceUsage | null; text: string | null }) {
  if (!usage) {
    return <p className="font-mono text-[11px] text-lab-dim leading-snug">{text ?? 'model call (no usage captured)'}</p>;
  }
  const model = usage.requestModel ?? '—';
  const routed = usage.responseModel;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[11px] text-lab-text">{model}</span>
        {routed && routed !== model && (
          <span className="font-mono text-[10px] text-lab-dim">→ {routed}</span>
        )}
        {usage.cached && (
          <span className="font-mono text-[9px] px-1 py-px border border-lab-acid text-lab-acid bg-lab-acid/10 uppercase">
            cached
          </span>
        )}
        {usage.attempt !== null && usage.attempt > 1 && (
          <span className="font-mono text-[9px] px-1 py-px border border-lab-warn text-lab-warn bg-lab-warn/10 uppercase">
            retry #{usage.attempt}
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[10px] text-lab-dim tabular-nums">
        <span>in {fmtTokens(usage.inputTokens)}</span>
        <span>out {fmtTokens(usage.outputTokens)}</span>
        <span>{usage.latencyMs !== null ? `${usage.latencyMs} ms` : 'latency —'}</span>
        {usage.finishReasons && usage.finishReasons.length > 0 && (
          <span>finish: {usage.finishReasons.join(', ')}</span>
        )}
      </div>
    </div>
  );
}

function ReasoningBody({ payload, text }: { payload: Record<string, unknown>; text: string | null }) {
  const reasoning = strOf(payload['reasoning']) ?? text;
  const memoriesUsed = strArrOf(payload['memories_used']);
  if (!reasoning) {
    return <p className="font-mono text-[11px] text-lab-dim leading-snug italic">no reasoning emitted (reflex / fallback turn)</p>;
  }
  return (
    <div className="flex flex-col gap-0.5">
      <p className="font-mono text-[11px] text-lab-text leading-snug italic border-l border-lab-border-bright pl-2">
        “{reasoning}”
      </p>
      {memoriesUsed.length > 0 && (
        <span className="font-mono text-[9px] text-lab-dim">drew on {memoriesUsed.length} memor{memoriesUsed.length === 1 ? 'y' : 'ies'}</span>
      )}
    </div>
  );
}

function ActionChosenBody({ payload }: { payload: Record<string, unknown> }) {
  const tool = strOf(payload['chosen_tool']);
  const tier = strOf(payload['tier']);
  const args = payload['args'];
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[11px] text-lab-acid">{tool ?? '—'}</span>
        {tier && (
          <span className="font-mono text-[9px] px-1 py-px border border-lab-border text-lab-dim uppercase">{tier}</span>
        )}
      </div>
      {isNonEmptyObject(args) && (
        <code className="font-mono text-[10px] text-lab-muted break-all">{fmtArgs(args)}</code>
      )}
    </div>
  );
}

function ActionResolvedBody({ text }: { text: string | null }) {
  // The outcome badge + state deltas render in the turn header / footer; here we
  // just show the human-readable resolution line (deltas summarized below).
  return <p className="font-mono text-[11px] text-lab-muted leading-snug">{text ?? 'turn resolved'}</p>;
}

// ── small UI bits ────────────────────────────────────────────────────────────

function DeltaChip({ label, value }: { label: string; value: number }) {
  const sign = value > 0 ? '+' : '';
  const tone =
    value > 0 ? 'border-lab-acid text-lab-acid' : value < 0 ? 'border-lab-danger text-lab-danger' : 'border-lab-border text-lab-muted';
  return (
    <span className={'font-mono text-[10px] tabular-nums px-1.5 py-0.5 border ' + tone}>
      {label} {sign}
      {value}
    </span>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-1.5 px-4 py-8 text-center">
      <span className="font-mono text-[11px] uppercase tracking-widest text-lab-muted">{title}</span>
      <p className="font-mono text-[10px] text-lab-dim leading-relaxed max-w-prose">{detail}</p>
    </div>
  );
}

// ── payload-read helpers (open payloads → typed reads, null-safe, no any) ─────

function numOf(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function strOf(v: unknown): string | null {
  return typeof v === 'string' && v.length > 0 ? v : null;
}

function strArrOf(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

function memoryItems(v: unknown): MemoryItem[] {
  if (!Array.isArray(v)) return [];
  return v.map((raw): MemoryItem => {
    const o = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
    return {
      ref: strOf(o['ref']) ?? undefined,
      tick: numOf(o['tick']) ?? undefined,
      kind: strOf(o['kind']) ?? undefined,
      text: strOf(o['text']) ?? undefined,
    };
  });
}

function isNonEmptyObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v as object).length > 0;
}

function fmtArgs(args: Record<string, unknown>): string {
  try {
    return JSON.stringify(args);
  } catch {
    return String(args);
  }
}

function fmtTokens(n: number | null): string {
  if (n === null) return '—';
  return n.toLocaleString();
}
