/**
 * BannerFade + TopBannerLayer (W11b EM-107) — layout-stable top banners.
 *
 * The top banners (routing-degraded / recovered, usage alerts, extinction)
 * used to mount IN FLOW, so every appearance/clearing reflowed the entire app
 * below them — with the routing banner's hysteresis flapping, the UI visibly
 * "zoomed" up and down. The fix is structural:
 *
 *   • `TopBannerLayer` renders the banner stack as an OVERLAY — absolutely
 *     positioned at the top of the app shell, above content. Content
 *     underneath NEVER moves: banner appearance/disappearance shifts zero
 *     pixels. The layer itself is pointer-events-none; each visible banner
 *     re-enables pointer events on its own row only.
 *   • `BannerFade` is the presence wrapper every top banner renders through:
 *     a short OPACITY-ONLY fade (180ms) on enter/exit — never height or
 *     transform (that's the "zoom" feeling). While fading out it keeps the
 *     last-rendered content so the text doesn't blank mid-fade.
 *
 * prefers-reduced-motion: the global index.css override already forces every
 * CSS transition to ~0ms, making the fade instant; the JS unmount delay also
 * checks the media query so an exiting banner is REMOVED immediately instead
 * of lingering invisibly for the fade window.
 *
 * Because the banners overlay translucent-tinted surfaces (bg-lab-warn/10
 * etc.), each fade wrapper carries a solid bg-lab-bg backing so the tints
 * composite exactly as they did in flow. Token-only styling.
 */

import { useEffect, useRef, useState } from 'react';

/** Opacity fade duration (ms) — keep in sync with .banner-fade in index.css. */
const FADE_MS = 180;

function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false; // jsdom / older environments: treat as no preference
  }
}

/**
 * Presence wrapper: mounts children while `show`, fades opacity on enter and
 * exit, and unmounts after the exit fade (immediately under reduced motion).
 * Initial render is synchronous (no enter fade on first paint), so tests and
 * SSR see the banner immediately.
 */
export function BannerFade({ show, children }: { show: boolean; children: React.ReactNode }) {
  const [mounted, setMounted] = useState(show);
  const [visible, setVisible] = useState(show);
  // Keep the last real content so an exiting banner doesn't blank mid-fade
  // (its data — e.g. health.model — may already be gone upstream).
  const lastChildrenRef = useRef(children);
  if (show) lastChildrenRef.current = children;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (show) {
      setMounted(true);
      // Two-phase so the opacity transition actually runs on (re-)enter.
      const raf = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(raf);
    }
    setVisible(false);
    const delay = prefersReducedMotion() ? 0 : FADE_MS;
    timerRef.current = setTimeout(() => {
      setMounted(false);
      timerRef.current = null;
    }, delay);
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [show]);

  if (!mounted) return null;

  return (
    <div
      // Semantics follow `show` SYNCHRONOUSLY: an exiting banner leaves the
      // accessibility tree (and role queries / screen readers) the instant
      // it's dismissed — only the visual opacity fade lingers.
      aria-hidden={show ? undefined : true}
      className={`banner-fade bg-lab-bg ${
        visible ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
      }`}
    >
      {show ? children : lastChildrenRef.current}
    </div>
  );
}

/**
 * The overlay stack at the top of the app shell. Parent must be
 * `position: relative`. Multiple banners stack vertically inside it
 * (routing + usage + extinction can co-occur), each individually
 * dismissible; the layer never participates in layout.
 */
export function TopBannerLayer({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="absolute inset-x-0 top-0 z-40 pointer-events-none flex flex-col"
      role="presentation"
    >
      {children}
    </div>
  );
}
