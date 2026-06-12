/**
 * Wave G (EM-197) — the viewport-fit data-dense annex (contract §G2).
 *
 * Layout law, structurally pinned (jsdom can't lay out, so the class sets ARE
 * the contract):
 *
 *  1. NO PAGE SCROLL at ≥1024px — the annex root pins h-dvh + overflow-hidden;
 *     the panel grid absorbs the remaining viewport (flex-1 min-h-0,
 *     lg:overflow-hidden) and every panel scrolls INTERNALLY.
 *  2. EMPTY PANELS COLLAPSE to a slim strip (zero-state text + expand
 *     affordance); data arriving auto-expands; siblings reclaim the space.
 *  3. The fixed chrome (status strip + scrub strip) stays OUTSIDE the grid.
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

describe('InspectorLayout — viewport-fit grid at a 3k-event run (wave G §G2.1)', () => {
  it('the annex root pins the no-page-scroll rules (h-dvh + overflow-hidden)', () => {
    renderAnnex(bigHistory());
    const main = screen.getByRole('main');
    for (const cls of ['h-dvh', 'max-h-full', 'min-h-0', 'overflow-hidden', 'flex', 'flex-col']) {
      expect(main.classList.contains(cls), `main missing ${cls}`).toBe(true);
    }
  });

  it('the panel grid absorbs the remaining viewport; page scroll only <1024', () => {
    renderAnnex(bigHistory());
    const grid = screen.getByTestId('inspector-grid');
    for (const cls of [
      'grid',
      'flex-1',
      'min-h-0',
      'grid-cols-1', // <1024 stacked fallback…
      'overflow-y-auto', // …the ONLY scrolling mode
      'lg:overflow-hidden', // ≥1024: the grid never scrolls — panels do
      'lg:grid-cols-2', // 1024–1279: two columns
      'xl:grid-cols-3', // ≥1280: three columns
    ]) {
      expect(grid.classList.contains(cls), `grid missing ${cls}`).toBe(true);
    }
  });

  it('every data panel mounts with its OWN internal scroll container', () => {
    renderAnnex(bigHistory());
    // Chaos feed + decision-trace turn rail: virtualized internal scrollers.
    expect(screen.getAllByTestId('virtual-list').length).toBeGreaterThanOrEqual(2);
    // Governance timeline: its own overflow-y-auto list.
    const gov = screen.getByLabelText('Governance & laws history (EM-057)');
    const govScroller = gov.querySelector('ol');
    expect(govScroller).not.toBeNull();
    expect(govScroller!.classList.contains('overflow-y-auto')).toBe(true);
    expect(govScroller!.classList.contains('min-h-0')).toBe(true);
    // The replay map + social graph render inside their cells.
    expect(screen.getByLabelText('Replay map (EM-055)')).toBeInTheDocument();
    expect(screen.getByLabelText('Social graph (EM-058)')).toBeInTheDocument();
  });

  it('the scrub strip is FIXED chrome outside the grid (never scrolls away)', () => {
    renderAnnex(bigHistory());
    const strip = screen.getByLabelText('Replay scrubber (EM-055)');
    const grid = screen.getByTestId('inspector-grid');
    expect(grid.contains(strip)).toBe(false);
    expect(strip.classList.contains('shrink-0')).toBe(true);
    expect(screen.getByLabelText('Scrub to tick')).toBeInTheDocument();
  });
});

describe('InspectorLayout — empty panels collapse to slim strips (wave G §G2.2)', () => {
  it('governance at 0 rules renders the strip; the panel is unmounted', () => {
    renderAnnex(bigHistory({ governance: false }));
    const strip = screen.getByRole('region', { name: /governance · laws \(empty, collapsed\)/i });
    // Zero-state says what would fill it.
    expect(within(strip).getByText(/no laws yet — proposals from town hall/i)).toBeInTheDocument();
    expect(within(strip).getByText('0')).toBeInTheDocument();
    expect(screen.queryByLabelText('Governance & laws history (EM-057)')).not.toBeInTheDocument();
  });

  it('the expand affordance opens the empty panel (and can re-collapse it)', () => {
    renderAnnex(bigHistory({ governance: false }));
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
    expect(screen.getByLabelText('Governance & laws history (EM-057)')).toBeInTheDocument();
    expect(
      screen.queryByRole('region', { name: /governance · laws \(empty, collapsed\)/i }),
    ).not.toBeInTheDocument();
  });

  it('chaos at 0 animal events collapses; with critter data it mounts in full', () => {
    renderAnnex(bigHistory({ animals: false }));
    expect(
      screen.getByRole('region', { name: /animal chaos feed \(empty, collapsed\)/i }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('Animal Chaos Feed (EM-065)')).not.toBeInTheDocument();
  });

  it('with critter data the chaos panel mounts in full (no strip)', () => {
    renderAnnex(bigHistory({ animals: true }));
    expect(screen.getByLabelText('Animal Chaos Feed (EM-065)')).toBeInTheDocument();
    expect(
      screen.queryByRole('region', { name: /animal chaos feed \(empty, collapsed\)/i }),
    ).not.toBeInTheDocument();
  });
});
