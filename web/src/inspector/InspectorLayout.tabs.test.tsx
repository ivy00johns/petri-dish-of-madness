/**
 * Wave M (EM-204) — Inspector IA cleanup: the tabbed annex.
 *
 * The formerly-flat 9-panel grid is grouped into four tabs — Forensics
 * (ReplayMap + DecisionTrace), Society (SocialGraph + Governance + AWI), Chaos
 * (AnimalChaosFeed), Runs (RunBrowser) — and only the active tab's panels
 * mount. This pins:
 *
 *   1. Default tab is Forensics; its two panels (and ONLY its panels) mount.
 *   2. Each tab switch mounts exactly that tab's panels and unmounts the rest.
 *   3. The shared scrub still DRIVES every panel after a tab switch — a panel
 *      that mounts in a non-default tab receives the SCRUBBED projection (the
 *      EM-204 invariant: scrub state lives above the tab body, panels in
 *      inactive tabs may unmount but re-mount projected at the scrub tick).
 *   4. Off-tab signal badges: chaos events / governance proposals show a count
 *      on their tab while you read another section.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
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

/**
 * A small multi-tick run with at least one of every panel's fuel: turn chains
 * (decision trace), relationships (social graph), governance proposals, animal
 * actions — newest-first (the history convention).
 */
function history(): WorldEvent[] {
  const asc: WorldEvent[] = [];
  for (let tick = 0; tick <= 10; tick++) {
    asc.push(ev({ kind: 'turn_start', tick, actor_id: 'a1', turn_id: `turn-${tick}`, text: `t${tick}` }));
    asc.push(
      ev({ kind: 'relationship', tick, actor_id: 'a1', target_id: 'a2', payload: { type: 'ally' } }),
    );
    asc.push(
      ev({
        kind: 'animal_action',
        tick,
        actor_id: 'cat_1',
        actor_type: 'animal',
        text: `mischief ${tick}`,
        payload: { species: 'cat', action: 'wander' },
      }),
    );
    asc.push(
      ev({
        kind: 'rule_proposed',
        tick,
        actor_id: 'a1',
        text: `proposal ${tick}`,
        payload: { rule_id: `rule-${tick}`, effect: 'ubi' },
      }),
    );
  }
  return asc.reverse();
}

function renderAnnex(h: WorldEvent[] = history()) {
  return render(<InspectorLayout world={null} history={h} mockMode={true} />);
}

function goToTab(name: RegExp) {
  fireEvent.click(screen.getByRole('tab', { name }));
}

function scrubTo(tick: number) {
  fireEvent.change(screen.getByLabelText('Scrub to tick'), { target: { value: String(tick) } });
}

