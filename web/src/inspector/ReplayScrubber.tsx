/**
 * ReplayScrubber (EM-055, reshaped wave G EM-197) — the inspector's time
 * machine, now in TWO pieces so the annex can be viewport-fit:
 *
 *  • `ReplayScrubber` — the SLIM SCRUB STRIP: play / pause / step / speed
 *    transport, the timeline slider, the color-coded event-marker rail
 *    (crime=red, governance=blue, construction=amber, animal=magenta,
 *    trace=dim) and its legend. InspectorLayout pins it under the status
 *    strip, OUTSIDE the panel grid, so it never scrolls away.
 *
 *  • `ReplayMapPanel` — the top-down Canvas2D mini-map of agent positions AT
 *    `currentTick` (Canvas2D — NOT the 3D scene, never react-three-fiber; the
 *    GPU rests in the annex) plus the structures readout, now a wrapped
 *    COMPACT CHIP GRID (name + status dot, status text on title hover),
 *    capped with internal scroll. The map keeps its aspect (the logical
 *    1000×1000 world maps onto a centered square region of the cell) and the
 *    tick badge stays.
 *
 * Neither piece owns tick state — InspectorLayout holds the shared
 * `currentTick`/`maxTick`; the strip drives them via `onSeek` and every panel
 * re-projects at `currentTick` (scrub once, everything follows).
 *
 * Pure projection: positions come from `replayStateAt` over the rolling
 * history (mock-safe, no backend). Token-only styling (lab-* classes); the
 * Canvas reads colors from data (agent profile colors) and named marker tokens.
 */

import { useEffect, useMemo, useRef, useCallback, useState } from 'react';
import type { Agent, Animal, BuildingStatus, ModelProfile, WorldEvent } from '../types';
import { replayStateAt, markerCategory } from './selectors';
import type { MarkerCategory, ReplaySnapshot } from './selectors';
import type { ReplayBuildingState } from './types';
import './inspector-tokens.css';

interface ReplayScrubberProps {
  events: WorldEvent[];
  currentTick: number;
  maxTick: number;
  onSeek: (tick: number) => void;
  /**
   * Wave G: the map + structures moved to `ReplayMapPanel`; these are still
   * ACCEPTED (callers/tests that pass the full pre-G2 bag keep compiling)
   * but the strip itself never reads them.
   */
  agents?: Agent[];
  profiles?: ModelProfile[];
  places?: Array<{ id: string; x: number; y: number; name?: string }>;
  buildings?: ReplayBuildingState[];
  animals?: Animal[];
  snapshots?: ReplaySnapshot[];
}

// W7 building-status → CSS custom property (declared in inspector-tokens.css).
// The canvas (getComputedStyle) and the DOM readout (var(--…)) share these, so
// markers never drift from the theme (no hardcoded hex anywhere).
const BUILDING_STATUS_VAR: Record<BuildingStatus, string> = {
  planned: '--building-planned',
  under_construction: '--building-under-construction',
  operational: '--building-operational',
  damaged: '--building-damaged',
  offline: '--building-offline',
  abandoned: '--building-abandoned',
  destroyed: '--building-destroyed',
};

