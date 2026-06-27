/**
 * Wave G (EM-197) — the viewport-fit data-dense annex (contract §G2), as
 * carried forward through Wave M (EM-204) — the tabbed IA.
 *
 * EM-204 grouped the formerly-flat 9-panel grid into four TABS (Forensics /
 * Society / Chaos / Runs); only the active tab's panels mount. The wave-G
 * layout law is UNCHANGED and still structurally pinned per tab (jsdom can't
 * lay out, so the class sets ARE the contract):
 *
 *  1. NO PAGE SCROLL at ≥1024px — the annex root pins h-dvh + overflow-hidden;
 *     the active tab's panel area absorbs the remaining viewport (flex-1
 *     min-h-0, lg:overflow-hidden) and every panel scrolls INTERNALLY.
 *  2. EMPTY PANELS COLLAPSE to a slim strip (zero-state text + expand
 *     affordance); data arriving auto-expands; siblings reclaim the space.
 *  3. The fixed chrome (status strip + scrub strip + the new tab bar) stays
 *     OUTSIDE the grid, ABOVE the tab body — switching tabs never scrolls the
 *     scrub away.
 *
 * Rendered against a 3k-event run so the structural assertions hold at the
 * volume the contract names (1440×900 / 3k events).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { InspectorLayout } from './InspectorLayout';
import { ev, resetSeq } from '../test-utils/fixtures';
import type { WorldEvent } from '../types';

beforeEach(() => {
  resetSeq();
  // RunBrowser fetches /api/runs on mount; a rejected fetch resolves to the
  // labeled "no backend" state (inspectorApi catches) — fine for these tests.
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** A 3k-event run: speech + animal chaos (with dialogue) + governance. */
function bigHistory(opts: { governance?: boolean; animals?: boolean } = {}): WorldEvent[] {
  const { governance = true, animals = true } = opts;
  const out: WorldEvent[] = [];
  for (let i = 0; i < 3000; i++) {
    const tick = Math.floor(i / 10);
    if (animals && i % 7 === 0) {
      out.push(
        ev({
          kind: 'animal_action',
          tick,
          actor_id: 'cat_1',
          actor_type: 'animal',
          text: `mischief #${i}`,
          payload:
            i % 14 === 0
              ? { species: 'cat', action: 'knock_over', animal_thought: `offends me #${i}` }
              : { species: 'cat', action: 'wander' },
        }),
      );
    } else if (i % 13 === 0) {
      // Real turn chains so the Decision Trace rail mounts its virtual list.
      out.push(
        ev({
          kind: 'turn_start',
          tick,
          actor_id: 'a1',
          turn_id: `turn-${i}`,
          text: `turn #${i}`,
        }),
      );
    } else if (governance && i % 211 === 0) {
      out.push(
        ev({
          kind: 'rule_proposed',
          tick,
          actor_id: 'a1',
          text: `proposal #${i}`,
          payload: { rule_id: `rule-${i}`, effect: 'ubi' },
        }),
      );
    } else {
      out.push(ev({ kind: 'agent_speech', tick, actor_id: 'a1', text: `line #${i}` }));
    }
  }
  return out.reverse(); // newest-first, the history convention
}

function renderAnnex(history: WorldEvent[]) {
  return render(
    <InspectorLayout
      world={null}
      history={history}
      historyLoading={false}
      historyTruncated={false}
      mockMode={true}
    />,
  );
}

/** Click a section tab by its visible label. */
function goToTab(name: RegExp) {
  fireEvent.click(screen.getByRole('tab', { name }));
}

