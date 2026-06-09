/**
 * ReplayScrubber (EM-055) — the inspector's time machine.
 *
 * A timeline slider over the run's ticks with play / pause / step / speed
 * controls, color-coded event markers (crime=red, governance=blue,
 * construction=amber, animal=magenta, trace=dim), and a top-down Canvas2D
 * mini-map of agent positions AT `currentTick` (Canvas2D — NOT the 3D scene,
 * never react-three-fiber; the GPU rests in the annex).
 *
 * It owns NO tick state — InspectorLayout holds the shared `currentTick` and
 * `maxTick`; this component drives them via `onSeek`. Every other panel
 * re-projects at `currentTick` (scrub once, everything follows).
 *
 * Pure projection: positions come from `replayStateAt` over the rolling
 * history (mock-safe, no backend). Token-only styling (lab-* classes); the
 * Canvas reads colors from data (agent profile colors) and named marker tokens.
 */

import { useEffect, useMemo, useRef, useCallback } from 'react';
import type { Agent, ModelProfile, WorldEvent } from '../types';
import { replayStateAt, markerCategory } from './selectors';
import type { MarkerCategory, ReplaySnapshot } from './selectors';
import './inspector-tokens.css';

interface ReplayScrubberProps {
  events: WorldEvent[];
  agents: Agent[];
  profiles: ModelProfile[];
  places: Array<{ id: string; x: number; y: number }>;
  currentTick: number;
  maxTick: number;
  /** Optional deep-replay snapshots (live mode); empty in mock. */
  snapshots?: ReplaySnapshot[];
  onSeek: (tick: number) => void;
}

// Marker colors are a fixed, named LEGEND tied to the contract's color code
// (frontend-inspector.md §4). Each maps to a CSS custom property declared in
// inspector-tokens.css, so the DOM legend (var(--…)) and the Canvas timeline
// (getComputedStyle) read the SAME token — no hardcoded hex anywhere.
const MARKER_VAR: Record<MarkerCategory, string> = {
  crime: '--marker-crime',
  governance: '--marker-governance',
  construction: '--marker-construction',
  animal: '--marker-animal',
  trace: '--marker-trace',
  other: '--marker-other',
};

/** CSS `var(--token)` reference for a marker category (DOM use). */
function markerVarRef(cat: MarkerCategory): string {
  return `var(${MARKER_VAR[cat]})`;
}

const MARKER_LEGEND: Array<{ cat: MarkerCategory; label: string }> = [
  { cat: 'crime', label: 'crime' },
  { cat: 'governance', label: 'governance' },
  { cat: 'construction', label: 'construction' },
  { cat: 'animal', label: 'animal' },
  { cat: 'trace', label: 'trace' },
];

const SPEEDS = [0.5, 1, 2, 4] as const;
const BASE_STEP_MS = 700;

