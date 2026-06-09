/**
 * EventFeed smoke (EM-043 / EM-070) — agent_starving rows always read in the
 * warn register (the survival alarm must not blend into the agent's model
 * color), while ordinary rows keep the normal text register.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventFeed } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the feed persists its filter focus
});

describe('EventFeed — agent_starving warning treatment', () => {
  it('gives the starving row the warn text register', () => {
    const events = [
      ev({
        kind: 'agent_starving',
        tick: 7,
        actor_id: 'a1',
        profile: 'model-a',
        profile_color: '#00ff00',
        text: 'Ada is starving',
        payload: { energy: 0, turns_until_death: 3, threshold: 25 },
      }),
      ev({ kind: 'agent_speech', tick: 7, actor_id: 'a2', text: 'lovely day in the plaza' }),
    ];
    render(<EventFeed events={events} />);

    const starvingRow = screen.getByText('Ada is starving');
    expect(starvingRow).toHaveClass('text-lab-warn', 'font-semibold');

    const normalRow = screen.getByText('lovely day in the plaza');
    expect(normalRow).toHaveClass('text-lab-text');
    expect(normalRow).not.toHaveClass('text-lab-warn');
  });

  it('gives world_extinct the danger register', () => {
    const events = [ev({ kind: 'world_extinct', tick: 9, text: 'the last villager has died' })];
    render(<EventFeed events={events} />);
    expect(screen.getByText('the last villager has died')).toHaveClass('text-lab-danger');
  });
});
