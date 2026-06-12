/**
 * SocialGraph (EM-058) — the relationship web, made legible.
 *
 * A force-directed graph (`react-force-graph-2d`) of the population AS OF the
 * shared scrub tick: nodes = agents (colored by their model profile), edges =
 * relationships (ally / friend / rival / enemy / neutral). Edge THICKNESS reads
 * |trust| and the edge is TINTED by the sign of trust (positive → acid, negative
 * → danger, flat → muted), so you can read who-trusts-whom at a glance.
 *
 * Data source = `props.events` (+ `props.agents`) via the pure selector
 * `socialGraph(events, agents, atTick)` → SocialGraphData { nodes, edges }. It
 * re-projects at `props.currentTick`: scrub the replay and the web rewinds with
 * it (the same shared tick every inspector panel follows). No backend required.
 *
 * Battery: the force sim is FROZEN once the layout settles — a bounded
 * `cooldownTicks` + a brisk `d3AlphaDecay`, and `onEngineStop` pauses the render
 * loop so an idle graph costs zero frames. Hover or click a node to spotlight
 * its ties (everything else dims). 0–1 nodes degrade to a labeled empty state,
 * never a blank canvas or a crash.
 *
 * Token-only: the canvas needs real color strings (a `<canvas>` can't take a
 * Tailwind class), so — exactly like ReplayScrubber — colors are read off the
 * declared `--lab-*` / `--inspector-*` CSS custom properties via getComputedStyle.
 * Node colors come from the data (the agent's model color). EM-196: every read
 * carries a literal fallback mirroring the declared token value, because the
 * canvas can't trust an unresolved var (see `resolveTokens`).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import type { ForceGraphMethods, NodeObject, LinkObject } from 'react-force-graph-2d';
import type { PanelProps } from './types';
import type { SocialNode, SocialEdge } from './types';
import { socialGraph } from './selectors';
import './inspector-tokens.css';
// Wave E: the --rel-* relationship registers (incl. partner/family/mentor/feud)
// live in the roster token sheet — the graph edges read the SAME tokens the
// roster chips wear, so a partner tie is one color everywhere.
import '../components/panels/roster-tokens.css';

// ── graph element shapes (our SocialNode/SocialEdge carried on the lib's bag) ──

type GraphNode = NodeObject<SocialNode>;
type GraphLink = LinkObject<SocialNode, SocialEdge>;

// Relationship types, for the legend + the dim/spotlight readout. Wave E:
// the four new types carry their OWN token swatch (type-keyed edge tint);
// the original five keep the trust-sign tone the edges fall back to.
const REL_LEGEND: Array<{ key: string; label: string; swatch: string }> = [
  { key: 'ally', label: 'ally', swatch: 'var(--lab-acid)' },
  { key: 'friend', label: 'friend', swatch: 'var(--lab-acid)' },
  { key: 'neutral', label: 'neutral', swatch: 'var(--lab-muted)' },
  { key: 'rival', label: 'rival', swatch: 'var(--marker-crime)' },
  { key: 'enemy', label: 'enemy', swatch: 'var(--marker-crime)' },
  { key: 'partner', label: 'partner', swatch: 'var(--rel-partner)' },
  { key: 'family', label: 'family', swatch: 'var(--rel-family)' },
  { key: 'mentor', label: 'mentor', swatch: 'var(--rel-mentor)' },
  { key: 'feud', label: 'feud', swatch: 'var(--rel-feud)' },
];

const COOLDOWN_TICKS = 120; // bounded settle, then the sim freezes (battery).
const NODE_REL_SIZE = 5;

export default function SocialGraph(props: PanelProps) {
  const { events, agents, currentTick, historyLoading } = props;

  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<ForceGraphMethods<GraphNode, GraphLink>>();
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const [settled, setSettled] = useState(false);

  // Theme tokens for the canvas (resolved once on mount; re-resolves on remount).
  const tokens = useResolvedTokens();

  // ── data: the relationship web AS OF the scrub tick ────────────────────────
  const projection = useMemo(
    () => socialGraph(events, agents, currentTick),
    [events, agents, currentTick],
  );

  // Adjacency for the spotlight (a node's direct ties). Built from edge ids.
  const neighbors = useMemo(() => {
    const map = new Map<string, Set<string>>();
    const link = (a: string, b: string) => {
      (map.get(a) ?? map.set(a, new Set()).get(a)!).add(b);
    };
    for (const e of projection.edges) {
      link(e.source, e.target);
      link(e.target, e.source);
    }
    return map;
  }, [projection.edges]);

  // The graph payload the library wants: { nodes, links }. We keep node objects
  // STABLE across re-projections (same tick window) so the layout doesn't jump —
  // positions persist; only edges/colors update as you scrub.
  const nodeCacheRef = useRef(new Map<string, GraphNode>());
  const graphData = useMemo(() => {
    const cache = nodeCacheRef.current;
    const liveIds = new Set(projection.nodes.map((n) => n.id));
    for (const id of [...cache.keys()]) if (!liveIds.has(id)) cache.delete(id);
    const nodes = projection.nodes.map((n) => {
      const prev = cache.get(n.id);
      if (prev) {
        // Refresh display fields; keep x/y/vx/vy so layout is sticky.
        prev.label = n.label;
        prev.color = n.color;
        prev.alive = n.alive;
        prev.factionId = n.factionId;
        prev.factionName = n.factionName;
        return prev;
      }
      const fresh: GraphNode = { ...n };
      cache.set(n.id, fresh);
      return fresh;
    });
    const links: GraphLink[] = projection.edges.map((e) => ({ ...e }));
    return { nodes, links };
  }, [projection]);

  // Reheat + re-freeze whenever the population (node set) changes — scrubbing
  // within the same set keeps the frozen layout, but a new node needs a settle.
  const nodeSignature = useMemo(
    () => projection.nodes.map((n) => n.id).sort().join(','),
    [projection.nodes],
  );
  useEffect(() => {
    setSettled(false);
    const fg = fgRef.current;
    if (fg) fg.d3ReheatSimulation();
  }, [nodeSignature]);

  // ── responsive sizing (the lib needs explicit px width/height) ─────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const obs = new ResizeObserver(measure);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const nodeCount = projection.nodes.length;
  const edgeCount = projection.edges.length;
  const aliveCount = projection.nodes.filter((n) => n.alive).length;
  const ready = size.w > 0 && size.h > 0 && nodeCount >= 2;

  // Pause the render loop when the graph unmounts (leak-free, like the annex
  // demands). EM-097 / W10-QA-1: reading `fgRef.current` inside an unmount
  // cleanup was DEAD CODE — React 18 detaches forwarded refs (the
  // useImperativeHandle handle is nulled) in the commit mutation phase,
  // BEFORE passive effect cleanups run, so the read always saw null. And the
  // old C5 capture-at-mount was equally dead: with `[]` deps the effect ran
  // while `ready` was still false (the graph wasn't rendered yet), so it
  // captured undefined. The fix is a CAPTURED-INSTANCE cleanup keyed on
  // `ready`: when `ready` flips true the graph mounts in the same commit and
  // its ref is attached before passive effects fire, so the capture is real —
  // and the closure-held instance survives React's ref detach, so the
  // teardown call actually runs (at route unmount AND whenever `ready` drops).
  useEffect(() => {
    if (!ready) return;
    const fg = fgRef.current;
    return () => {
      // Braced: pauseAnimation() returns the chainable instance, which a
      // cleanup must not return.
      fg?.pauseAnimation();
    };
  }, [ready]);

  // ── interaction: spotlight a node's ties ───────────────────────────────────
  const activeId = pinnedId ?? hoverId;
  const isDimmed = useCallback(
    (nodeId: string): boolean => {
      if (!activeId) return false;
      if (nodeId === activeId) return false;
      return !(neighbors.get(activeId)?.has(nodeId) ?? false);
    },
    [activeId, neighbors],
  );
  const linkActive = useCallback(
    (l: GraphLink): boolean => {
      if (!activeId) return false;
      const s = endpointId(l.source);
      const t = endpointId(l.target);
      return s === activeId || t === activeId;
    },
    [activeId],
  );

  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      const id = String(node.id);
      setPinnedId((cur) => (cur === id ? null : id));
      const fg = fgRef.current;
      if (fg && typeof node.x === 'number' && typeof node.y === 'number') {
        fg.centerAt(node.x, node.y, 400);
      }
    },
    [],
  );

  // ── canvas paint: node dot + label, dim-aware, alive/dead aware ────────────
  const paintNode = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const id = String(node.id);
      const dim = isDimmed(id);
      const baseColor = node.color || tokens.nodeNeutral;
      const r = NODE_REL_SIZE;
      ctx.save();
      ctx.globalAlpha = dim ? 0.18 : node.alive ? 1 : 0.4;

      // Wave E (EM-120): faction membership reads as a soft per-node ring in
      // the shared --faction-tint (the hull-tint fallback the contract allows:
      // a convex-hull canvas pass would redraw geometry on a layout the
      // battery design FREEZES — the ring is per-node, cheap, and stable).
      if (node.factionId && node.alive) {
        ctx.beginPath();
        ctx.arc(node.x ?? 0, node.y ?? 0, r + 2, 0, Math.PI * 2);
        ctx.lineWidth = 2 / scale;
        ctx.strokeStyle = withAlpha(tokens.faction, dim ? 0.15 : 0.5);
        ctx.stroke();
      }

      // Spotlight ring on the active node.
      if (id === activeId) {
        ctx.beginPath();
        ctx.arc(node.x ?? 0, node.y ?? 0, r + 3, 0, Math.PI * 2);
        ctx.lineWidth = 1.5 / scale;
        ctx.strokeStyle = tokens.acid;
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, Math.PI * 2);
      ctx.fillStyle = baseColor;
      ctx.fill();
      // Dead agents read as hollow rings, not filled dots.
      if (!node.alive) {
        ctx.lineWidth = 1 / scale;
        ctx.strokeStyle = tokens.dim;
        ctx.stroke();
      }

      // Label only when the graph is zoomed-in enough or the node is spotlit
      // (keeps a dense web from turning into a wall of text).
      if (!dim && (scale > 1.4 || id === activeId)) {
        const fontSize = Math.max(8, 11 / scale);
        ctx.font = `${fontSize}px "IBM Plex Mono", monospace`;
        ctx.fillStyle = tokens.text;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(node.label ?? id, node.x ?? 0, (node.y ?? 0) + r + 1.5);
      }
      ctx.restore();
    },
    [isDimmed, activeId, tokens],
  );

  // Pointer hit-area paint (so the dot, not just the line, is clickable).
  const paintNodePointer = useCallback(
    (node: GraphNode, color: string, ctx: CanvasRenderingContext2D) => {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, NODE_REL_SIZE + 2, 0, Math.PI * 2);
      ctx.fill();
    },
    [],
  );

  // Edge color: keyed by relationship TYPE for the Wave-E bonds (partner /
  // family warm-distinct, mentor sky, feud darker than enemy — token vars);
  // everything else keeps the trust-sign tint. Spotlight-aware.
  const linkColor = useCallback(
    (l: GraphLink): string => {
      const trust = typeof l.trust === 'number' ? l.trust : 0;
      const typed =
        typeof l.type === 'string' ? typeEdgeColor(l.type, tokens) : null;
      const base =
        typed ?? (trust > 4 ? tokens.acid : trust < -4 ? tokens.danger : tokens.edgeFlat);
      if (!activeId) return withAlpha(base, 0.55);
      return linkActive(l) ? withAlpha(base, 0.95) : withAlpha(base, 0.08);
    },
    [activeId, linkActive, tokens],
  );

  // Edge thickness ~ |trust| (1..4 px-ish in graph units).
  const linkWidth = useCallback(
    (l: GraphLink): number => {
      const mag = Math.abs(typeof l.trust === 'number' ? l.trust : 0);
      const base = 0.6 + (mag / 100) * 3.4;
      return activeId && linkActive(l) ? base + 1 : base;
    },
    [activeId, linkActive],
  );

  const onEngineStop = useCallback(() => {
    setSettled(true);
    fgRef.current?.zoomToFit(400, 24);
  }, []);

  return (
    <section className="lab-panel flex flex-col h-full min-h-[16rem]" aria-label="Social graph (EM-058)">
      <div className="lab-header flex items-center justify-between gap-2">
        <span>Social Graph</span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">EM-058</span>
      </div>

      {/* Readout strip: population + the relationship-type legend. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 border-b border-lab-border">
        <span className="font-mono text-[10px] text-lab-muted tabular-nums">
          <span className="text-lab-text">{aliveCount}</span>
          <span className="text-lab-dim">/{nodeCount}</span> agents ·{' '}
          <span className="text-lab-text">{edgeCount}</span> ties · tick{' '}
          <span className="text-lab-acid">{String(currentTick).padStart(4, '0')}</span>
        </span>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 ml-auto">
          {REL_LEGEND.map((r) => (
            <span key={r.key} className="flex items-center gap-1">
              <i
                className="inline-block w-3 h-0.5 rounded-full"
                style={{ backgroundColor: r.swatch }}
                aria-hidden="true"
              />
              <span className="font-mono text-[9px] text-lab-muted uppercase tracking-wide">{r.label}</span>
            </span>
          ))}
        </div>
      </div>

      {/* The graph surface (or an empty-but-labeled state). */}
      <div ref={containerRef} className="relative flex-1 min-h-[12rem] bg-lab-bg overflow-hidden">
        {ready ? (
          <ForceGraph2D<SocialNode, SocialEdge>
            // EM-196: force a CLEAN kapsule mount on every ready transition.
            // react-kapsule's useEffectOnce skips re-init on StrictMode's
            // double-mount, which can leave a stale DETACHED canvas (broken
            // -image artifact + dead rAF loop). Keying on `ready` makes React
            // discard the old fiber + DOM and mount fresh.
            key={String(ready)}
            ref={fgRef}
            width={size.w}
            height={size.h}
            graphData={graphData}
            backgroundColor={tokens.bg}
            nodeRelSize={NODE_REL_SIZE}
            nodeId="id"
            nodeLabel={(n) => nodeTooltip(n as GraphNode, projection.edges)}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={paintNodePointer}
            linkColor={linkColor}
            linkWidth={linkWidth}
            linkLabel={(l) => edgeTooltip(l as GraphLink)}
            linkDirectionalParticles={0}
            cooldownTicks={settled ? 0 : COOLDOWN_TICKS}
            d3AlphaDecay={0.045}
            d3VelocityDecay={0.35}
            warmupTicks={20}
            onEngineStop={onEngineStop}
            onNodeHover={(n) => setHoverId(n ? String(n.id) : null)}
            onNodeClick={handleNodeClick}
            onBackgroundClick={() => setPinnedId(null)}
            enableNodeDrag
            enableZoomInteraction
            enablePanInteraction
          />
        ) : (
          <EmptyState nodeCount={nodeCount} sized={size.w > 0} loading={historyLoading === true} />
        )}

        {/* A subtle "frozen" affordance once the sim settles (battery proof). */}
        {ready && settled && (
          <span className="absolute bottom-1.5 right-2 font-mono text-[9px] text-lab-dim uppercase tracking-widest pointer-events-none">
            layout frozen
          </span>
        )}
        {/* Spotlight hint when a node is pinned. */}
        {ready && pinnedId && (
          <span className="absolute top-1.5 left-2 font-mono text-[9px] text-lab-acid uppercase tracking-widest pointer-events-none">
            {pinnedId} · {neighbors.get(pinnedId)?.size ?? 0} ties · click bg to clear
          </span>
        )}
      </div>
    </section>
  );
}