export function ReplayScrubber({
  events,
  agents,
  profiles,
  places,
  currentTick,
  maxTick,
  snapshots = [],
  onSeek,
}: ReplayScrubberProps) {
  const playingRef = useRef(false);
  const speedRef = useRef<number>(1);
  const playTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Latest scrub position in a ref so the play interval reads fresh values
  // without re-subscribing each tick.
  const tickRef = useRef(currentTick);
  tickRef.current = currentTick;
  const maxRef = useRef(maxTick);
  maxRef.current = maxTick;

  // The replay frame at the current scrub tick (positions for the mini-map).
  const frame = useMemo(
    () => replayStateAt(events, snapshots, currentTick, agents, places),
    [events, snapshots, currentTick, agents, places],
  );

  // Marker buckets per tick (for the timeline rail). Newest data wins.
  const markers = useMemo(() => {
    const byTick = new Map<number, Set<MarkerCategory>>();
    for (const e of events) {
      const cat = markerCategory(e);
      if (cat === 'other') continue;
      const set = byTick.get(e.tick) ?? new Set<MarkerCategory>();
      set.add(cat);
      byTick.set(e.tick, set);
    }
    return byTick;
  }, [events]);

  const stopPlay = useCallback(() => {
    playingRef.current = false;
    if (playTimerRef.current) {
      clearInterval(playTimerRef.current);
      playTimerRef.current = null;
    }
  }, []);

  const startPlay = useCallback(() => {
    if (playTimerRef.current) clearInterval(playTimerRef.current);
    playingRef.current = true;
    playTimerRef.current = setInterval(() => {
      const next = tickRef.current + 1;
      if (next > maxRef.current) {
        stopPlay();
        return;
      }
      onSeek(next);
    }, BASE_STEP_MS / speedRef.current);
  }, [onSeek, stopPlay]);

  const togglePlay = useCallback(() => {
    if (playingRef.current) {
      stopPlay();
    } else {
      // Restart from the beginning if we're parked at the end.
      if (tickRef.current >= maxRef.current) onSeek(0);
      startPlay();
    }
  }, [startPlay, stopPlay, onSeek]);

  const stepBy = useCallback(
    (delta: number) => {
      stopPlay();
      const next = Math.max(0, Math.min(maxRef.current, tickRef.current + delta));
      onSeek(next);
    },
    [onSeek, stopPlay],
  );

  const setSpeed = useCallback(
    (s: number) => {
      speedRef.current = s;
      if (playingRef.current) startPlay(); // re-arm interval at the new rate
    },
    [startPlay],
  );

  // Tear the play loop down on unmount (leak-free, like the contract demands).
  useEffect(() => stopPlay, [stopPlay]);

  // ── Canvas2D mini-map: top-down agent positions at currentTick ─────────────
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const dpr = window.devicePixelRatio || 1;
    const W = container.clientWidth;
    const H = container.clientHeight;
    const bw = Math.round(W * dpr);
    const bh = Math.round(H * dpr);
    if (canvas.width !== bw || canvas.height !== bh) {
      canvas.width = bw;
      canvas.height = bh;
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Read the lab tokens off the declared CSS custom properties so the canvas
    // stays in lockstep with the theme (never a hardcoded hex literal).
    const bg = cssVar('--lab-bg');
    const grid = cssVar('--lab-chrome');
    const neutral = cssVar('--inspector-node-neutral');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    const pad = Math.min(W, H) * 0.12;
    const sx = (x: number) => pad + (x / 1000) * (W - 2 * pad);
    const sy = (y: number) => pad + (y / 1000) * (H - 2 * pad);

    // Faint place footprints (so positions read as "somewhere").
    ctx.save();
    ctx.strokeStyle = grid;
    ctx.lineWidth = 1;
    for (const p of places) {
      const px = sx(p.x);
      const py = sy(p.y);
      ctx.strokeRect(px - 6, py - 6, 12, 12);
    }
    ctx.restore();

    // Agents at currentTick.
    const r = Math.max(4, Math.min(W, H) * 0.018);
    for (const a of frame.agents) {
      const ax = sx(a.x);
      const ay = sy(a.y);
      ctx.save();
      if (!a.alive) ctx.globalAlpha = 0.25;
      ctx.beginPath();
      ctx.arc(ax, ay, r, 0, Math.PI * 2);
      // a.color is the agent's model color from data; empty → neutral token.
      ctx.fillStyle = a.color || neutral;
      ctx.fill();
      ctx.restore();
    }

    // Tick overlay.
    ctx.save();
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.fillStyle = cssVar('--lab-dim');
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`TICK ${frame.tick}`, W - 6, H - 5);
    ctx.restore();
  }, [frame, places]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    const obs = new ResizeObserver(() => draw());
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, [draw]);

  const railMax = Math.max(1, maxTick);

  return (
    <section className="lab-panel flex flex-col" aria-label="Replay scrubber (EM-055)">
      <div className="lab-header flex items-center justify-between gap-2">
        <span>Replay</span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          EM-055
        </span>
      </div>

      <div className="flex flex-col gap-3 p-3">
        {/* Transport controls */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => stepBy(-1)}
            className="lab-btn-secondary"
            aria-label="Step back one tick"
            title="Step back"
          >
            ⟨ STEP
          </button>
          <button
            type="button"
            onClick={togglePlay}
            className="lab-btn-primary"
            aria-label="Play or pause the replay"
          >
            {playingRef.current ? 'PAUSE' : 'PLAY'}
          </button>
          <button
            type="button"
            onClick={() => stepBy(1)}
            className="lab-btn-secondary"
            aria-label="Step forward one tick"
            title="Step forward"
          >
            STEP ⟩
          </button>

          <div className="flex items-center gap-1 ml-1">
            <span className="font-mono text-[10px] text-lab-muted uppercase tracking-wide">
              speed
            </span>
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSpeed(s)}
                className={
                  speedRef.current === s
                    ? 'font-mono text-[10px] px-1.5 py-0.5 border border-lab-acid text-lab-acid bg-lab-acid/10'
                    : 'font-mono text-[10px] px-1.5 py-0.5 border border-lab-border text-lab-muted hover:border-lab-acid hover:text-lab-acid transition-colors'
                }
                aria-label={`Set replay speed ${s}x`}
                aria-pressed={speedRef.current === s}
              >
                {s}×
              </button>
            ))}
          </div>

          <span className="ml-auto font-mono text-xs tabular-nums text-lab-text">
            TICK <span className="text-lab-acid">{String(currentTick).padStart(4, '0')}</span>
            <span className="text-lab-dim"> / {String(maxTick).padStart(4, '0')}</span>
          </span>
        </div>

        {/* Timeline rail: slider + color-coded markers underneath */}
        <div className="flex flex-col gap-1">
          <input
            type="range"
            min={0}
            max={railMax}
            value={Math.min(currentTick, railMax)}
            onChange={(e) => {
              stopPlay();
              onSeek(Number(e.target.value));
            }}
            className="w-full accent-lab-acid cursor-pointer"
            aria-label="Scrub to tick"
          />
          <div className="relative h-3 w-full bg-lab-chrome rounded-sm overflow-hidden">
            {[...markers.entries()].map(([tick, cats]) => {
              const leftPct = (Math.min(tick, railMax) / railMax) * 100;
              // One thin tick mark per category present at this tick, stacked.
              return [...cats].map((cat, i) => (
                <MarkerTick key={`${tick}-${cat}`} leftPct={leftPct} color={markerVarRef(cat)} offset={i} />
              ));
            })}
          </div>
          {/* Legend */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 pt-0.5">
            {MARKER_LEGEND.map((m) => (
              <span key={m.cat} className="flex items-center gap-1">
                <i className="inline-block w-2 h-2 rounded-sm" style={{ backgroundColor: markerVarRef(m.cat) }} />
                <span className="font-mono text-[9px] text-lab-muted uppercase tracking-wide">
                  {m.label}
                </span>
              </span>
            ))}
          </div>
        </div>

        {/* Top-down Canvas2D mini-map (NOT the 3D scene) */}
        <div ref={containerRef} className="relative w-full h-32 bg-lab-bg border border-lab-border rounded-sm overflow-hidden">
          <canvas
            ref={canvasRef}
            className="absolute inset-0 w-full h-full"
            aria-label={`Agent positions at tick ${currentTick}`}
          />
          {frame.agents.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="font-mono text-[10px] text-lab-dim uppercase tracking-widest">
                no positions yet
              </span>
            </div>
          )}
        </div>

        <span className="font-mono text-[10px] text-lab-dim">
          {frame.eventsAtTick.length} event{frame.eventsAtTick.length === 1 ? '' : 's'} at this tick ·{' '}
          {profiles.length} models · {agents.length} agents
        </span>
      </div>
    </section>
  );
}

// A single color-coded marker on the timeline rail. Stacked vertically when a
// tick has multiple categories. `backgroundColor`/`left` are data-driven
// positions/legend colors, not hardcoded design literals.
function MarkerTick({ leftPct, color, offset }: { leftPct: number; color: string; offset: number }) {
  // Fixed sizing comes from Tailwind utilities (h-1 = 4px, w-px); only the
  // data-driven position + legend color ride the inline style (all dynamic →
  // design-token-guard clean, no hardcoded literals).
  return (
    <i
      className="absolute w-px h-1"
      style={{
        left: `${leftPct}%`,
        backgroundColor: color,
        top: `${offset * 0.25}rem`,
      }}
      aria-hidden="true"
    />
  );
}

/**
 * Read a declared CSS custom property (a theme token from inspector-tokens.css)
 * for Canvas use, where a class can't apply. Returns '' if unresolved (only in
 * a non-DOM environment) — never a hardcoded hex literal.
 */
function cssVar(name: string): string {
  if (typeof window === 'undefined') return '';
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
