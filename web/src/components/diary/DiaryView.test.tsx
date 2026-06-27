/**
 * DiaryView (EM-215) — the per-agent inner-life reading room: the individual
 * cousin to the town Chronicle.
 *
 * PRESERVE-EXACTLY hooks:
 *   - empty state shows text containing "no diary entries" (case-insensitive)
 *   - each agent column carries data-testid="diary-agent-<actorId>"
 *   - reflection lines carry data-testid="diary-entry"
 *   - the inner-life text renders as the entry body
 */
import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { DiaryView } from './DiaryView';
import { groupReflectionsByAgent } from './diary';
import { Header } from '../Header';
import { ev, agent, world } from '../../test-utils/fixtures';
import type { WorldEvent } from '../../types';

// History arrives newest-first from the simulation hook; a diary reads
// oldest→newest within each agent.
function refl(actor_id: string, text: string, tick: number, extra: Partial<WorldEvent> = {}): WorldEvent {
  return ev({
    kind: 'reflection',
    actor_id,
    text,
    tick,
    payload: { text, importance: 0.7 },
    ...extra,
  });
}

// ============================================================
// groupReflectionsByAgent — the grouping/ordering logic
// ============================================================
describe('groupReflectionsByAgent', () => {
  it('groups reflection events by actor and orders each chronologically (oldest→newest)', () => {
    // Mixed newest-first input across two agents, plus non-reflection noise.
    const history: WorldEvent[] = [
      refl('ada', 'Ada later thought.', 30),
      ev({ kind: 'agent_speech', actor_id: 'ada', text: 'just chatter', tick: 25 }),
      refl('bram', 'Bram only thought.', 20),
      refl('ada', 'Ada first thought.', 10),
    ];

    const groups = groupReflectionsByAgent(history);
    // Two agents grouped
    expect(groups.map((g) => g.actorId).sort()).toEqual(['ada', 'bram']);

    const ada = groups.find((g) => g.actorId === 'ada')!;
    // Ada's two reflections, oldest first
    expect(ada.entries.map((e) => e.tick)).toEqual([10, 30]);
    expect(ada.entries[0].text).toContain('Ada first');
    expect(ada.entries[1].text).toContain('Ada later');

    // Non-reflection events never enter a group
    const bram = groups.find((g) => g.actorId === 'bram')!;
    expect(bram.entries).toHaveLength(1);
  });

  it('drops reflections with no actor_id (cannot attribute to a diary)', () => {
    const history: WorldEvent[] = [
      refl('ada', 'attributed', 5),
      ev({ kind: 'reflection', text: 'orphan', tick: 6, payload: { text: 'orphan' } }),
    ];
    const groups = groupReflectionsByAgent(history);
    expect(groups).toHaveLength(1);
    expect(groups[0].actorId).toBe('ada');
  });
});

// ============================================================
// DiaryView — rendering
// ============================================================
describe('DiaryView', () => {
  it('shows a labelled empty state when no reflections exist', () => {
    render(<DiaryView world={world()} history={[]} />);
    expect(screen.getByText(/no diary entries/i)).toBeTruthy();
  });

  it('groups reflections by agent and renders them chronologically', () => {
    const w = world({
      agents: [
        agent({ id: 'ada', name: 'Ada', mood: 'wistful', profile: 'kimi', profile_color: '#c8ff00' }),
        agent({ id: 'bram', name: 'Bram', mood: 'restless', profile: 'gemini' }),
      ],
    });
    const history: WorldEvent[] = [
      refl('ada', 'I fear the plaza grows cold.', 30, { profile: 'kimi', profile_color: '#c8ff00' }),
      refl('bram', 'The market owes me nothing.', 20, { profile: 'gemini' }),
      refl('ada', 'A quiet morning by the fountain.', 10, { profile: 'kimi', profile_color: '#c8ff00' }),
    ];

    render(<DiaryView world={w} history={history} />);

    // One column per agent (keyed by actor id)
    const adaCol = screen.getByTestId('diary-agent-ada');
    const bramCol = screen.getByTestId('diary-agent-bram');
    expect(adaCol).toBeTruthy();
    expect(bramCol).toBeTruthy();

    // The agent's identity surfaces (name + mood)
    expect(within(adaCol).getByText('Ada')).toBeTruthy();
    expect(within(adaCol).getByText(/wistful/i)).toBeTruthy();

    // Ada's two entries appear; chronological (oldest first) inside her column.
    const adaEntries = within(adaCol).getAllByTestId('diary-entry');
    expect(adaEntries).toHaveLength(2);
    expect(adaEntries[0].textContent).toContain('A quiet morning');
    expect(adaEntries[1].textContent).toContain('I fear the plaza');

    // The inner-life text renders.
    expect(within(bramCol).getByText(/The market owes me nothing/)).toBeTruthy();
  });

  it('falls back to a derived name when the agent is absent from the world snapshot', () => {
    // No matching agent in world.agents — DiaryView still renders the column,
    // using the actor_id as the identity label (graceful degradation).
    const history: WorldEvent[] = [refl('ghost', 'Still here, somehow.', 1)];
    render(<DiaryView world={world()} history={history} />);
    const col = screen.getByTestId('diary-agent-ghost');
    expect(within(col).getByText(/ghost/i)).toBeTruthy();
    expect(within(col).getByText(/Still here, somehow/)).toBeTruthy();
  });

  it('lets the reader filter to a single agent via the selector', async () => {
    const w = world({
      agents: [
        agent({ id: 'ada', name: 'Ada' }),
        agent({ id: 'bram', name: 'Bram' }),
      ],
    });
    const history: WorldEvent[] = [
      refl('ada', 'Ada writes.', 10),
      refl('bram', 'Bram writes.', 12),
    ];
    render(<DiaryView world={w} history={history} />);

    // Both columns initially present
    expect(screen.queryByTestId('diary-agent-ada')).toBeTruthy();
    expect(screen.queryByTestId('diary-agent-bram')).toBeTruthy();

    // Pick Ada from the agent selector → only Ada's column remains.
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /filter to one agent/i }),
      'ada',
    );
    expect(screen.queryByTestId('diary-agent-ada')).toBeTruthy();
    expect(screen.queryByTestId('diary-agent-bram')).toBeNull();
  });
});

// ============================================================
// Nav seam (EM-215) — the new Diary tab + /diary route
// ============================================================
describe('Diary nav tab', () => {
  const headerProps = { tick: 0, day: 1, running: false, connected: true, mockMode: false };

  it('renders a Diary nav tab linking to /diary', () => {
    render(
      <MemoryRouter>
        <Header {...headerProps} />
      </MemoryRouter>,
    );
    const tab = screen.getByRole('link', { name: 'Diary' });
    expect(tab).toBeTruthy();
    expect(tab.getAttribute('href')).toBe('/diary');
  });

  it('marks the Diary tab active (aria-current) when on the /diary route', () => {
    render(
      <MemoryRouter initialEntries={['/diary']}>
        <Header {...headerProps} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Diary' }).getAttribute('aria-current')).toBe('page');
  });
});
