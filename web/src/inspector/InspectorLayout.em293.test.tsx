/**
 * EM-293 — Inspector tab bar completes the ARIA tabs pattern (offline review
 * 2026-07-01).
 *
 * The EM-204 tab bar used ARIA tab roles (tablist / tab / tabpanel) with none of
 * the required wiring: no roving tabindex, no arrow-key navigation, no ids, no
 * aria-controls / aria-labelledby linking tab ⇄ panel. These pins assert the
 * completed pattern:
 *   • roving tabindex (only the active tab is in the Tab order),
 *   • each tab aria-controls the one reused tabpanel; the panel is
 *     aria-labelledby the active tab,
 *   • Left/Right cycle (wrapping) and Home/End jump, with selection following
 *     focus.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { InspectorLayout } from './InspectorLayout';
import { ev, resetSeq } from '../test-utils/fixtures';
import type { WorldEvent } from '../types';

beforeEach(() => {
  resetSeq();
  // RunBrowser fetches /api/runs on mount; a rejected fetch resolves to the
  // labeled "no backend" state — fine for these tests.
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function history(): WorldEvent[] {
  return [ev({ kind: 'turn_start', tick: 0, actor_id: 'a1', turn_id: 't0', text: 't0' })];
}

function renderAnnex() {
  return render(<InspectorLayout world={null} history={history()} mockMode={true} />);
}

function tab(name: RegExp): HTMLElement {
  return screen.getByRole('tab', { name });
}

describe('InspectorLayout tabs — ARIA wiring (EM-293)', () => {
  it('roving tabindex: only the active tab is in the Tab order', () => {
    renderAnnex();
    expect(tab(/forensics/i)).toHaveAttribute('tabindex', '0');
    for (const name of [/society/i, /chaos/i, /runs/i]) {
      expect(tab(name)).toHaveAttribute('tabindex', '-1');
    }
  });

  it('each tab controls the single tabpanel; the panel is labelled by the active tab', () => {
    renderAnnex();
    const panel = screen.getByRole('tabpanel');
    const panelId = panel.getAttribute('id');
    expect(panelId).toBeTruthy();

    const forensics = tab(/forensics/i);
    expect(forensics.id).toBeTruthy();
    // Every tab points at the one reused panel.
    for (const name of [/forensics/i, /society/i, /chaos/i, /runs/i]) {
      expect(tab(name)).toHaveAttribute('aria-controls', panelId as string);
    }
    // The panel names its active tab (roving as selection changes).
    expect(panel).toHaveAttribute('aria-labelledby', forensics.id);
    expect(panel).toHaveAccessibleName(/forensics/i);
  });

  it('ArrowRight moves selection + focus to the next tab', () => {
    renderAnnex();
    const forensics = tab(/forensics/i);
    forensics.focus();
    fireEvent.keyDown(forensics, { key: 'ArrowRight' });

    const society = tab(/society/i);
    expect(society).toHaveAttribute('aria-selected', 'true');
    expect(society).toHaveFocus();
    expect(society).toHaveAttribute('tabindex', '0');
    expect(tab(/forensics/i)).toHaveAttribute('tabindex', '-1');
  });

  it('ArrowLeft from the first tab wraps to the last', () => {
    renderAnnex();
    const forensics = tab(/forensics/i);
    forensics.focus();
    fireEvent.keyDown(forensics, { key: 'ArrowLeft' });

    const runs = tab(/runs/i);
    expect(runs).toHaveAttribute('aria-selected', 'true');
    expect(runs).toHaveFocus();
  });

  it('Home and End jump to the first / last tab', () => {
    renderAnnex();
    const forensics = tab(/forensics/i);
    forensics.focus();

    fireEvent.keyDown(forensics, { key: 'End' });
    expect(tab(/runs/i)).toHaveFocus();
    expect(tab(/runs/i)).toHaveAttribute('aria-selected', 'true');

    fireEvent.keyDown(tab(/runs/i), { key: 'Home' });
    expect(tab(/forensics/i)).toHaveFocus();
    expect(tab(/forensics/i)).toHaveAttribute('aria-selected', 'true');
  });
});