// ── empty / degenerate states (0–1 nodes, or not yet measured) ────────────────

function EmptyState({
  nodeCount,
  sized,
  loading,
}: {
  nodeCount: number;
  sized: boolean;
  loading: boolean;
}) {
  const msg = !sized
    ? 'sizing…'
    : loading && nodeCount === 0
      ? 'history loading…'
      : nodeCount === 0
        ? 'no agents in this run yet'
        : 'one lone agent — no relationships to graph';
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 text-center">
      <span className="font-mono text-[11px] uppercase tracking-widest text-lab-muted border border-lab-border px-2 py-0.5">
        {msg}
      </span>
      {sized && nodeCount <= 1 && !loading && (
        <p className="font-mono text-[10px] text-lab-muted leading-relaxed max-w-prose">
          The social web fills in as agents form ties — allies, rivals, gifts and conflicts.
          Scrub forward, or wait for the run to populate.
        </p>
      )}
    </div>
  );
}

// ── tooltips (HTML strings; the lib renders them as native titles) ────────────

function nodeTooltip(n: GraphNode, edges: SocialEdge[]): string {
  const ties = edges.filter((e) => e.source === n.id || e.target === n.id).length;
  const state = n.alive ? 'alive' : 'deceased';
  const faction = n.factionName ? ` · ⚑ ${n.factionName}` : '';
  return `${n.label ?? n.id} — ${state} · ${ties} tie${ties === 1 ? '' : 's'}${faction}`;
}

