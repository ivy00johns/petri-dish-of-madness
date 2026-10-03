/**
 * panelCollapse — the shared left-column collapse storage (feed primacy,
 * 2026-10-03). Pins the one-time migration: the pre-fix panels persisted '0'
 * (expanded) ON MOUNT, so every browser that loaded the old UI carries stale
 * expanded pins — including ones poisoned during a hot reload AFTER the new
 * code shipped. The marker makes the new collapsed default a ONE-TIME
 * migration; after it, the user's explicit choices always win.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { loadPanelCollapsed, savePanelCollapsed } from './panelCollapse';

beforeEach(() => {
  localStorage.clear();
});

describe('loadPanelCollapsed — the one-time default migration', () => {
  it('defaults COLLAPSED pre-migration even with a stale expanded pin', () => {
    // The poison case: the pre-fix persist-on-mount wrote '0' on every load.
    localStorage.setItem('em.test.collapsed', '0');
    expect(loadPanelCollapsed('em.test.collapsed')).toBe(true);
  });

  it('respects a persisted expand after the migration marker is set', () => {
    localStorage.setItem('em.panelDefaults.v2', '1');
    localStorage.setItem('em.test.collapsed', '0');
    expect(loadPanelCollapsed('em.test.collapsed')).toBe(false);
  });

  it('respects a persisted collapse after the migration marker is set', () => {
    localStorage.setItem('em.panelDefaults.v2', '1');
    localStorage.setItem('em.test.collapsed', '1');
    expect(loadPanelCollapsed('em.test.collapsed')).toBe(true);
  });

  it('defaults collapsed for a never-saved key post-migration', () => {
    localStorage.setItem('em.panelDefaults.v2', '1');
    expect(loadPanelCollapsed('em.never.saved')).toBe(true);
  });
});

describe('savePanelCollapsed — persisting the user choice', () => {
  it('writes the flag and sets the migration marker', () => {
    savePanelCollapsed('em.test.collapsed', false);
    expect(localStorage.getItem('em.test.collapsed')).toBe('0');
    expect(localStorage.getItem('em.panelDefaults.v2')).toBe('1');
    expect(loadPanelCollapsed('em.test.collapsed')).toBe(false); // user wins
  });

  it('round-trips a collapsed choice', () => {
    savePanelCollapsed('em.test.collapsed', true);
    expect(loadPanelCollapsed('em.test.collapsed')).toBe(true);
  });
});
