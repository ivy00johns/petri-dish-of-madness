/**
 * Wave D2 (EM-159/166) — the subtle ⟳ reflex marker on feed rows.
 *
 * A background agent's non-salient due turn resolves a zero-LLM reflex
 * routine; its events carry `payload.reflex: true` (additive). The feed marks
 * those rows with a dim "⟳ reflex" chip; normal LLM turns get no marker.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventFeed } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';

beforeEach(() => {
  resetSeq();
  localStorage.clear();
});

describe('EventFeed — reflex turn marker (EM-166)', () => {
  it('marks events carrying payload.reflex: true', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'economy',
            actor_id: 'a1',
            text: 'Cy forages and finds 1 credits.',
            payload: { reflex: true, cadence_tier: 'background', reflex_streak: 2 },
          }),
        ]}
      />,
    );
    expect(screen.getByText('⟳ reflex')).toBeInTheDocument();
  });

  it('does not mark ordinary LLM-turn events', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'economy',
            actor_id: 'a1',
            text: 'Ada works and earns 4 credits.',
            payload: { cadence_tier: 'protagonist' },
          }),
        ]}
      />,
    );
    expect(screen.queryByText('⟳ reflex')).not.toBeInTheDocument();
  });

  it('renders cadence_tier_changed receipts in the default view', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'cadence_tier_changed',
            actor_id: 'a1',
            text: "Cy's cadence tier set to background.",
            payload: { old_tier: 'protagonist', new_tier: 'background' },
          }),
        ]}
      />,
    );
    expect(
      screen.getByText("Cy's cadence tier set to background."),
    ).toBeInTheDocument();
  });
});