function edgeTooltip(l: GraphLink): string {
  const s = endpointId(l.source);
  const t = endpointId(l.target);
  const trust = typeof l.trust === 'number' ? Math.round(l.trust) : 0;
  const type = typeof l.type === 'string' ? l.type : 'neutral';
  return `${s} ↔ ${t} — ${type} (trust ${trust > 0 ? '+' : ''}${trust})`;
}

/** A link endpoint may be an id (pre-layout) or a resolved node object. */
function endpointId(end: GraphLink['source'] | GraphLink['target']): string {
  if (end && typeof end === 'object') return String((end as { id?: string | number }).id ?? '');
  return String(end ?? '');
}

// ── token plumbing (canvas wants real colors; read declared CSS vars) ─────────

interface ResolvedTokens {
  bg: string;
  text: string;
  dim: string;
  acid: string;
  danger: string;
  edgeFlat: string;
  nodeNeutral: string;
  // Wave E — typed-bond edge registers + the faction ring tint.
  relPartner: string;
  relFamily: string;
  relMentor: string;
  relFeud: string;
  faction: string;
}

/**
 * Resolve the lab tokens the canvas paints with.
 *
 * EM-196 — canvas never trusts an unresolved var: getComputedStyle can return
 * '' on a timing/route edge (stylesheet not applied yet), and a falsy
 * `backgroundColor` never passes force-graph's init guard, leaving a
 * transparent canvas over the OS-white page (the "white box"). So EVERY
 * canvas-bound read carries a literal hex fallback. The literals MIRROR the
 * declared token values EXACTLY — inspector-tokens.css (--lab-*,
 * --marker-crime, --inspector-node-neutral, --faction-tint) and
 * roster-tokens.css (--rel-*) — for canvas safety only; they must be kept in
 * lockstep with those token sheets.
 *
 * Exported (not just the hook) so the fallback table is unit-testable with a
 * stubbed getComputedStyle.
 */
