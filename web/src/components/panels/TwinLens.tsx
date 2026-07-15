/**
 * TwinLens (EM-310 / Chimera Twins) — the marquee "same persona, different
 * brain" surface. A LINKED pair (byte-identical persona / memory-seed /
 * starting state, differing ONLY in model, named Vesper / Vesper II) gets a
 * synchronized DUAL-STRAND thread of their answer streams side by side, plus
 * an auto-pinned DIVERGENCE-POINT card the first time the twins answer the same
 * class of situation differently — quoted both, with model chips.
 *
 * This is FEED-ONLY CHROME, entirely CLIENT-SIDE: it reads the additive `twin`
 * link the backend rides in every world_state broadcast + the event history it
 * already has, and derives the strands + divergence with pure functions. It
 * writes NOTHING back to the sim (off the replay surface — the standing law).
 *
 * NO TWIN PAIR RENDERS NOTHING — with no linked pair in the roster the panel
 * returns null, so the golden UI stays byte-identical (Chimera Twins ships
 * dormant behind world.chimera_twins.enabled; a pair only exists once the
 * gated twin-spawn endpoint mints one).
 *
 * Honest framing (the panel's own tooltip): twins share neighbors, economy, and
 * the weather of events, so a divergence is attributable to the weights — but
 * they still interact, so this is a natural experiment, NOT a clean RCT. The
 * "same class of situation" is approximated by ALIGNING each twin's answer
 * stream by index (their k-th answer), which holds because they start identical.
 *
 * Token-only styling; the collapse preference persists to localStorage.
 */

import { useEffect, useMemo, useState } from 'react';
import type { Agent, WorldEvent, WorldState } from '../../types';
import '../../inspector/inspector-tokens.css';

interface TwinLensProps {
  world: WorldState | null;
  history: WorldEvent[];
}

const COLLAPSE_KEY = 'em.twinlens.collapsed';
const MAX_STRAND_ROWS = 8;

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

/** A mutually-linked twin pair, `a` before `b` by a stable name/id order. */
export interface TwinPair {
  group: string;
  a: Agent;
  b: Agent;
}

/**
 * Find the first MUTUALLY-linked twin pair in the roster (a.twin.of === b.id
 * AND b.twin.of === a.id). A one-sided or dangling link is ignored (the peer
 * must point back). Deterministic: agents are scanned in a stable (name, id)
 * order and the earliest valid pair wins, so a re-render never reshuffles which
 * pair the lens shows. Returns null when no such pair exists.
 */
export function findTwinPair(agents: Agent[] | undefined): TwinPair | null {
  const list = [...(agents ?? [])].sort((x, y) =>
    x.name === y.name ? x.id.localeCompare(y.id) : x.name.localeCompare(y.name),
  );
  const byId = new Map(list.map((a) => [a.id, a]));
  const seen = new Set<string>();
  for (const a of list) {
    if (seen.has(a.id)) continue;
    const of = a.twin?.of;
    if (!of) continue;
    const b = byId.get(of);
    if (!b || b.twin?.of !== a.id) continue; // must point back
    seen.add(a.id);
    seen.add(b.id);
    return { group: a.twin?.group || b.twin?.group || a.name, a, b };
  }
  return null;
}

/** One "answer" a twin gave: its action verb + the feed line, in order. */
export interface TwinAction {
  tick: number;
  seq: number;
  verb: string;
  text: string;
}

/** The verb (answer CLASS) a feed event represents, or '' if it is not an
 *  answer we track. agent_action → payload.action; agent_speech → 'say'. */
function eventVerb(e: WorldEvent): string {
  if (e.kind === 'agent_speech') return 'say';
  if (e.kind === 'agent_action') {
    const a = e.payload?.action;
    return typeof a === 'string' && a ? a : 'act';
  }
  return '';
}

/**
 * Extract one agent's ordered ANSWER stream (its agent_action / agent_speech
 * events) from the shared history, oldest→newest by (tick, seq). Pure/total.
 */
export function twinActions(history: WorldEvent[], agentId: string): TwinAction[] {
  const out: TwinAction[] = [];
  for (const e of history) {
    if (e.actor_id !== agentId) continue;
    const verb = eventVerb(e);
    if (!verb) continue;
    out.push({ tick: e.tick, seq: e.seq, verb, text: e.text ?? '' });
  }
  out.sort((p, q) => (p.tick === q.tick ? p.seq - q.seq : p.tick - q.tick));
  return out;
}

/** The first divergence: the earliest index at which both twins have answered
 *  and their answer VERBS differ. Returns the aligned pair + its index, or null
 *  when the streams never peel apart within their shared length. */
export interface Divergence {
  index: number;
  a: TwinAction;
  b: TwinAction;
}

export function firstDivergence(
  aActions: TwinAction[],
  bActions: TwinAction[],
): Divergence | null {
  const n = Math.min(aActions.length, bActions.length);
  for (let i = 0; i < n; i++) {
    if (aActions[i].verb !== bActions[i].verb) {
      return { index: i, a: aActions[i], b: bActions[i] };
    }
  }
  return null;
}

/** A model chip: the twin's name + its profile, colored by profile_color. */
function ModelChip({ agent }: { agent: Agent }) {
  const color = agent.profile_color || 'var(--lab-acid, #9acd32)';
  return (
    <span
      className="inline-flex items-center gap-1 font-mono text-[10px] px-1 py-px border rounded-sm
                 whitespace-nowrap max-w-[10rem]"
      style={{ color, borderColor: color }}
      title={`${agent.name} — ${agent.profile}`}
    >
      <span className="truncate">{agent.name}</span>
      <span className="opacity-70 truncate">{agent.profile}</span>
    </span>
  );
}

