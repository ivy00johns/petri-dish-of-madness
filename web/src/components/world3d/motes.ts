/**
 * motes.ts — EM-127 (partial) ambient dust motes, the pure deterministic math.
 *
 * Golden-hour ambiance: a field of slow warm motes drifting over the city,
 * the floating-pollen/embers you see in low late-afternoon sun. Tuned to the
 * EXISTING golden-hour look (warm, sparse, subtle) — NOT night fireflies — so
 * it adds life without touching the signature lighting/tone. The riskier
 * EM-127 beats that reshape the mood (day/night cycle, Bloom/Vignette, filmic
 * tone-mapping) are deliberately deferred for visual sign-off.
 *
 * The mote FIELD is a pure function of the seed (deterministic scatter); the
 * per-frame drift is a pure function of (mote, time) — clock-driven, purely
 * visual, off the replay surface (like Traffic). Rendered as one THREE.Points
 * (one draw call) by Ambiance.tsx.
 */

import { hashUnit } from './worldSpace';

/** Master switch — flip to false for the pre-EM-127 look (no motes). */
export const AMBIANCE_ENABLED = true;

const TAU = Math.PI * 2;

export interface Mote {
  /** Base position. */
  x: number;
  y: number;
  z: number;
  /** Drift amplitudes (world units) on each axis. */
  ax: number;
  ay: number;
  az: number;
  /** Phase offset so motes don't pulse in unison. */
  phase: number;
  /** Drift rate. */
  speed: number;
}

export interface MoteFieldOpts {
  count?: number;
  /** Half-extent of the scatter square on X/Z (world units). */
  half?: number;
  yMin?: number;
  yMax?: number;
}

/** Deterministic mote field for a seed (replay-stable scatter, EM-155-style). */
export function computeMotes(seed: number, opts: MoteFieldOpts = {}): Mote[] {
  const { count = 120, half = 38, yMin = 0.6, yMax = 9 } = opts;
  const out: Mote[] = [];
  for (let i = 0; i < count; i++) {
    const h = (p: string) => hashUnit(`mote:${seed}:${i}:${p}`);
    out.push({
      x: (h('x') - 0.5) * 2 * half,
      y: yMin + h('y') * (yMax - yMin),
      z: (h('z') - 0.5) * 2 * half,
      ax: 0.3 + h('ax') * 0.9,
      ay: 0.2 + h('ay') * 0.6,
      az: 0.3 + h('az') * 0.9,
      phase: h('phase') * TAU,
      speed: 0.08 + h('speed') * 0.22, // slow
    });
  }
  return out;
}

/** Pure drift position of a mote at time `t` (seconds). */
export function motePosition(m: Mote, t: number): { x: number; y: number; z: number } {
  return {
    x: m.x + Math.sin(t * m.speed + m.phase) * m.ax,
    y: m.y + Math.sin(t * m.speed * 0.7 + m.phase) * m.ay,
    z: m.z + Math.cos(t * m.speed * 0.9 + m.phase) * m.az,
  };
}