export function resolveTokens(): ResolvedTokens {
  return {
    bg: cssVar('--lab-bg') || '#0a0a0b',
    text: cssVar('--lab-text') || cssVar('--inspector-node-neutral') || '#e8e8f0',
    dim: cssVar('--lab-dim') || '#3a3a50',
    acid: cssVar('--lab-acid') || '#c8ff00',
    danger: cssVar('--marker-crime') || '#ff3333',
    edgeFlat: cssVar('--lab-muted') || '#5a5a72',
    nodeNeutral: cssVar('--inspector-node-neutral') || '#5a5a72',
    relPartner: cssVar('--rel-partner') || '#ff6fa5',
    relFamily: cssVar('--rel-family') || '#ffb347',
    relMentor: cssVar('--rel-mentor') || '#4cc9f0',
    relFeud: cssVar('--rel-feud') || '#a31621',
    faction: cssVar('--faction-tint') || '#2ee6a8',
  };
}

function useResolvedTokens(): ResolvedTokens {
  const [tokens] = useState<ResolvedTokens>(resolveTokens);
  return tokens;
}

/** Wave E: the type-keyed edge tint — only the four new bond types override
 *  the trust-sign tint (feud deliberately DARKER than enemy's danger red).
 *  Unknown/legacy types return null → the caller's trust-sign fallback. */
function typeEdgeColor(type: string, tokens: ResolvedTokens): string | null {
  switch (type) {
    case 'partner': return tokens.relPartner || null;
    case 'family':  return tokens.relFamily || null;
    case 'mentor':  return tokens.relMentor || null;
    case 'feud':    return tokens.relFeud || null;
    default:        return null;
  }
}

/** Read a declared CSS custom property for Canvas use (no DOM ⇒ ''). */
function cssVar(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Apply an alpha to a token color for the canvas. Handles #rgb / #rrggbb (the
 * lab tokens are hex) and falls back to the raw value (already rgba/named).
 */
function withAlpha(color: string, alpha: number): string {
  const hex = color.trim();
  const m3 = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(hex);
  const m6 = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  let r = 0;
  let g = 0;
  let b = 0;
  if (m6) {
    r = parseInt(m6[1], 16);
    g = parseInt(m6[2], 16);
    b = parseInt(m6[3], 16);
  } else if (m3) {
    r = parseInt(m3[1] + m3[1], 16);
    g = parseInt(m3[2] + m3[2], 16);
    b = parseInt(m3[3] + m3[3], 16);
  } else {
    return hex; // already a usable color string
  }
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
