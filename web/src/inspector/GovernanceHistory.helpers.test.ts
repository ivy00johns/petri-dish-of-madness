/**
 * GovernanceHistory helpers (W11b EM-087) — pure-logic tests for the ×N
 * identical-effect grouping (`groupTimeline`) and renewal detection
 * (`renewalsByRule`). The headline scenario is HISTORICAL 3×UBI-shaped data:
 * runs persisted before the backend's renewal semantics hold three
 * simultaneously-active identical effects, and the panel must collapse them
 * into one ×3 row with no backend support.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { groupTimeline, renewalsByRule } from './GovernanceHistory';
import type { GovTimelineEntry } from './types';
import { ev, resetSeq } from '../test-utils/fixtures';

function entry(
  partial: Partial<GovTimelineEntry> & { ruleId: string },
): GovTimelineEntry {
  return {
    effect: 'ubi',
    text: 'Everyone deserves a basic income',
    proposerId: 'agent_a',
    status: 'active',
    createdTick: 0,
    votes: [],
    resolvedTick: null,
    outcome: 'passed',
    downstream: [],
    ...partial,
  };
}

beforeEach(() => resetSeq());

describe('groupTimeline — identical-effect ACTIVE stacking (EM-087)', () => {
  it('collapses 3 identical-effect active rules into one ×3 stack (the 3×UBI data)', () => {
    const timeline = [
      entry({ ruleId: 'ubi-1', createdTick: 10 }),
      entry({ ruleId: 'ubi-2', createdTick: 40 }),
      entry({ ruleId: 'ubi-3', createdTick: 90 }),
    ];
    const items = groupTimeline(timeline);
    expect(items).toHaveLength(1);
    expect(items[0].entry.ruleId).toBe('ubi-1'); // the earliest instance leads
    expect(items[0].stack.map((e) => e.ruleId)).toEqual(['ubi-1', 'ubi-2', 'ubi-3']);
  });

  it('keeps non-active entries of the same effect as individual rows', () => {
    const timeline = [
      entry({ ruleId: 'ubi-active' }),
      entry({ ruleId: 'ubi-rejected', status: 'rejected', outcome: 'rejected' }),
      entry({ ruleId: 'ubi-floor', status: 'proposed', outcome: null }),
    ];
    const items = groupTimeline(timeline);
    expect(items.map((i) => i.entry.ruleId)).toEqual([
      'ubi-active',
      'ubi-rejected',
      'ubi-floor',
    ]);
    // A lone active is a stack of one — no ×N badge territory.
    expect(items[0].stack).toHaveLength(1);
  });

  it('does not group across different effects', () => {
    const timeline = [
      entry({ ruleId: 'ubi-1', effect: 'ubi' }),
      entry({ ruleId: 'ban-1', effect: 'ban_stealing', text: 'No stealing' }),
    ];
    const items = groupTimeline(timeline);
    expect(items).toHaveLength(2);
    expect(items.every((i) => i.stack.length === 1)).toBe(true);
  });

  it('actives with a null effect never stack (render individually)', () => {
    const timeline = [
      entry({ ruleId: 'x1', effect: null }),
      entry({ ruleId: 'x2', effect: null }),
    ];
    const items = groupTimeline(timeline);
    expect(items).toHaveLength(2);
  });

  it('preserves original timeline order around a stack', () => {
    const timeline = [
      entry({ ruleId: 'ban-1', effect: 'ban_stealing', status: 'rejected', outcome: 'rejected' }),
      entry({ ruleId: 'ubi-1' }),
      entry({ ruleId: 'work-1', effect: 'work_bonus' }),
      entry({ ruleId: 'ubi-2' }), // folds into ubi-1's stack
    ];
    expect(groupTimeline(timeline).map((i) => i.entry.ruleId)).toEqual([
      'ban-1',
      'ubi-1',
      'work-1',
    ]);
  });
});

describe('renewalsByRule — rule_passed{renewed:true} detection (EM-087)', () => {
  it('collects renewals per rule_id, sorted by tick', () => {
    const events = [
      ev({ kind: 'rule_passed', tick: 90, payload: { renewed: true, rule_id: 'ubi-1' } }),
      ev({ kind: 'rule_passed', tick: 40, payload: { renewed: true, rule_id: 'ubi-1' } }),
      ev({ kind: 'rule_passed', tick: 55, payload: { renewed: true, rule_id: 'ban-1' } }),
    ];
    const map = renewalsByRule(events);
    expect(map.get('ubi-1')?.map((r) => r.tick)).toEqual([40, 90]);
    expect(map.get('ban-1')).toHaveLength(1);
  });

  it('ignores fresh enactments, other kinds, and rows missing rule_id', () => {
    const events = [
      // A fresh PASSED (no renewed flag) is not a renewal.
      ev({ kind: 'rule_passed', tick: 10, payload: { rule_id: 'ubi-1' } }),
      // renewed must be EXACTLY true.
      ev({ kind: 'rule_passed', tick: 11, payload: { renewed: 'yes', rule_id: 'ubi-1' } }),
      // Wrong kind.
      ev({ kind: 'rule_proposed', tick: 12, payload: { renewed: true, rule_id: 'ubi-1' } }),
      // Missing / non-string rule_id.
      ev({ kind: 'rule_passed', tick: 13, payload: { renewed: true } }),
      ev({ kind: 'rule_passed', tick: 14, payload: { renewed: true, rule_id: 7 } }),
    ];
    expect(renewalsByRule(events).size).toBe(0);
  });
});
