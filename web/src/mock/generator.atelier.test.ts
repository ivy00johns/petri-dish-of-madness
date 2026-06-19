/**
 * Mock-generator atelier tests (Wave I / EM-210/211/213).
 *
 * The offline demo substrate must render the atelier with no backend:
 *   • the initial world_state seeds a gallery + a promoted plaza_banner_ref
 *     that resolves to a gallery image;
 *   • gallery image urls are RELATIVE (/assets/images/<id>.png) — no host;
 *   • generateTick eventually synthesizes image_posted events whose payload
 *     carries {image_id, prompt, url, place}, and the gallery grows;
 *   • a reset clears the atelier state and re-seeds it.
 *
 * The generator keeps module-level mutable state, so each test resets first.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { buildInitialWorldState, generateTick, mockControls } from './generator';

beforeEach(() => {
  mockControls.reset();
});

describe('atelier mock data (EM-210/213)', () => {
  it('seeds a gallery on the initial world_state', () => {
    const w = buildInitialWorldState();
    expect(Array.isArray(w.gallery)).toBe(true);
    expect(w.gallery!.length).toBeGreaterThan(0);
    const img = w.gallery![0];
    expect(typeof img.image_id).toBe('string');
    expect(typeof img.prompt).toBe('string');
    expect(typeof img.proposer_id).toBe('string');
    expect(typeof img.created_tick).toBe('number');
    expect(typeof img.promoted).toBe('boolean');
  });

  it('seeds a plaza_banner_ref that resolves to a gallery image', () => {
    const w = buildInitialWorldState();
    expect(w.plaza_banner_ref).toBeTruthy();
    const promoted = w.gallery!.find((g) => g.image_id === w.plaza_banner_ref);
    expect(promoted).toBeDefined();
    expect(promoted!.promoted).toBe(true);
    // The resolved url is RELATIVE — no hardcoded host.
    expect(promoted!.url.startsWith('/assets/images/')).toBe(true);
    expect(promoted!.url.endsWith('.png')).toBe(true);
  });

  it('every gallery url is a relative /assets/images path', () => {
    const w = buildInitialWorldState();
    for (const img of w.gallery!) {
      expect(img.url).toMatch(/^\/assets\/images\/.+\.png$/);
    }
  });

  it('synthesizes image_posted events over time, growing the gallery', () => {
    buildInitialWorldState();
    const seeded = generateTick().state.gallery!.length;

    let posted: ReturnType<typeof generateTick>['events'][number] | undefined;
    let latest = seeded;
    for (let i = 0; i < 400 && !posted; i++) {
      const { state, events } = generateTick();
      latest = state.gallery!.length;
      posted = events.find((e) => e.kind === 'image_posted');
    }

    expect(posted, 'expected at least one image_posted within 400 ticks').toBeDefined();
    // The gallery grew past the seed count once art was painted.
    expect(latest).toBeGreaterThan(seeded);

    const p = posted!.payload as Record<string, unknown>;
    expect(typeof p.image_id).toBe('string');
    expect(typeof p.prompt).toBe('string');
    expect(typeof p.place).toBe('string');
    expect(String(p.url)).toMatch(/^\/assets\/images\/.+\.png$/);
    // image_posted is authored by a human agent (the painter), not the system.
    expect(posted!.actor_id).toBeTruthy();
  });

  it('resets the atelier state and re-seeds it', () => {
    buildInitialWorldState();
    // Advance so the gallery diverges from the seed, then reset.
    for (let i = 0; i < 50; i++) generateTick();
    const fresh = mockControls.reset();
    expect(fresh.plaza_banner_ref).toBeTruthy();
    expect(fresh.gallery!.length).toBeGreaterThan(0);
    // The re-seeded ids restart from the seed (deterministic), not the run tail.
    expect(fresh.gallery![0].image_id).toBe('img_0000000001');
  });
});
