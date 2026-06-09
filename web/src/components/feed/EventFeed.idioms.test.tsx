/**
 * EventFeed W11b idiom smoke (event-log.md v1.3.0 kinds) — the new feed
 * treatments render: 👻 phantom chip on commitment_lapsed{reason:"phantom"}
 * (and ONLY then), ⚑ commitment_made, ✎ reflection in the diary italic,
 * ✦ god chip + god ink on a god billboard post, ↻ renewed chip on
 * rule_passed{renewed:true}, the usage_alert warn register, and the ⑂
 * run_forked icon. Separate file — EventFeed.test.tsx is wave-1/W11a-owned.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventFeed } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the feed persists its filter focus
});

describe('EventFeed — W11b feed idioms', () => {
  it('haunts a PHANTOM commitment_lapsed with the 👻 chip + muted italic', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'commitment_lapsed',
            tick: 12,
            actor_id: 'a1',
            text: 'Ada’s promise lapsed — all talk, no follow-through.',
            payload: { commitment_id: 'c1', text: 'I will build', reason: 'phantom' },
          }),
        ]}
      />,
    );
    expect(screen.getByText('👻 phantom')).toBeInTheDocument();
    expect(screen.getByText('👻')).toBeInTheDocument(); // the icon swap too
    expect(
      screen.getByText('Ada’s promise lapsed — all talk, no follow-through.'),
    ).toHaveClass('italic');
  });

  it('an EXPIRED commitment_lapsed gets no phantom treatment', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'commitment_lapsed',
            tick: 12,
            text: 'a promise quietly expired',
            payload: { commitment_id: 'c1', text: 'x', reason: 'expired' },
          }),
        ]}
      />,
    );
    expect(screen.queryByText('👻 phantom')).not.toBeInTheDocument();
    expect(screen.getByText('⌛')).toBeInTheDocument(); // the default icon
  });

  it('flags commitment_made with the ⚑ icon', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'commitment_made',
            tick: 3,
            actor_id: 'a1',
            text: 'Ada commits: "I will build a garden"',
            payload: { commitment_id: 'c1', text: 'I will build a garden' },
          }),
        ]}
      />,
    );
    expect(screen.getByText('⚑')).toBeInTheDocument();
    expect(screen.getByText(/Ada commits/)).toBeInTheDocument();
  });

  it('renders a reflection in the diary idiom (muted italic)', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'reflection',
            tick: 5,
            actor_id: 'a1',
            text: 'Ada reflects: "I fear the plaza."',
            payload: { text: 'I fear the plaza.', importance: 11 },
          }),
        ]}
      />,
    );
    expect(screen.getByText(/Ada reflects/)).toHaveClass('italic', 'text-lab-muted');
  });

  it('a god billboard post takes GOD INK + the ✦ god chip; agent posts do not', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'billboard_posted',
            tick: 7,
            actor_id: 'god',
            actor_type: 'god',
            text: '📌 GOD posts on the billboard: "behave"',
            payload: { place: 'plaza', text: 'behave' },
          }),
          ev({
            kind: 'billboard_posted',
            tick: 8,
            actor_id: 'a1',
            text: '📌 Ada pins a note to the billboard: "hello"',
            payload: { place: 'plaza', text: 'hello' },
          }),
        ]}
      />,
    );
    expect(screen.getAllByText('✦ god')).toHaveLength(1);
    expect(screen.getByText(/GOD posts on the billboard/)).toHaveStyle({
      color: 'var(--lab-god-bright)',
    });
    expect(screen.getByText(/Ada pins a note/)).toHaveClass('text-lab-text');
  });

  it('marks a RENEWED rule_passed with the ↻ chip; a fresh pass gets none', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'rule_passed',
            tick: 90,
            text: '"Everyone deserves a basic income" (ubi) RENEWED',
            payload: { rule_id: 'r1', effect: 'ubi', renewed: true },
          }),
          ev({
            kind: 'rule_passed',
            tick: 10,
            text: '"No stealing" (ban_stealing) PASSED and is now active!',
            payload: { rule_id: 'r2', effect: 'ban_stealing' },
          }),
        ]}
      />,
    );
    expect(screen.getAllByText('↻ renewed')).toHaveLength(1);
  });

  it('usage_alert reads in the warn register like the other alarms', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'usage_alert',
            tick: 40,
            text: 'groq usage crossed 70% of its rpd day cap (1000).',
            payload: { provider: 'groq', metric: 'rpd', pct: 70, limit: 1000 },
          }),
        ]}
      />,
    );
    expect(screen.getByText(/groq usage crossed 70%/)).toHaveClass(
      'text-lab-warn',
      'font-semibold',
    );
  });

  it('run_forked rows carry the ⑂ lineage icon', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'run_forked',
            tick: 0,
            actor_type: 'system',
            text: 'forked from run #4 @ tick 26',
            payload: { parent_run_id: 4, tick: 26 },
          }),
        ]}
      />,
    );
    expect(screen.getByText('⑂')).toBeInTheDocument();
    expect(screen.getByText(/forked from run #4/)).toBeInTheDocument();
  });
});
