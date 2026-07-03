/**
 * EM-292 — cssVar() token reads are cached out of the rAF draw path (offline
 * review 2026-07-01).
 *
 * The token migration moved cssVar() — a fresh getComputedStyle(document.
 * documentElement) per call — into the per-agent WorldMap draw loop (drawAgent
 * reads --lab-border / --lab-acid / --lab-bg per agent, per frame), so a busy
 * village at 60fps did hundreds-to-thousands of computed-style reads/sec. The fix
 * caches each token after its first resolve (the lab palette is a single static
 * :root theme). Tokens stay the source of truth — no hardcoded hex.
 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { cssVar } from './WorldMap';

afterEach(() => vi.restoreAllMocks());

describe('cssVar — cached token reads (EM-292)', () => {
  it('resolves a token ONCE via getComputedStyle, then serves cached reads', () => {
    const spy = vi.spyOn(window, 'getComputedStyle').mockReturnValue({
      getPropertyValue: (name: string) => (name === '--em292-probe' ? ' #123456 ' : ''),
    } as unknown as CSSStyleDeclaration);

    // Simulate the loop hammering the same token (per agent, per frame).
    const values = Array.from({ length: 50 }, () => cssVar('--em292-probe'));

    // Tokens stay the styling source — the resolved (trimmed) value is returned.
    expect(values.every((v) => v === '#123456')).toBe(true);
    // …but getComputedStyle ran at most once, not once per read (the leak fix).
    expect(spy.mock.calls.length).toBeLessThanOrEqual(1);
  });

  it('does NOT cache an unresolved token (retries until the stylesheet applies)', () => {
    const spy = vi.spyOn(window, 'getComputedStyle').mockReturnValue({
      getPropertyValue: () => '',
    } as unknown as CSSStyleDeclaration);

    cssVar('--em292-never-defined-xyz');
    cssVar('--em292-never-defined-xyz');
    // An empty resolve is never memoized, so each call still probes.
    expect(spy.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
