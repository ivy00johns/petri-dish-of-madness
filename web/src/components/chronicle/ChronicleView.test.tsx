/**
 * ChronicleView (EM-201) — the Chronicle tab projects `narrator_summary`
 * chapters into a paginated reading view; degrades to a labelled empty state.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ChronicleView, readChapters } from './ChronicleView';
import { ev } from '../../test-utils/fixtures';
import type { WorldState } from '../../types';

describe('readChapters', () => {
  it('gathers narrator_summary chapters in window order; skips non-chapters + empties', () => {
    const history = [
      ev({ kind: 'narrator_summary', text: 'Chapter two.', tick: 200,
           payload: { from_tick: 100, to_tick: 200 } }),
      ev({ kind: 'agent_speech', text: 'just chatter' }),
      ev({ kind: 'narrator_summary', text: '   ', tick: 50 }),  // empty → skipped
      ev({ kind: 'narrator_summary', text: 'Chapter one.', tick: 100,
           payload: { from_tick: 0, to_tick: 100 } }),
    ];
    expect(readChapters(history).map((c) => c.text)).toEqual([
      'Chapter one.', 'Chapter two.',
    ]);
  });
});

describe('ChronicleView', () => {
  it('shows a labelled empty state before any chapter exists', () => {
    render(<ChronicleView world={null} history={[]} />);
    expect(screen.getByText(/has not yet begun/i)).toBeTruthy();
  });

  it('renders the latest chapter by default and navigates to earlier ones', async () => {
    const history = [
      ev({ kind: 'narrator_summary', text: 'First chapter prose.', tick: 100,
           payload: { from_tick: 0, to_tick: 100 } }),
      ev({ kind: 'narrator_summary', text: 'Latest chapter prose.', tick: 200,
           payload: { from_tick: 100, to_tick: 200 } }),
    ];
    render(<ChronicleView world={null} history={history} />);
    // pinned to the latest
    expect(screen.getByTestId('chapter-prose').textContent).toContain('Latest chapter');
    expect(screen.getByText('2 / 2')).toBeTruthy();

    await userEvent.click(screen.getByText('◀ Prev'));
    expect(screen.getByTestId('chapter-prose').textContent).toContain('First chapter');
    expect(screen.getByText('1 / 2')).toBeTruthy();
  });
});

describe('Build from history', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('POSTs /api/chronicle/build with the picked model (default = no model)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'building', model: 'kimi' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const world = {
      profiles: [{ name: 'kimi', adapter: 'x', model_id: 'x', color: '#fff' }],
    } as unknown as WorldState;

    render(<ChronicleView world={world} history={[]} />);
    await userEvent.selectOptions(screen.getByLabelText('Chronicle model'), 'kimi');
    await userEvent.click(screen.getByRole('button', { name: 'Build from history' }));

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/chronicle/build',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ model: 'kimi' });
    expect(await screen.findByText(/Building from history/i)).toBeTruthy();
  });
});
