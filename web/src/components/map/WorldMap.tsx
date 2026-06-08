/**
 * WorldMap — lightweight 2D top-down view of the village.
 *
 * Mirrors the 3D "village" view (same place layout, same warm palette, same
 * model-tinted agents that walk between buildings and pulse when they speak),
 * but on a plain 2D canvas — far cheaper on the GPU than React-Three-Fiber.
 *
 * Crispness: the canvas backing store is sized to devicePixelRatio, so it is
 * pixel-sharp on retina displays (the old version rendered at 1× and let CSS
 * stretch it, which is what made it blurry).
 *
 * Efficiency: it does NOT redraw every frame. The animation loop runs only
 * while something is actually moving (agents gliding between places) or
 * pulsing (recent speech); once everything settles it stops and only redraws
 * on new world state, new events, or a resize.
 */

import { useRef, useEffect, useCallback } from 'react';
import type { WorldState, WorldEvent } from '../../types';
import { PLACE_STYLES } from '../world3d/worldSpace';

interface WorldMapProps {
  world: WorldState | null;
  events: WorldEvent[];
}

const SPEECH_PULSE_MS = 2600;   // how long a "speaking" pulse lasts
const EASE = 0.18;              // glide easing per frame
const SETTLE_EPS = 0.4;         // logical-units distance considered "arrived"

interface Vec { x: number; y: number }

