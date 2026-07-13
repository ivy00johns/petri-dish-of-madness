/**
 * DramaWire (EM-316) — the feed breaks its own news.
 *
 * A slim rail that rides ABOVE the event feed, gated behind VITE_DRAMA_WIRE
 * (DEFAULT OFF ⇒ renders null, feed byte-identical to today). When on, it shows
 * a live Drama Index sparkline in its header and promotes the rate-capped
 * breaking beats (lib/dramaWire) into red BREAKING interstitial cards. Clicking
 * a card flies the 3-D camera to the scene via the SHIPPED zoom-to-place
 * controls (EM-095) — the ONLY outward effect. It is a DERIVED VIEW with zero
 * sim feedback: it reads history + world and never writes, posts, or injects,
 * so byte-identical replay is untouched.
 *
 * Rate discipline (feed-wins rule): the scorer caps surfaced cards by count +
 * sim-tick spacing so the wire can never crowd raw agent chat. All logic lives
 * in the pure lib; this file is presentation + the camera hand-off only.
 */

import { useMemo } from 'react';
import type { WorldEvent, WorldState, FocusTarget } from '../../types';
import {
  beatFocus,
  dramaBeats,
  dramaIndex,
  dramaSparkline,
  isDramaWireEnabled,
} from '../../lib/dramaWire';

interface DramaWireProps {
  world: WorldState | null;
  /** The deep rolling history (newest-first) — NOT the 200-cap feed. */
  history: WorldEvent[];
  /** Fly the shipped camera to a place/building (EM-095 zoom-to-place). */
  onFocus?: (target: FocusTarget) => void;
}

/** A tiny inline sparkline (design-token stroke, no hardcoded color). */
function Sparkline({ series }: { series: number[] }) {
  const w = 96;
  const h = 16;
  const max = Math.max(1, ...series);
  const n = series.length;
  const pts = series
    .map((v, i) => {
      const x = n <= 1 ? w : (i / (n - 1)) * w;
      const y = h - (v / max) * (h - 2) - 1;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  return (
    <svg
      className="text-lab-danger"
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline
        points={pts}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity="0.85"
      />
    </svg>
  );
}

export function DramaWire({ world, history, onFocus }: DramaWireProps) {
  // Hooks run unconditionally (rules-of-hooks); the flag gates the RENDER.
  const beats = useMemo(() => dramaBeats(history), [history]);
  const index = useMemo(() => dramaIndex(history), [history]);
  const series = useMemo(() => dramaSparkline(history), [history]);

  // Flag gate: DEFAULT OFF ⇒ nothing renders and the feed is byte-identical.
  if (!isDramaWireEnabled()) return null;

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label="Drama Wire — auto-surfaced breaking beats"
    >
      {/* Header: label + live Drama Index sparkline + numeric index. */}
      <div className="lab-header flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5">
          <span aria-hidden="true" className="text-lab-danger">⚡</span>
          DRAMA WIRE
        </span>
        <div className="flex items-center gap-2">
          <Sparkline series={series} />
          <span
            className="font-mono text-[10px] tabular-nums text-lab-danger"
            title="Drama Index — decayed salience of recent typed events (0–100)"
            aria-label={`Drama Index ${index}`}
          >
            {index}
          </span>
        </div>
      </div>

      {/* Breaking cards — rate-capped by the scorer. */}
      {beats.length === 0 ? (
        <div className="px-2 py-1.5 font-mono text-[10px] text-lab-dim">
          Quiet on the wire — no breaking beats.
        </div>
      ) : (
        <ul className="m-0 list-none p-0">
          {beats.map((beat) => {
            const focus = beatFocus(beat, world);
            const canFly = Boolean(focus && onFocus);
            return (
              <li key={beat.seq}>
                <button
                  type="button"
                  disabled={!canFly}
                  onClick={() => {
                    if (focus && onFocus) onFocus(focus);
                  }}
                  aria-label={
                    canFly
                      ? `Fly the camera to ${beat.label}: ${beat.headline}`
                      : `${beat.label}: ${beat.headline} — no place to fly to`
                  }
                  title={
                    canFly
                      ? 'Fly the camera to the scene'
                      : 'No place to fly to for this beat'
                  }
                  className="group flex w-full items-start gap-2 px-2 py-1.5 text-left
                             border-l-[3px] border-lab-danger bg-lab-danger/10
                             hover:bg-lab-danger/20 transition-colors duration-100
                             disabled:cursor-default disabled:opacity-80
                             enabled:cursor-pointer"
                >
                  <span
                    className="flex-none mt-px font-mono text-[9px] font-bold uppercase tracking-wider
                               px-1 py-px rounded-sm border border-lab-danger text-lab-danger whitespace-nowrap"
                  >
                    {beat.label}
                  </span>
                  <span className="flex-1 min-w-0 font-mono text-[11px] leading-snug text-lab-text break-words">
                    {beat.headline}
                    {canFly && (
                      <span
                        aria-hidden="true"
                        className="ml-1 text-lab-danger opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        ⌖
                      </span>
                    )}
                  </span>
                  <span className="flex-none font-mono text-[9px] text-lab-muted tabular-nums mt-px">
                    T{beat.tick}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