/** One side of the divergence card: a twin's quoted diverging answer. */
function DivergenceSide({ agent, action }: { agent: Agent; action: TwinAction }) {
  return (
    <div className="flex-1 min-w-0">
      <ModelChip agent={agent} />
      <p className="m-0 mt-0.5 font-mono text-[10px] text-lab-text">
        <span className="text-lab-dim">{action.verb}</span>
        {action.text ? ` — ${action.text}` : ''}
      </p>
    </div>
  );
}

export function TwinLens({ world, history }: TwinLensProps) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
  }, [collapsed]);

  const pair = useMemo(() => findTwinPair(world?.agents), [world]);

  const aActions = useMemo(
    () => (pair ? twinActions(history, pair.a.id) : []),
    [history, pair],
  );
  const bActions = useMemo(
    () => (pair ? twinActions(history, pair.b.id) : []),
    [history, pair],
  );
  const divergence = useMemo(
    () => firstDivergence(aActions, bActions),
    [aActions, bActions],
  );

  // No linked pair ⇒ render nothing at all (golden-safe: zero chrome until a
  // twin pair is deliberately spawned behind the flag).
  if (!pair) return null;

  // ONE shared index window over both strands: row r shows answer #(start+r)
  // for BOTH twins, so the columns stay index-aligned when the streams have
  // drifted apart in length (a per-twin offset would pair different answer
  // indexes as if aligned and could tint the wrong row as the divergence).
  const maxLen = Math.max(aActions.length, bActions.length);
  const rows = Math.min(maxLen, MAX_STRAND_ROWS);
  const start = Math.max(0, maxLen - rows);

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label={`Twin lens — ${pair.group} across two models`}
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <h2
          className="m-0 font-mono text-xs font-semibold tracking-widest uppercase"
          title="Same persona, different brain — a within-one-city A/B (natural experiment, not a clean RCT)"
        >
          ⧉ TWIN · {pair.group}
        </h2>
        <div className="flex items-center gap-2">
          {divergence && (
            <span
              className="font-mono text-[10px] px-1 py-px border rounded-sm normal-case tracking-normal"
              style={{ color: 'var(--lab-acid, #9acd32)', borderColor: 'var(--lab-acid, #9acd32)' }}
              title="The twins peeled apart — see the divergence point"
            >
              diverged
            </span>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand the twin lens' : 'Collapse the twin lens'}
            title={collapsed ? 'Expand the twin lens' : 'Collapse the twin lens'}
            className="font-mono text-[10px] px-1.5 py-0.5 border border-lab-border text-lab-muted
                       hover:border-lab-acid hover:text-lab-acid rounded-sm cursor-pointer
                       transition-colors duration-100"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="max-h-64 overflow-y-auto">
          {/* Auto-pinned divergence-point card — the spectacle. */}
          {divergence && (
            <div
              className="px-3 py-2 border-b border-lab-border/60"
              style={{ borderLeft: '3px solid var(--lab-acid, #9acd32)' }}
              aria-label="Divergence point"
            >
              <p className="m-0 mb-1 font-mono text-[9px] uppercase tracking-wider text-lab-dim">
                ⚡ divergence point · answer #{divergence.index + 1} · tick {divergence.a.tick}/{divergence.b.tick}
              </p>
              <div className="flex gap-3">
                <DivergenceSide agent={pair.a} action={divergence.a} />
                <span className="self-center font-mono text-[10px] text-lab-dim" aria-hidden="true">vs</span>
                <DivergenceSide agent={pair.b} action={divergence.b} />
              </div>
            </div>
          )}

          {/* Column header — the two model chips over their strands. */}
          <div className="flex gap-2 px-3 py-1.5 border-b border-lab-border/40">
            <div className="flex-1 min-w-0"><ModelChip agent={pair.a} /></div>
            <div className="flex-1 min-w-0"><ModelChip agent={pair.b} /></div>
          </div>

          {/* Synchronized dual-strand thread — index-aligned answer rows. */}
          <ul className="m-0 p-0 list-none">
            {Array.from({ length: rows }).map((_, r) => {
              const i = start + r;
              const a = aActions[i];
              const b = bActions[i];
              // The shared index makes this exact: at divergence.index both
              // twins answered (firstDivergence only scans the shared length).
              const isDiverge = divergence != null && i === divergence.index;
              return (
                <li
                  key={r}
                  className="flex gap-2 px-3 py-1 border-b border-lab-border/20"
                  style={isDiverge ? { background: 'color-mix(in srgb, var(--lab-acid, #9acd32) 12%, transparent)' } : undefined}
                >
                  <TwinStrandCell action={a} />
                  <TwinStrandCell action={b} />
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}

/** One strand cell — a single answer line, or a muted placeholder when this
 *  twin has not yet answered at this aligned step. */
function TwinStrandCell({ action }: { action: TwinAction | undefined }) {
  if (!action) {
    return <div className="flex-1 min-w-0 font-mono text-[10px] text-lab-dim">·</div>;
  }
  return (
    <div className="flex-1 min-w-0 font-mono text-[10px] text-lab-muted truncate" title={action.text}>
      <span className="text-lab-dim">{action.verb}</span>
      {action.text ? ` — ${action.text}` : ''}
    </div>
  );
}
