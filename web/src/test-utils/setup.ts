/**
 * Vitest setup (EM-043) — jest-dom matchers + the two browser APIs jsdom
 * lacks that the components under test touch defensively:
 *
 *   • ResizeObserver — ReplayScrubber observes its mini-map container.
 *   • HTMLCanvasElement.getContext — jsdom's throws "not implemented"; the
 *     ReplayScrubber draw() already guards a null ctx, so a quiet null stub
 *     keeps the smoke tests about the DOM, not the canvas raster.
 */
import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom raises "Not implemented" for canvas 2D contexts; the components under
// test all null-guard, so return null quietly.
HTMLCanvasElement.prototype.getContext = vi.fn(
  () => null,
) as unknown as typeof HTMLCanvasElement.prototype.getContext;
