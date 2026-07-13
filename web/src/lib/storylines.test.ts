/**
 * storylines (EM-312) — the ZERO-LLM drama scorer. Pure-logic tests over a
 * synthetic event log + world projection: the recurrence gate, the three named
 * archetypes (RIVALRY / REDEMPTION / POWER_GRAB), escalation bands, verbatim
 * beats, the both-endpoints-are-agents guard, input-order determinism, and the
 * two-threshold hysteresis + cap.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { agent, ev, resetSeq, world } from '../test-utils/fixtures';
import type { WorldEvent } from '../types';
import {
  scoreStorylines,
  applyHysteresis,
  MAX_STORYLINES,
  type Storyline,
} from './storylines';

beforeEach(() => resetSeq());

const W = world({
  agents: [
    agent({ id: 'a1', name: 'Ada' }),
    agent({ id: 'a2', name: 'Vesper II' }),
    agent({ id: 'a3', name: 'Mara' }),
  ],
});

function conflict(actor: string, target: string, tick: number, text: string): WorldEvent {
  return ev({ kind: 'conflict', actor_id: actor, target_id: target, tick, text });
}

describe('scoreStorylines — recurrence gate', () => {
  it('returns nothing with an empty log', () => {
    expect(scoreStorylines([], W)).toEqual([]);
    expect(scoreStorylines([], null)).toEqual([]);
  });

  it('does NOT promote a one-tick burst (fails MIN_TICKS)', () => {
    const h = [
      conflict('a1', 'a2', 5, 'Ada shoves Vesper'),
      conflict('a1', 'a2', 5, 'Ada shoves Vesper again'),
      conflict('a1', 'a2', 5, 'and again'),
    ];
    expect(scoreStorylines(h, W)).toEqual([]);
  });

  it('does NOT promote two events (fails MIN_EVENTS)', () => {
    const h = [conflict('a1', 'a2', 1, 'x'), conflict('a1', 'a2', 2, 'y')];
    expect(scoreStorylines(h, W)).toEqual([]);
  });
});

describe('scoreStorylines — RIVALRY', () => {
  it('promotes a recurring hostile pair as RIVALRY / TENSION', () => {
    const h = [
      conflict('a1', 'a2', 1, 'Ada insults Vesper II'),
      conflict('a1', 'a2', 3, 'Vesper II retaliates'),
      conflict('a1', 'a2', 5, 'a scuffle in the plaza'),
    ];
    const s = scoreStorylines(h, W);
    expect(s).toHaveLength(1);
    expect(s[0].kind).toBe('RIVALRY');
    expect(s[0].id).toBe('dyad:a1~a2');
    expect(s[0].title).toBe('Ada v. Vesper II');
    expect(s[0].status).toBe('TENSION');
    expect(s[0].principals).toEqual(['a1', 'a2']);
    expect(s[0].principalNames).toEqual(['Ada', 'Vesper II']);
  });

  it('escalates to FEUD past the heat band', () => {
    const h = [
      conflict('a1', 'a2', 1, 'a'),
      conflict('a1', 'a2', 2, 'b'),
      conflict('a1', 'a2', 3, 'c'),
      conflict('a1', 'a2', 4, 'd'),
    ];
    const s = scoreStorylines(h, W);
    expect(s[0].status).toBe('FEUD'); // 4×3 = 12 ≥ FEUD_BAND
  });

  it('keeps beats VERBATIM, newest-first, capped', () => {
    const h = [
      conflict('a1', 'a2', 1, 'first blow'),
      conflict('a1', 'a2', 2, 'second blow'),
      conflict('a1', 'a2', 3, 'third blow'),
    ];
    const s = scoreStorylines(h, W);
    expect(s[0].beats.map((b) => b.text)).toEqual([
      'third blow', 'second blow', 'first blow',
    ]);
  });
});

describe('scoreStorylines — REDEMPTION', () => {
  it('flips a hostile pair that later makes up into REDEMPTION', () => {
    const h = [
      conflict('a1', 'a2', 1, 'Ada accuses Vesper II'),
      ev({ kind: 'jailed', actor_id: 'a1', target_id: 'a2', tick: 2, text: 'Vesper II is jailed' }),
      ev({ kind: 'released', actor_id: 'a1', target_id: 'a2', tick: 8, text: 'Ada frees Vesper II' }),
      ev({
        kind: 'relationship_changed', actor_id: 'a1', target_id: 'a2', tick: 9,
        text: 'Ada and Vesper II become allies', payload: { to_type: 'ally' },
      }),
    ];
    const s = scoreStorylines(h, W);
    expect(s).toHaveLength(1);
    expect(s[0].kind).toBe('REDEMPTION');
    expect(s[0].id).toBe('dyad:a1~a2'); // SAME stable container as the rivalry
    expect(s[0].title).toBe('Ada & Vesper II');
    expect(['MENDING', 'RECONCILED']).toContain(s[0].status);
  });
});

describe('scoreStorylines — POWER_GRAB', () => {
  it('names a single agent amassing power', () => {
    const h = [
      ev({ kind: 'faction_formed', actor_id: 'a3', tick: 1, text: 'Mara founds the Iron Circle' }),
      ev({ kind: 'recruited', actor_id: 'a3', target_id: 'a1', tick: 2, text: 'Mara recruits Ada' }),
      ev({ kind: 'rule_proposed', actor_id: 'a3', tick: 3, text: 'Mara proposes a curfew' }),
    ];
    const s = scoreStorylines(h, W);
    const grab = s.find((x) => x.kind === 'POWER_GRAB');
    expect(grab).toBeDefined();
    expect(grab!.id).toBe('grab:a3');
    expect(grab!.title).toBe("Mara's Power Grab");
    expect(grab!.principals).toContain('a3');
    expect(grab!.principals).toContain('a1'); // recruited ally pulled in
  });

  it('does NOT fire on routine rule chatter alone (below PROMOTE)', () => {
    const h = [
      ev({ kind: 'rule_proposed', actor_id: 'a3', tick: 1, text: 'p1' }),
      ev({ kind: 'rule_proposed', actor_id: 'a3', tick: 2, text: 'p2' }),
      ev({ kind: 'rule_proposed', actor_id: 'a3', tick: 3, text: 'p3' }),
    ];
    // 3×1 = 3 < PROMOTE(6); it clears the gate but not the promote bar.
    const grab = scoreStorylines(h, W).find((x) => x.kind === 'POWER_GRAB');
    const active = grab ? applyHysteresis([grab], new Set()) : [];
    expect(active).toEqual([]);
  });
});

describe('scoreStorylines — agent guard + determinism', () => {
  it('ignores crimes/conflicts targeting a BUILDING (not an agent)', () => {
    const h = [
      ev({ kind: 'crime_committed', actor_id: 'a1', target_id: 'b1', tick: 1, text: 'Ada vandalizes the mill' }),
      ev({ kind: 'conflict', actor_id: 'a1', target_id: 'b1', tick: 2, text: 'Ada torches the mill' }),
      ev({ kind: 'crime_committed', actor_id: 'a1', target_id: 'b1', tick: 3, text: 'Ada loots the mill' }),
    ];
    expect(scoreStorylines(h, W)).toEqual([]); // b1 is not an agent id
  });

  it('is deterministic regardless of input order', () => {
    const build = () => [
      conflict('a1', 'a2', 1, 'a'),
      conflict('a1', 'a2', 2, 'b'),
      conflict('a1', 'a2', 3, 'c'),
      ev({ kind: 'faction_formed', actor_id: 'a3', tick: 1, text: 'circle' }),
      ev({ kind: 'settlement_founded', actor_id: 'a3', tick: 2, text: 'a new ward' }),
      ev({ kind: 'recruited', actor_id: 'a3', target_id: 'a1', tick: 3, text: 'recruit' }),
    ];
    resetSeq();
    const forward = scoreStorylines(build(), W);
    resetSeq();
    const src = build();
    const shuffled = [src[4], src[0], src[5], src[2], src[1], src[3]];
    const back = scoreStorylines(shuffled, W);
    expect(back).toEqual(forward);
  });
});

describe('applyHysteresis — two thresholds + cap', () => {
  const mk = (id: string, score: number): Storyline => ({
    id, kind: 'RIVALRY', title: id, status: 'TENSION', score,
    principals: [], principalNames: [], beats: [], firstTick: 0, lastTick: 0,
  });

  it('requires PROMOTE for a new thread but keeps an active one to DEMOTE', () => {
    const c = [mk('x', 5)]; // between demote(4) and promote(6)
    expect(applyHysteresis(c, new Set())).toEqual([]);               // new: excluded
    expect(applyHysteresis(c, new Set(['x']))).toEqual([mk('x', 5)]); // sticky: kept
  });

  it('drops an active thread once it decays below DEMOTE', () => {
    expect(applyHysteresis([mk('x', 3)], new Set(['x']))).toEqual([]);
  });

  it('caps the visible set', () => {
    const many = Array.from({ length: MAX_STORYLINES + 3 }, (_, i) => mk(`s${i}`, 10));
    expect(applyHysteresis(many, new Set())).toHaveLength(MAX_STORYLINES);
  });
});
