/**
 * MinWidthGate (W11b EM-082) — below 1024px the lab's three-region live
 * layout and the inspector grid both shear apart, so instead of a broken
 * layout BOTH routes render this labeled full-screen gate.
 *
 * `useViewportWide` listens via matchMedia (no resize-thrash) and re-renders
 * only on threshold crossings; the gate also shows the live current width so
 * the user can see how far they are from the threshold while resizing.
 *
 * Token-only styling. The gate is a static, motion-free screen (nothing to
 * disable for prefers-reduced-motion).
 */

import { useEffect, useState } from 'react';

export const MIN_LAB_WIDTH = 1024;

const QUERY = `(min-width: ${MIN_LAB_WIDTH}px)`;

/** True while the viewport is at least MIN_LAB_WIDTH wide. */
export function useViewportWide(): boolean {
  const [wide, setWide] = useState<boolean>(() => {
    try {
      return window.matchMedia(QUERY).matches;
    } catch {
      return true; // environments without matchMedia (jsdom) never gate
    }
  });

  useEffect(() => {
    let mql: MediaQueryList;
    try {
      mql = window.matchMedia(QUERY);
    } catch {
      return;
    }
    const onChange = (e: MediaQueryListEvent) => setWide(e.matches);
    mql.addEventListener('change', onChange);
    setWide(mql.matches);
    return () => mql.removeEventListener('change', onChange);
  }, []);

  return wide;
}

/** Live viewport width readout for the gate (updates while resizing). */
function useViewportWidth(): number {
  const [w, setW] = useState<number>(() => window.innerWidth);
  useEffect(() => {
    const onResize = () => setW(window.innerWidth);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return w;
}

export function MinWidthGate() {
  const width = useViewportWidth();
  return (
    <main
      className="flex flex-col items-center justify-center gap-4 h-screen px-6 text-center bg-lab-bg text-lab-text"
      aria-label="Viewport too narrow for the lab"
    >
      <span className="font-mono text-3xl text-lab-acid" aria-hidden="true">
        ⛶
      </span>
      <h1 className="m-0 font-mono text-base font-bold tracking-widest uppercase text-lab-acid border border-lab-acid px-3 py-1.5">
        THE LAB NEEDS ≥{MIN_LAB_WIDTH}px
      </h1>
      <p className="m-0 max-w-md font-mono text-[12px] leading-relaxed text-lab-muted">
        The live view runs three columns — the event feed, the 3D village, and
        the control panel — and the inspector is a multi-panel analysis grid.
        Below {MIN_LAB_WIDTH}px they collapse into an unreadable mess, so the
        lab waits instead. Widen this window (or rotate / switch to a desktop
        display) and the experiment resumes exactly where it was.
      </p>
      <p className="m-0 font-mono text-[11px] text-lab-dim tabular-nums" role="status">
        current width: <span className="text-lab-text">{width}px</span> · need{' '}
        <span className="text-lab-acid">{Math.max(0, MIN_LAB_WIDTH - width)}px</span> more
      </p>
      <p className="m-0 font-mono text-[10px] text-lab-dim">
        the simulation keeps running while you resize — nothing is lost
      </p>
    </main>
  );
}