function buildingStatusVarRef(status: BuildingStatus): string {
  return `var(${BUILDING_STATUS_VAR[status]})`;
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

// ── The slim scrub strip ──────────────────────────────────────────────────────

export function ReplayScrubber({
  events,
  currentTick,
  maxTick,
  onSeek,
}: ReplayScrubberProps) {
  // Audit C2: refs drive the interval (no re-subscribe per tick) but a ref read
  // in render never updates the DOM — so play/speed are ALSO tracked as state,
  // kept in lockstep with the refs, and the button label / aria-pressed render
  // from the state.
  const playingRef = useRef(false);
  const [playing, setPlaying] = useState(false);
  const speedRef = useRef<number>(1);
  const [speed, setSpeedState] = useState<number>(1);
  const playTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Latest scrub position in a ref so the play interval reads fresh values
  // without re-subscribing each tick.
  const tickRef = useRef(currentTick);
  tickRef.current = currentTick;
  const maxRef = useRef(maxTick);
  maxRef.current = maxTick;

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
    setPlaying(false);
    if (playTimerRef.current) {
      clearInterval(playTimerRef.current);
      playTimerRef.current = null;
    }
  }, []);

  const startPlay = useCallback(() => {
    if (playTimerRef.current) clearInterval(playTimerRef.current);
    playingRef.current = true;
    setPlaying(true);
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
      setSpeedState(s);
      if (playingRef.current) startPlay(); // re-arm interval at the new rate
    },
    [startPlay],
  );

  // Tear the play loop down on unmount (leak-free, like the contract demands).
  useEffect(() => stopPlay, [stopPlay]);

  const railMax = Math.max(1, maxTick);

  return (
    <section
      className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5 border-b border-lab-border bg-lab-surface shrink-0"
      aria-label="Replay scrubber (EM-055)"
    >
      {/* Transport controls — compact (the strip is viewport chrome now). */}
      <span className="flex items-center gap-1 shrink-0">
        <button
          type="button"
          onClick={() => stepBy(-1)}
          className="font-mono text-[10px] font-semibold px-1.5 py-0.5 border border-lab-border text-lab-text cursor-pointer hover:border-lab-acid hover:text-lab-acid transition-colors"
          aria-label="Step back one tick"
          title="Step back"
        >
          ⟨
        </button>
        <button
          type="button"
          onClick={togglePlay}
          className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-acid bg-lab-acid text-lab-bg cursor-pointer hover:bg-white hover:border-white transition-colors"
          aria-label="Play or pause the replay"
          aria-pressed={playing}
        >
          {playing ? 'PAUSE' : 'PLAY'}
        </button>
        <button
          type="button"
          onClick={() => stepBy(1)}
          className="font-mono text-[10px] font-semibold px-1.5 py-0.5 border border-lab-border text-lab-text cursor-pointer hover:border-lab-acid hover:text-lab-acid transition-colors"
          aria-label="Step forward one tick"
          title="Step forward"
        >
          ⟩
        </button>
      </span>

      <span className="flex items-center gap-1 shrink-0">
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSpeed(s)}
            className={
              speed === s
                ? 'font-mono text-[9px] px-1 py-0.5 border border-lab-acid text-lab-acid bg-lab-acid/10'
                : 'font-mono text-[9px] px-1 py-0.5 border border-lab-border text-lab-muted hover:border-lab-acid hover:text-lab-acid transition-colors'
            }
            aria-label={`Set replay speed ${s}x`}
            aria-pressed={speed === s}
          >
            {s}×
          </button>
        ))}
      </span>

      {/* Timeline rail: slider + color-coded markers underneath. */}
      <span className="flex-1 min-w-[10rem] flex flex-col gap-0.5">
        <input
          type="range"
          min={0}
          max={railMax}
          value={Math.min(currentTick, railMax)}
          onChange={(e) => {
            stopPlay();
            onSeek(Number(e.target.value));
          }}
          className="w-full accent-lab-acid cursor-pointer h-3"
          aria-label="Scrub to tick"
        />
        <span className="relative h-2 w-full bg-lab-chrome rounded-sm overflow-hidden">
          {[...markers.entries()].map(([tick, cats]) => {
            const leftPct = (Math.min(tick, railMax) / railMax) * 100;
            // One thin tick mark per category present at this tick, stacked.
            return [...cats].map((cat, i) => (
              <MarkerTick
                key={`${tick}-${cat}`}
                leftPct={leftPct}
                color={markerVarRef(cat)}
                offset={i}
              />
            ));
          })}
        </span>
      </span>

      {/* Marker legend — inline, tiny. */}
      <span className="hidden xl:flex items-center gap-x-2 shrink-0">
        {MARKER_LEGEND.map((m) => (
          <span key={m.cat} className="flex items-center gap-1">
            <i
              className="inline-block w-1.5 h-1.5 rounded-sm"
              style={{ backgroundColor: markerVarRef(m.cat) }}
            />
            <span className="font-mono text-[8px] text-lab-muted uppercase tracking-wide">
              {m.label}
            </span>
          </span>
        ))}
      </span>

      <span className="ml-auto font-mono text-[11px] tabular-nums text-lab-text shrink-0">
        TICK <span className="text-lab-acid">{String(currentTick).padStart(4, '0')}</span>
        <span className="text-lab-dim"> / {String(maxTick).padStart(4, '0')}</span>
      </span>
    </section>
  );
}

// ── The replay map + structures panel (a grid cell) ──────────────────────────

interface ReplayMapPanelProps {
  events: WorldEvent[];
  agents: Agent[];
  profiles: ModelProfile[];
  places: Array<{ id: string; x: number; y: number; name?: string }>;
  /**
   * W7 buildings — surfaced as status markers on the mini-map + chips.
   * W10 / audit C7: while scrubbed, InspectorLayout passes the TIME-PROJECTED
   * building state at the scrub tick (folded by replayStateAt) instead of the
   * live roster, so the map/readout show each structure as it WAS at tick T.
   */
  buildings?: ReplayBuildingState[];
  /** W10 / audit D4: live animal roster — the replay fold's position fallback. */
  animals?: Animal[];
  currentTick: number;
  maxTick: number;
  /** Optional deep-replay snapshots (live mode); empty in mock. */
  snapshots?: ReplaySnapshot[];
}