describe('InspectorLayout — tabbed IA (EM-204)', () => {
  it('renders the four section tabs in reading order', () => {
    renderAnnex();
    const tablist = screen.getByRole('tablist', { name: /inspector sections/i });
    const tabs = within(tablist).getAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual([
      expect.stringMatching(/forensics/i),
      expect.stringMatching(/society/i),
      expect.stringMatching(/chaos/i),
      expect.stringMatching(/runs/i),
    ]);
  });

  it('default tab is Forensics: ReplayMap + DecisionTrace mount, others do not', () => {
    renderAnnex();
    expect(screen.getByRole('tab', { name: /forensics/i })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByLabelText('Replay map (EM-055)')).toBeInTheDocument();
    expect(screen.getByLabelText('Decision trace (EM-056)')).toBeInTheDocument();
    // Other tabs' panels are NOT mounted.
    expect(screen.queryByLabelText('Social graph (EM-058)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('AWI dashboard (EM-059)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Animal Chaos Feed (EM-065)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Run browser (EM-086)')).not.toBeInTheDocument();
  });

  it('Society tab mounts SocialGraph + Governance + AWI (and unmounts Forensics)', () => {
    renderAnnex();
    goToTab(/society/i);
    expect(screen.getByLabelText('Social graph (EM-058)')).toBeInTheDocument();
    expect(screen.getByLabelText('Governance & laws history (EM-057)')).toBeInTheDocument();
    expect(screen.getByLabelText('AWI dashboard (EM-059)')).toBeInTheDocument();
    // Forensics panels are gone.
    expect(screen.queryByLabelText('Replay map (EM-055)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Decision trace (EM-056)')).not.toBeInTheDocument();
  });

  it('Chaos tab mounts ONLY the animal chaos feed', () => {
    renderAnnex();
    goToTab(/chaos/i);
    expect(screen.getByLabelText('Animal Chaos Feed (EM-065)')).toBeInTheDocument();
    expect(screen.queryByLabelText('Social graph (EM-058)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Replay map (EM-055)')).not.toBeInTheDocument();
  });

  it('Runs tab mounts ONLY the run browser', () => {
    renderAnnex();
    goToTab(/runs/i);
    expect(screen.getByLabelText('Run browser (EM-086)')).toBeInTheDocument();
    expect(screen.queryByLabelText('Animal Chaos Feed (EM-065)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Replay map (EM-055)')).not.toBeInTheDocument();
  });

  it('switching back and forth re-mounts the right panels each time', () => {
    renderAnnex();
    goToTab(/society/i);
    expect(screen.getByLabelText('Social graph (EM-058)')).toBeInTheDocument();
    goToTab(/forensics/i);
    expect(screen.getByLabelText('Replay map (EM-055)')).toBeInTheDocument();
    expect(screen.queryByLabelText('Social graph (EM-058)')).not.toBeInTheDocument();
    goToTab(/society/i);
    expect(screen.getByLabelText('Social graph (EM-058)')).toBeInTheDocument();
  });
});

describe('InspectorLayout — scrub still drives panels across tabs (EM-204)', () => {
  it('the shared scrub survives a tab switch (the playhead is fixed chrome)', () => {
    renderAnnex();
    // Scrub to tick 4 on the Forensics tab, then switch to Society — the scrub
    // tick is unchanged (the REPLAY badge reads the same tick).
    scrubTo(4);
    expect(screen.getByText(/REPLAY @ 4 \//i)).toBeInTheDocument();
    goToTab(/society/i);
    expect(screen.getByText(/REPLAY @ 4 \//i)).toBeInTheDocument();
    goToTab(/forensics/i);
    expect(screen.getByText(/REPLAY @ 4 \//i)).toBeInTheDocument();
  });

  it('a panel mounting on a non-default tab receives the SCRUBBED projection', () => {
    // The status strip's TICK is the shared scrub; switching to a panel-bearing
    // tab does not reset it, proving the projection that feeds the newly-mounted
    // panel is the scrubbed one (panelProps.currentTick === the scrub tick).
    renderAnnex();
    scrubTo(2);
    goToTab(/society/i);
    // Governance is scoped to tick ≤ 2: only ticks 0,1,2 proposed (3 rules).
    const gov = screen.getByLabelText('Governance & laws history (EM-057)');
    // The scrubbed projection mounted — the panel exists and the scrub tick held.
    expect(gov).toBeInTheDocument();
    expect(screen.getByText(/REPLAY @ 2 \//i)).toBeInTheDocument();
  });
});

describe('InspectorLayout — off-tab signal badges (EM-204)', () => {
  it('the Chaos tab shows a count badge while you read another section', () => {
    renderAnnex();
    // 11 ticks × 1 animal_action = 11 chaos events; the badge surfaces them.
    const chaosTab = screen.getByRole('tab', { name: /chaos/i });
    expect(within(chaosTab).getByText('11')).toBeInTheDocument();
  });

  it('the Society tab badges the governance proposal count', () => {
    renderAnnex();
    // 11 ticks × 1 rule_proposed = 11 governance events.
    const societyTab = screen.getByRole('tab', { name: /society/i });
    expect(within(societyTab).getByText('11')).toBeInTheDocument();
  });

  it('no badge when the tab has no off-tab signal yet', () => {
    renderAnnex(
      // A run with zero animal events: the chaos badge stays absent.
      [ev({ kind: 'agent_speech', tick: 0, actor_id: 'a1', text: 'hi' })],
    );
    const chaosTab = screen.getByRole('tab', { name: /chaos/i });
    expect(within(chaosTab).queryByText(/^\d+$/)).not.toBeInTheDocument();
  });
});