export function WorldMap({ world, events }: WorldMapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);

  // Live data in refs so the stable render loop always reads the latest.
  const worldRef = useRef<WorldState | null>(world);
  worldRef.current = world;
  const eventsRef = useRef<WorldEvent[]>(events);
  eventsRef.current = events;

  // Per-agent rendered center in logical [0..1000] space (eases toward target).
  const posRef = useRef<Map<string, Vec>>(new Map());
  // agentId -> timestamp (ms) at which its speaking pulse expires.
  const speakingRef = useRef<Map<string, number>>(new Map());
  const lastSpeechSeqRef = useRef<number>(-1);

  // ── One frame. Returns true if more animation is needed. ──────────────────
  const renderFrame = useCallback((): boolean => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return false;

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
    if (!ctx) return false;
    // Draw in CSS pixels; the transform handles the DPR upscale crisply.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Background
    ctx.fillStyle = '#0a0a0b';
    ctx.fillRect(0, 0, W, H);
    drawGrid(ctx, W, H);

    const world = worldRef.current;
    if (!world) {
      ctx.font = '12px "IBM Plex Mono", monospace';
      ctx.fillStyle = '#3a3a50';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('AWAITING WORLD STATE…', W / 2, H / 2);
      return false;
    }

    const { places, agents } = world;
    const pad = Math.min(W, H) * 0.09;
    const sx = (x: number) => pad + (x / 1000) * (W - 2 * pad);
    const sy = (y: number) => pad + (y / 1000) * (H - 2 * pad);
    const unit = Math.min(W, H);

    // Place centers (pixel) + lookup of logical centers (for agent targets).
    const placePx = new Map<string, Vec>();
    const placeLogical = new Map<string, Vec>();
    places.forEach((p) => {
      placePx.set(p.id, { x: sx(p.x), y: sy(p.y) });
      placeLogical.set(p.id, { x: p.x, y: p.y });
    });

    // Subtle connection paths between nearby places.
    ctx.save();
    ctx.strokeStyle = '#1d1d26';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 6]);
    const pts = [...placePx.values()];
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const a = pts[i], b = pts[j];
        if (Math.hypot(a.x - b.x, a.y - b.y) < unit * 0.5) {
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }
    ctx.restore();

    // Buildings (top-down footprints, warm palette = same as 3D). Labels are
    // drawn in a later pass so co-located agents never occlude place names.
    const bSize = Math.max(26, unit * 0.085);
    places.forEach((p) => {
      const c = placePx.get(p.id)!;
      drawBuilding(ctx, p.kind, c.x, c.y, bSize);
    });

    // Group agents by place for cluster fan-out + ease rendered centers.
    const byPlace = new Map<string, string[]>();
    agents.forEach((a) => {
      const list = byPlace.get(a.location) ?? [];
      list.push(a.id);
      byPlace.set(a.location, list);
    });

    const now = Date.now();
    let animating = false;
    const agentR = Math.min(16, Math.max(9, unit * 0.024));
    const clusterR = bSize * 0.95;

    agents.forEach((a) => {
      const targetLogical = placeLogical.get(a.location) ?? { x: 500, y: 500 };
      let p = posRef.current.get(a.id);
      if (!p) { p = { ...targetLogical }; posRef.current.set(a.id, p); } // new agent: snap

      const dx = targetLogical.x - p.x;
      const dy = targetLogical.y - p.y;
      if (Math.hypot(dx, dy) > SETTLE_EPS) {
        p.x += dx * EASE;
        p.y += dy * EASE;
        animating = true;
      } else {
        p.x = targetLogical.x;
        p.y = targetLogical.y;
      }

      // Pixel center + circular cluster offset (kept in px so it stays round).
      const colocated = byPlace.get(a.location) ?? [a.id];
      const idx = colocated.indexOf(a.id);
      const cnt = colocated.length;
      const ang = cnt > 1 ? (idx / cnt) * Math.PI * 2 - Math.PI / 2 : 0;
      const offR = cnt > 1 ? clusterR : 0;
      const ax = sx(p.x) + Math.cos(ang) * offR;
      const ay = sy(p.y) + Math.sin(ang) * offR;

      const speakUntil = speakingRef.current.get(a.id) ?? 0;
      const speaking = speakUntil > now;
      if (speaking) animating = true;
      const pulse = speaking ? 1 - (speakUntil - now) / SPEECH_PULSE_MS : 0;

      drawAgent(ctx, a, ax, ay, agentR, speaking, pulse);
    });

    // Place labels on top — always readable above agent clusters.
    ctx.save();
    ctx.font = 'bold 10px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    places.forEach((p) => {
      const c = placePx.get(p.id)!;
      const accent = (PLACE_STYLES[p.kind] ?? PLACE_STYLES.social).accent;
      const ly = c.y + bSize / 2 + 5;
      const label = p.name.toUpperCase();
      // Legibility plate behind the text.
      const w = ctx.measureText(label).width;
      ctx.fillStyle = 'rgba(10,10,11,0.7)';
      ctx.fillRect(c.x - w / 2 - 3, ly - 1, w + 6, 12);
      ctx.fillStyle = accent;
      ctx.fillText(label, c.x, ly);
    });
    ctx.restore();

    // Tick / day overlay.
    ctx.save();
    ctx.font = '10px "IBM Plex Mono", monospace';
    ctx.fillStyle = '#3a3a50';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`TICK ${world.tick}  DAY ${world.day}`, W - 8, H - 6);
    ctx.restore();

    return animating;
  }, []);

  // Drive the loop only while animation is needed.
  const tick = useCallback(() => {
    const more = renderFrame();
    rafRef.current = more ? requestAnimationFrame(tick) : 0;
  }, [renderFrame]);

  const kick = useCallback(() => {
    if (!rafRef.current) rafRef.current = requestAnimationFrame(tick);
  }, [tick]);

  // New world state → animate agents toward their (possibly new) places.
  useEffect(() => { kick(); }, [world, kick]);

  // New speech events → start/refresh speaking pulses (skip historical backlog).
  useEffect(() => {
    if (events.length === 0) return;
    const maxSeq = events[0].seq;
    if (maxSeq <= lastSpeechSeqRef.current) return;
    if (lastSpeechSeqRef.current < 0) { lastSpeechSeqRef.current = maxSeq; return; }
    const now = Date.now();
    for (const e of events) {
      if (e.seq <= lastSpeechSeqRef.current) break;
      if (e.kind === 'agent_speech' && e.actor_id) {
        speakingRef.current.set(e.actor_id, now + SPEECH_PULSE_MS);
      }
    }
    lastSpeechSeqRef.current = maxSeq;
    kick();
  }, [events, kick]);

  // Redraw on resize (one frame, plus a kick if anything is mid-animation).
  useEffect(() => {
    const observer = new ResizeObserver(() => { renderFrame(); kick(); });
    if (containerRef.current) observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [renderFrame, kick]);

  // Initial paint + cleanup.
  useEffect(() => {
    kick();
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [kick]);

  return (
    <div ref={containerRef} className="relative w-full h-full bg-lab-bg">
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full"
        aria-label="World map — agent positions"
      />
    </div>
  );
}

// ── Drawing helpers ───────────────────────────────────────────────────────────

function drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number) {
  ctx.save();
  ctx.strokeStyle = '#15151b';
  ctx.lineWidth = 1;
  const step = Math.max(40, w / 12);
  for (let x = step; x < w; x += step) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let y = step; y < h; y += step) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }
  ctx.restore();
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function drawBuilding(
  ctx: CanvasRenderingContext2D,
  kind: keyof typeof PLACE_STYLES,
  cx: number,
  cy: number,
  size: number,
) {
  const style = PLACE_STYLES[kind] ?? PLACE_STYLES.social;
  const half = size / 2;
  ctx.save();

  // Soft ground shadow
  ctx.beginPath();
  ctx.ellipse(cx, cy + half * 0.85, half * 1.15, half * 0.5, 0, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(0,0,0,0.35)';
  ctx.fill();

  // Building footprint (body) with roof-accent border = same colors as 3D.
  roundRect(ctx, cx - half, cy - half, size, size, size * 0.18);
  ctx.fillStyle = style.body;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = style.accent;
  ctx.stroke();

  // Inner roof square (accent) so it reads as a little house from above.
  const inner = size * 0.46;
  roundRect(ctx, cx - inner / 2, cy - inner / 2, inner, inner, inner * 0.22);
  ctx.fillStyle = style.accent;
  ctx.fill();

  ctx.restore();
}

function drawAgent(
  ctx: CanvasRenderingContext2D,
  agent: { name: string; energy: number; credits: number; alive: boolean; profile_color?: string },
  ax: number,
  ay: number,
  r: number,
  speaking: boolean,
  pulse: number,
) {
  const color = agent.profile_color ?? '#888888';
  ctx.save();
  if (!agent.alive) ctx.globalAlpha = 0.25;

  // Speaking pulse — an expanding fading ring (mirrors the 3D chat bubble).
  if (speaking && agent.alive) {
    ctx.beginPath();
    ctx.arc(ax, ay, r + 4 + pulse * 10, 0, Math.PI * 2);
    ctx.strokeStyle = color + 'aa';
    ctx.globalAlpha = Math.max(0, 0.6 * (1 - pulse));
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // Energy ring
  const energyAngle = (Math.max(0, Math.min(100, agent.energy)) / 100) * Math.PI * 2;
  ctx.beginPath();
  ctx.arc(ax, ay, r + 3, -Math.PI / 2, -Math.PI / 2 + energyAngle);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.lineCap = 'round';
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(ax, ay, r + 3, -Math.PI / 2 + energyAngle, 1.5 * Math.PI);
  ctx.strokeStyle = '#252530';
  ctx.lineWidth = 2.5;
  ctx.lineCap = 'butt';
  ctx.stroke();

  // Body
  ctx.beginPath();
  ctx.arc(ax, ay, r, 0, Math.PI * 2);
  ctx.fillStyle = color + '33';
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // Initials
  ctx.font = `600 ${Math.round(r * 0.7)}px "IBM Plex Mono", monospace`;
  ctx.fillStyle = color;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(agent.name.slice(0, 2).toUpperCase(), ax, ay);

  // Credits pip
  if (agent.credits > 0 && agent.alive) {
    const px = ax + r - 1, py = ay + r - 1;
    ctx.beginPath();
    ctx.arc(px, py, Math.max(5, r * 0.4), 0, Math.PI * 2);
    ctx.fillStyle = '#c8ff00';
    ctx.fill();
    ctx.font = `bold ${Math.round(r * 0.42)}px "IBM Plex Mono", monospace`;
    ctx.fillStyle = '#0a0a0b';
    ctx.fillText(agent.credits > 99 ? '99+' : String(agent.credits), px, py + 0.5);
  }

  ctx.restore();
}
