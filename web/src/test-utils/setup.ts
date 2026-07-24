/**
 * Vitest setup (EM-043) — jest-dom matchers + the two browser APIs jsdom
 * lacks that the components under test touch defensively:
 *
 *   • ResizeObserver — ReplayScrubber observes its mini-map container.
 *   • HTMLCanvasElement.getContext — jsdom's throws "not implemented"; the
 *     ReplayScrubber draw() already guards a null ctx, so a quiet null stub
 *     keeps the smoke tests about the DOM, not the canvas raster.
 *
 * 2026-07-21 (feed-truth) — localStorage/sessionStorage vs. Node's built-in
 * webStorage global: Node 22+ ships an experimental `globalThis.localStorage`
 * accessor that returns an inert stub (no backing `--localstorage-file`, so
 * `.clear`/`.setItem`/etc. are all undefined). Vitest's jsdom environment
 * (`populateGlobal`, vitest/dist/chunks/index.*.js) only installs a jsdom
 * window property onto the test global when that key is EITHER on its fixed
 * allowlist OR absent from Node's own global — `localStorage` is on neither
 * list, so on a Node build where the native accessor exists it silently
 * wins over jsdom's real implementation (Node 20 has no such global, so it
 * was never a problem there). Force-install jsdom's actual Storage objects
 * (exposed by the environment as `globalThis.jsdom`, vitest's own ambient
 * `jsdom: JSDOM` global — see `vitest/jsdom.d.ts`) over whatever Node left
 * behind, on every Node version, so this is a no-op where jsdom already won.
 */
import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

const realJsdom = (globalThis as { jsdom?: { window: Window } }).jsdom;
if (realJsdom) {
  Object.defineProperty(globalThis, 'localStorage', {
    get: () => realJsdom.window.localStorage,
    configurable: true,
  });
  Object.defineProperty(globalThis, 'sessionStorage', {
    get: () => realJsdom.window.sessionStorage,
    configurable: true,
  });
}

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// matchMedia — uPlot (AWIDashboard's chart lib) calls it at MODULE LOAD to
// track devicePixelRatio; jsdom doesn't implement it. A static no-op MQL is
// enough (wave F: the InspectorLayout render tests import the full panel
// grid, which pulls uPlot in).
if (typeof globalThis.matchMedia === 'undefined') {
  globalThis.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof globalThis.matchMedia;
}

// jsdom raises "Not implemented" for canvas 2D contexts; the components under
// test all null-guard, so return null quietly.
HTMLCanvasElement.prototype.getContext = vi.fn(
  () => null,
) as unknown as typeof HTMLCanvasElement.prototype.getContext;
