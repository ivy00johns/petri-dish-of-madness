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
 * Node colors come from the data (the agent's model color). No hardcoded hex.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import type { ForceGraphMethods, NodeObject, LinkObject } from 'react-force-graph-2d';
import type { PanelProps } from './types';
import type { SocialNode, SocialEdge } from './types';
import { socialGraph } from './selectors';
import './inspector-tokens.css';

// ── graph element shapes (our SocialNode/SocialEdge carried on the lib's bag) ──

type GraphNode = NodeObject<SocialNode>;
type GraphLink = LinkObject<SocialNode, SocialEdge>;

// Relationship types, for the legend + the dim/spotlight readout.
const REL_LEGEND: Array<{ key: string; label: string; tone: 'pos' | 'neg' | 'flat' }> = [
  { key: 'ally', label: 'ally', tone: 'pos' },
  { key: 'friend', label: 'friend', tone: 'pos' },
  { key: 'neutral', label: 'neutral', tone: 'flat' },
  { key: 'rival', label: 'rival', tone: 'neg' },
  { key: 'enemy', label: 'enemy', tone: 'neg' },
];

const COOLDOWN_TICKS = 120; // bounded settle, then the sim freezes (battery).
const NODE_REL_SIZE = 5;

export default function SocialGraph(props: PanelProps) {
  const { events, agents, currentTick } = props;

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

  // Pause the render loop on unmount (leak-free, like the annex demands).
  useEffect(() => {
    const fg = fgRef.current;
    return () => {
      fg?.pauseAnimation();
    };
  }, []);

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

  // Edge color: tinted by trust sign; spotlight-aware.
  const linkColor = useCallback(
    (l: GraphLink): string => {
      const trust = typeof l.trust === 'number' ? l.trust : 0;
      const base = trust > 4 ? tokens.acid : trust < -4 ? tokens.danger : tokens.edgeFlat;
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

  const nodeCount = projection.nodes.length;
  const edgeCount = projection.edges.length;
  const aliveCount = projection.nodes.filter((n) => n.alive).length;
  const ready = size.w > 0 && size.h > 0 && nodeCount >= 2;

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
                style={{ backgroundColor: legendVar(r.tone) }}
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
          <EmptyState nodeCount={nodeCount} sized={size.w > 0} />
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

function EmptyState({ nodeCount, sized }: { nodeCount: number; sized: boolean }) {
  const msg = !sized
    ? 'sizing…'
    : nodeCount === 0
      ? 'no agents in this run yet'
      : 'one lone agent — no relationships to graph';
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 text-center">
      <span className="font-mono text-[10px] uppercase tracking-widest text-lab-dim">{msg}</span>
      {sized && nodeCount <= 1 && (
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
  return `${n.label ?? n.id} — ${state} · ${ties} tie${ties === 1 ? '' : 's'}`;
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
}

/** Resolve the lab tokens the canvas paints with (re-reads on mount). */
function useResolvedTokens(): ResolvedTokens {
  const [tokens] = useState<ResolvedTokens>(() => ({
    bg: cssVar('--lab-bg'),
    text: cssVar('--lab-text') || cssVar('--inspector-node-neutral'),
    dim: cssVar('--lab-dim'),
    acid: cssVar('--lab-acid'),
    danger: cssVar('--marker-crime'),
    edgeFlat: cssVar('--lab-muted'),
    nodeNeutral: cssVar('--inspector-node-neutral'),
  }));
  return tokens;
}

/** Legend swatch color by trust tone — reads the same tokens the canvas uses. */
function legendVar(tone: 'pos' | 'neg' | 'flat'): string {
  if (tone === 'pos') return 'var(--lab-acid)';
  if (tone === 'neg') return 'var(--marker-crime)';
  return 'var(--lab-muted)';
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