describe('InspectorLayout — viewport-fit grid at a 3k-event run (wave G §G2.1 / EM-204)', () => {
  it('the annex root pins the no-page-scroll rules (h-dvh + overflow-hidden)', () => {
    renderAnnex(bigHistory());
    const main = screen.getByRole('main');
    for (const cls of ['h-dvh', 'max-h-full', 'min-h-0', 'overflow-hidden', 'flex', 'flex-col']) {
      expect(main.classList.contains(cls), `main missing ${cls}`).toBe(true);
    }
  });

  it('the active tab area absorbs the remaining viewport; page scroll only <1024', () => {
    renderAnnex(bigHistory());
    const grid = screen.getByTestId('inspector-grid');
    for (const cls of [
      'grid',
      'flex-1',
      'min-h-0',
      'grid-cols-1', // <1024 stacked fallback…
      'overflow-y-auto', // …the ONLY scrolling mode
      'lg:overflow-hidden', // ≥1024: the area never scrolls — panels do
    ]) {
      expect(grid.classList.contains(cls), `grid missing ${cls}`).toBe(true);
    }
  });

  it('the Forensics tab lays the map beside the trace in a 2-up grid ≥1280px', () => {
    renderAnnex(bigHistory());
    // Default tab is Forensics — map + decision trace, two columns at xl.
    const map = screen.getByLabelText('Replay map (EM-055)');
    const inner = map.closest('.xl\\:grid-cols-2');
    expect(inner, 'Forensics inner grid missing xl:grid-cols-2').not.toBeNull();
    expect(screen.getByLabelText('Decision trace (EM-056)')).toBeInTheDocument();
  });

  it('every data panel mounts with its OWN internal scroll container (per tab)', () => {
    renderAnnex(bigHistory());
    // Forensics: decision-trace turn rail is a virtualized internal scroller +
    // the replay map renders inside its cell.
    expect(screen.getAllByTestId('virtual-list').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByLabelText('Replay map (EM-055)')).toBeInTheDocument();

    // Society: governance timeline owns an overflow-y-auto list; social graph
    // renders inside its cell.
    goToTab(/society/i);
    const gov = screen.getByLabelText('Governance & laws history (EM-057)');
    const govScroller = gov.querySelector('ol');
    expect(govScroller).not.toBeNull();
    expect(govScroller!.classList.contains('overflow-y-auto')).toBe(true);
    expect(govScroller!.classList.contains('min-h-0')).toBe(true);
    expect(screen.getByLabelText('Social graph (EM-058)')).toBeInTheDocument();

    // Chaos: the critter feed's virtual scroller.
    goToTab(/chaos/i);
    expect(screen.getAllByTestId('virtual-list').length).toBeGreaterThanOrEqual(1);
  });

  it('the scrub strip + tab bar are FIXED chrome outside the grid (never scroll away)', () => {
    renderAnnex(bigHistory());
    const strip = screen.getByLabelText('Replay scrubber (EM-055)');
    const tablist = screen.getByRole('tablist', { name: /inspector sections/i });
    const grid = screen.getByTestId('inspector-grid');
    expect(grid.contains(strip)).toBe(false);
    expect(grid.contains(tablist)).toBe(false);
    expect(strip.classList.contains('shrink-0')).toBe(true);
    expect(tablist.classList.contains('shrink-0')).toBe(true);
    expect(screen.getByLabelText('Scrub to tick')).toBeInTheDocument();
  });
});

describe('InspectorLayout — empty panels collapse to slim strips (wave G §G2.2 / EM-204)', () => {
  it('governance at 0 rules renders the strip; the panel is unmounted', () => {
    renderAnnex(bigHistory({ governance: false }));
    goToTab(/society/i);
    const strip = screen.getByRole('region', { name: /governance · laws \(empty, collapsed\)/i });
    // Zero-state says what would fill it.
    expect(within(strip).getByText(/no laws yet — proposals from town hall/i)).toBeInTheDocument();
    expect(within(strip).getByText('0')).toBeInTheDocument();
    expect(screen.queryByLabelText('Governance & laws history (EM-057)')).not.toBeInTheDocument();
  });

  it('the expand affordance opens the empty panel (and can re-collapse it)', () => {
    renderAnnex(bigHistory({ governance: false }));
    goToTab(/society/i);
    fireEvent.click(
      screen.getByRole('button', { name: /expand the empty governance · laws panel/i }),
    );
    expect(screen.getByLabelText('Governance & laws history (EM-057)')).toBeInTheDocument();
    expect(screen.getAllByText(/no proposals yet/i).length).toBeGreaterThan(0);
    fireEvent.click(
      screen.getByRole('button', { name: /collapse the empty governance · laws panel/i }),
    );
    expect(screen.queryByLabelText('Governance & laws history (EM-057)')).not.toBeInTheDocument();
  });

  it('a rule existing expands governance automatically (no strip)', () => {
    renderAnnex(bigHistory({ governance: true }));
    goToTab(/society/i);
    expect(screen.getByLabelText('Governance & laws history (EM-057)')).toBeInTheDocument();
    expect(
      screen.queryByRole('region', { name: /governance · laws \(empty, collapsed\)/i }),
    ).not.toBeInTheDocument();
  });

  it('chaos at 0 animal events collapses; with critter data it mounts in full', () => {
    renderAnnex(bigHistory({ animals: false }));
    goToTab(/chaos/i);
    expect(
      screen.getByRole('region', { name: /animal chaos feed \(empty, collapsed\)/i }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('Animal Chaos Feed (EM-065)')).not.toBeInTheDocument();
  });

  it('with critter data the chaos panel mounts in full (no strip)', () => {
    renderAnnex(bigHistory({ animals: true }));
    goToTab(/chaos/i);
    expect(screen.getByLabelText('Animal Chaos Feed (EM-065)')).toBeInTheDocument();
    expect(
      screen.queryByRole('region', { name: /animal chaos feed \(empty, collapsed\)/i }),
    ).not.toBeInTheDocument();
  });
});
