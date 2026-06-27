/**
 * EM-202 — A/B persona-across-models, the feed surface.
 *
 * The backend tags every A/B agent_spawned event with payload.ab_group (the
 * shared base name). The feed surfaces an "⚗ A/B · {group}" chip on those rows
 * so a spawned variant reads as one of a model-vs-model group, correlated with
 * the existing model chip.
 *
 * Covers:
 *  • an agent_spawned carrying payload.ab_group renders the A/B chip naming the
 *    group;
 *  • a plain agent_spawned (no ab_group) renders NO A/B chip;
 *  • a non-spawn event carrying an ab_group payload key does not get the chip
 *    (the chip is scoped to the spawn event).
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventFeed } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';

beforeEach(() => {
  resetSeq();
  try { localStorage.clear(); } catch { /* ignore */ }
});

describe('EventFeed — A/B group chip (EM-202)', () => {
  it('shows the A/B chip on an agent_spawned variant carrying ab_group', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'agent_spawned',
            profile: 'mistral-small',
            profile_color: '#00ff00',
            text: 'Vesper·mistral spawned (A/B group: Vesper).',
            payload: { ab_group: 'Vesper', name: 'Vesper·mistral', method: 'god' },
          }),
        ]}
      />,
    );
    const chip = screen.getByTitle(/A\/B group “Vesper”/);
    expect(chip).toBeInTheDocument();
    expect(chip).toHaveTextContent(/A\/B · Vesper/);
  });

  it('shows NO A/B chip on a plain agent_spawned (no ab_group)', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'agent_spawned',
            profile: 'mistral-small',
            profile_color: '#00ff00',
            text: 'Fenn joined the village.',
            payload: { name: 'Fenn', method: 'god' },
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/A\/B ·/)).not.toBeInTheDocument();
  });

  it('does not surface the A/B chip on a non-spawn event with an ab_group key', () => {
    render(
      <EventFeed
        events={[
          ev({
            kind: 'agent_action',
            profile: 'mistral-small',
            profile_color: '#00ff00',
            text: 'Vesper·mistral forages.',
            payload: { ab_group: 'Vesper' },
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/A\/B ·/)).not.toBeInTheDocument();
  });
});