export function ReplayMapPanel({
  events,
  agents,
  profiles,
  places,
  buildings = [],
  animals = [],
  currentTick,
  maxTick,
  snapshots = [],
}: ReplayMapPanelProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // The replay frame at the current scrub tick (positions for the mini-map).
  // The animal roster rides along so frame.animals can fall back to live
  // positions when no snapshot covers the tick (D4 — best-effort, labeled "~").
  const frame = useMemo(() => {
    const f = replayStateAt(events, snapshots, currentTick, agents, places, [], animals);
    // Pinned to the live edge: the live roster IS the tick-T truth, so the
    // roster-fallback positions are exact — clear the approximation flag.
    if (currentTick >= maxTick && f.animals.some((a) => a.approximate)) {
      return {
        ...f,
        animals: f.animals.map((a) => (a.approximate ? { ...a, approximate: false } : a)),
      };
    }
    return f;
  }, [events, snapshots, currentTick, maxTick, agents, places, animals]);

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
    const neutral = cssVar('--inspector-node-neutral');
    const outline = cssVar('--lab-border-bright') || cssVar('--lab-muted');
    const labelInk = cssVar('--lab-muted');
    const brightInk = cssVar('--lab-text') || neutral;
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    // Wave G (EM-197): ASPECT-PRESERVED fit — the logical 1000×1000 world maps
    // onto a centered SQUARE region of whatever cell the panel got, so the map
    // never stretches when the grid cell isn't square.
    const side = Math.min(W, H);
    const ox = (W - side) / 2;
    const oy = (H - side) / 2;
    const pad = side * 0.12;
    const sx = (x: number) => ox + pad + (x / 1000) * (side - 2 * pad);
    const sy = (y: number) => oy + pad + (y / 1000) * (side - 2 * pad);

    // Place footprints + labels (audit D3 quick-win: the old ghost outlines
    // were nearly invisible and the dots unlabeled — brighter token strokes
    // and a name under each footprint make the map legible at a glance).
    ctx.save();
    ctx.strokeStyle = outline;
    ctx.lineWidth = 1.5;
    ctx.font = '8px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const p of places) {
      const px = sx(p.x);
      const py = sy(p.y);
      ctx.strokeRect(px - 7, py - 7, 14, 14);
      ctx.fillStyle = labelInk;
      ctx.fillText((p.name ?? p.id).slice(0, 14), px, py + 9);
    }
    ctx.restore();

    // W7: building markers — a small diamond per building at its place, colored
    // by status. A stable per-building angle offsets it from the place center so
    // co-located structures don't stack. (W10/C7: while scrubbed the `buildings`
    // prop is the TIME-PROJECTED state at the scrub tick, so the diamond color
    // is the status the structure had at tick T — not the live edge.)
    const placeById = new Map(places.map((p) => [p.id, p]));
    for (const b of buildings) {
      const place = placeById.get(b.location);
      if (!place) continue;
      // deterministic angle from the id so the diamond sits beside the footprint.
      let h = 2166136261;
      for (let i = 0; i < b.id.length; i++) {
        h ^= b.id.charCodeAt(i);
        h = (h * 16777619) >>> 0;
      }
      const ang = ((h % 360) / 360) * Math.PI * 2;
      const off = side * 0.05;
      const bx = sx(place.x) + Math.cos(ang) * off;
      const by = sy(place.y) + Math.sin(ang) * off;
      const sz = Math.max(3, side * 0.014);
      ctx.save();
      ctx.translate(bx, by);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = cssVar(BUILDING_STATUS_VAR[b.status] ?? '--building-planned') || neutral;
      // hollow for not-yet-built states so they read as "incomplete".
      const hollow = b.status === 'planned' || b.status === 'destroyed';
      if (hollow) {
        ctx.strokeStyle = ctx.fillStyle;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(-sz / 2, -sz / 2, sz, sz);
      } else {
        ctx.fillRect(-sz / 2, -sz / 2, sz, sz);
      }
      ctx.restore();
    }

    // Agents at currentTick — dot + bright outline ring + name label, with
    // co-located agents fanned slightly so dots don't fully stack (D3).
    const nameOf = new Map(agents.map((a) => [a.id, a.name]));
    const r = Math.max(4, side * 0.018);
    const seenAt = new Map<string, number>();
    for (const a of frame.agents) {
      const locKey = `${a.x},${a.y}`;
      const slot = seenAt.get(locKey) ?? 0;
      seenAt.set(locKey, slot + 1);
      const fan = slot * (r * 2.4);
      const ax = sx(a.x) + fan;
      const ay = sy(a.y) - fan * 0.4;
      ctx.save();
      if (!a.alive) ctx.globalAlpha = 0.3;
      ctx.beginPath();
      ctx.arc(ax, ay, r, 0, Math.PI * 2);
      // a.color is the agent's model color from data; empty → neutral token.
      ctx.fillStyle = a.color || neutral;
      ctx.fill();
      // Bright ring so a dot reads against dark place footprints.
      ctx.lineWidth = 1;
      ctx.strokeStyle = brightInk;
      ctx.stroke();
      // Name label above the dot (dead agents read with a struck "†").
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillStyle = brightInk;
      const name = nameOf.get(a.id) ?? a.id;
      ctx.fillText(`${a.alive ? '' : '† '}${name.slice(0, 10)}`, ax, ay - r - 1);
      ctx.restore();
    }

    // W10 / audit D4: animals — small magenta-accented triangles (distinct from
    // the round agent dots and the diamond buildings), with the SAME name-label
    // treatment agents got in W9 (D3). Positions are best-effort (see
    // replayStateAt): a "~" prefix marks a live-roster approximation.
    const animalInk = cssVar('--marker-animal') || neutral;
    const ar = Math.max(3, side * 0.014);
    for (const a of frame.animals) {
      const px = sx(a.x);
      // Sit animals slightly below the place footprint so they never stack on
      // the agent fan above it.
      const py = sy(a.y) + ar * 3;
      ctx.save();
      if (!a.alive) ctx.globalAlpha = 0.3;
      ctx.beginPath();
      ctx.moveTo(px, py - ar);
      ctx.lineTo(px + ar, py + ar);
      ctx.lineTo(px - ar, py + ar);
      ctx.closePath();
      ctx.fillStyle = animalInk;
      ctx.fill();
      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(
        `${a.approximate ? '~' : ''}${a.alive ? '' : '† '}${a.name.slice(0, 10)}`,
        px,
        py + ar + 1,
      );
      ctx.restore();
    }

    // Tick overlay (the badge STAYS — bottom-right of the cell).
    ctx.save();
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.fillStyle = cssVar('--lab-dim');
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`TICK ${frame.tick}`, W - 6, H - 5);
    ctx.restore();
  }, [frame, places, buildings, agents]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    const obs = new ResizeObserver(() => draw());
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, [draw]);

  return (
    <section
      className="lab-panel flex flex-col h-full min-h-0 overflow-hidden"
      aria-label="Replay map (EM-055)"
    >
      {/* Slim panel header: title + live counts + EM-tag right-aligned. */}
      <div className="lab-header flex items-center gap-2 !py-1 shrink-0">
        <span>Replay Map</span>
        <span className="font-mono text-[10px] text-lab-muted normal-case tracking-normal tabular-nums">
          {frame.eventsAtTick.length} event{frame.eventsAtTick.length === 1 ? '' : 's'} @ T
          {currentTick} · {profiles.length} models · {agents.length} agents
        </span>
        <span className="ml-auto font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          EM-055
        </span>
      </div>

      {/* Top-down Canvas2D mini-map (NOT the 3D scene) — fills the cell;
          the drawing keeps a centered square (aspect preserved). */}
      <div
        ref={containerRef}
        className="relative flex-1 min-h-[4rem] bg-lab-bg overflow-hidden"
      >
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

      {/* W7 structures readout → wave G: a wrapped COMPACT CHIP GRID (name +
          status dot; status + progress ride the title tooltip), capped height
          with internal scroll — the old 26-row list is gone. */}
      {buildings.length > 0 && (
        <div
          className="min-h-[2.25rem] overflow-hidden border-t border-lab-border px-2 py-1.5 flex flex-col gap-1"
          aria-label={`Structures (${buildings.length})`}
        >
          <span className="font-mono text-[9px] text-lab-muted uppercase tracking-wide tabular-nums">
            Structures · {buildings.length}
          </span>
          <ul
            role="list"
            className="m-0 p-0 list-none flex flex-wrap gap-1 max-h-20 overflow-y-auto"
            data-testid="structures-chips"
          >
            {buildings.map((b) => (
              <li
                key={b.id}
                className="flex items-center gap-1 px-1.5 py-0.5 border border-lab-border bg-lab-bg font-mono text-[9px] text-lab-text max-w-[9rem]"
                title={`${b.name} — ${b.status.replace(/_/g, ' ')}${
                  b.status === 'under_construction' || b.status === 'planned'
                    ? ` (${Math.max(0, Math.min(100, b.progress))}%)`
                    : ''
                }`}
              >
                <i
                  className="inline-block w-1.5 h-1.5 rounded-sm shrink-0"
                  style={{ backgroundColor: buildingStatusVarRef(b.status) }}
                  aria-hidden="true"
                />
                <span className="truncate">{b.name}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
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
