/**
 * ChronicleView (EM-201) — integration tests for the Chronicle reading room.
 *
 * PRESERVE-EXACTLY hooks:
 *   - data-testid="chapter-prose" textContent contains the chapter text
 *   - buttons with exact text "◀ Prev" and "Next ▶"
 *   - text node exactly "{i+1} / {N}" (unique in the footer counter)
 *   - <select aria-label="Chronicle model"> with first option "Default (free)"
 *   - "Build from history" button POSTs /api/chronicle/build with correct body
 *   - empty state shows text containing "has not yet begun"
 *   - default selection = the LATEST chapter (selected null → last index)
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ChronicleView } from './ChronicleView';
import { readChapters } from './chronicle';
import { ev } from '../../test-utils/fixtures';
import type { WorldState } from '../../types';

// ============================================================
// readChapters (re-exported from chronicle.ts via ChronicleView)
// ============================================================
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

// ============================================================
// ChronicleView — core behaviour
// ============================================================
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

  it('clicking a chapter index entry jumps to that chapter', async () => {
    const history = [
      ev({ kind: 'narrator_summary', text: 'Alpha chapter contents.', tick: 100,
           payload: { from_tick: 0, to_tick: 100 } }),
      ev({ kind: 'narrator_summary', text: 'Beta chapter contents.', tick: 200,
           payload: { from_tick: 100, to_tick: 200 } }),
      ev({ kind: 'narrator_summary', text: 'Gamma chapter contents.', tick: 300,
           payload: { from_tick: 200, to_tick: 300 } }),
    ];
    render(<ChronicleView world={null} history={history} />);
    // Default is latest (chapter 3 = Gamma)
    expect(screen.getByTestId('chapter-prose').textContent).toContain('Gamma chapter');

    // The index shows roman numerals; click "I" entry to jump to chapter 1
    // The index entries are buttons; find the one whose text row1 contains "I"
    // We'll look for an index button that shows the first chapter's title
    const indexButtons = screen.getAllByRole('button');
    // The chapter index button for chapter 1 will have aria-current undefined (not active)
    // and contain the title derived from "Alpha chapter contents."
    const alphaBtn = indexButtons.find(
      (btn) =>
        btn.textContent?.includes('Alpha chapter') &&
        !btn.textContent?.includes('◀') &&
        !btn.textContent?.includes('▶'),
    );
    expect(alphaBtn).toBeTruthy();
    await userEvent.click(alphaBtn!);

    expect(screen.getByTestId('chapter-prose').textContent).toContain('Alpha chapter');
    expect(screen.getByText('1 / 3')).toBeTruthy();
  });

  it('keyboard ArrowLeft/ArrowRight turns pages', async () => {
    const user = userEvent.setup();
    const history = [
      ev({ kind: 'narrator_summary', text: 'Page one text.', tick: 100,
           payload: { from_tick: 0, to_tick: 100 } }),
      ev({ kind: 'narrator_summary', text: 'Page two text.', tick: 200,
           payload: { from_tick: 100, to_tick: 200 } }),
      ev({ kind: 'narrator_summary', text: 'Page three text.', tick: 300,
           payload: { from_tick: 200, to_tick: 300 } }),
    ];
    render(<ChronicleView world={null} history={history} />);
    // starts at latest (page 3)
    expect(screen.getByText('3 / 3')).toBeTruthy();

    // ArrowLeft → page 2
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByText('2 / 3')).toBeTruthy();
    expect(screen.getByTestId('chapter-prose').textContent).toContain('Page two text');

    // ArrowLeft → page 1
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByText('1 / 3')).toBeTruthy();

    // ArrowRight → page 2
    await user.keyboard('{ArrowRight}');
    expect(screen.getByText('2 / 3')).toBeTruthy();
  });

  it('keyboard navigation is ignored when typing in the filter input', async () => {
    const user = userEvent.setup();
    const history = [
      ev({ kind: 'narrator_summary', text: 'Only chapter.', tick: 100,
           payload: { from_tick: 0, to_tick: 100 } }),
      ev({ kind: 'narrator_summary', text: 'Second chapter.', tick: 200,
           payload: { from_tick: 100, to_tick: 200 } }),
    ];
    render(<ChronicleView world={null} history={history} />);
    // Latest = chapter 2
    expect(screen.getByText('2 / 2')).toBeTruthy();

    // Focus the filter input and press ArrowLeft — should NOT navigate
    const filterInput = screen.getByPlaceholderText(/filter chapters/i);
    await user.click(filterInput);
    await user.keyboard('{ArrowLeft}');
    // Still on chapter 2
    expect(screen.getByText('2 / 2')).toBeTruthy();
  });
});

// ============================================================
// Build from history
// ============================================================
describe('Build from history', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('POSTs /api/chronicle/build with the picked model (default = no model)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'building', model: 'kimi' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const world = {
      profiles: [{ name: 'kimi', adapter: 'x', model_id: 'x', color: 'x' }],
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

// ============================================================
// Rebuild all
// ============================================================
describe('Rebuild all', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('POSTs /api/chronicle/build with rebuild:true', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'building' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<ChronicleView world={null} history={[]} />);
    await userEvent.click(screen.getByRole('button', { name: 'Rebuild all' }));

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/chronicle/build',
      expect.objectContaining({ method: 'POST' }),
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ rebuild: true });
    expect(await screen.findByText(/Rebuilding all chapters/i)).toBeTruthy();
  });

  it('POSTs rebuild:true AND the selected model when a model is chosen', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'building' }),
    });
    vi.stubGlobal('fetch', fetchMock);
    const world = {
      profiles: [{ name: 'gemini', adapter: 'x', model_id: 'x', color: 'x' }],
    } as unknown as WorldState;

    render(<ChronicleView world={world} history={[]} />);
    await userEvent.selectOptions(screen.getByLabelText('Chronicle model'), 'gemini');
    await userEvent.click(screen.getByRole('button', { name: 'Rebuild all' }));

    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      rebuild: true,
      model: 'gemini',
    });
  });
});

// ============================================================
// ChaosPanel — payload facts fix (EM-201 follow-on)
// ============================================================
describe('ChaosPanel payload facts', () => {
  it('renders non-zero counts from chapter.chaos even when history buffer is empty', () => {
    // This is the core bug fix: old chapters with no events in the browser
    // history buffer used to show all-zero stats. With a server-stamped
    // chaos payload, the panel must display those facts without any events.
    const payloadChaos = {
      cast: ['Aria', 'Bret', 'Cara'],
      quotes: [{ speaker: 'Aria', said: 'The die is cast.' }],
      laws: ['All debts forgiven.'],
      conflicts: ['Bret and Cara clashed at the market.'],
      deaths: [],
      counts: { spoken: 42, laws: 3, clashes: 7, deaths: 0 },
    };
    const chapterEvent = ev({
      kind: 'narrator_summary',
      text: 'A tumultuous chapter unfolded.',
      tick: 300,
      payload: {
        from_tick: 200,
        to_tick: 300,
        chronicler_version: 2,
        chaos: payloadChaos,
      },
    });

    // No history events in the window at all — simulates the empty-buffer bug
    render(<ChronicleView world={null} history={[chapterEvent]} />);

    // Counts from payload must be shown
    expect(screen.getByText(/SPOKEN\s*42/i)).toBeTruthy();
    expect(screen.getByText(/LAWS\s*3/i)).toBeTruthy();
    expect(screen.getByText(/CLASHES\s*7/i)).toBeTruthy();

    // Cast members from payload (Aria appears twice: cast chip + quote speaker label)
    expect(screen.getAllByText('Aria').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Bret').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Cara').length).toBeGreaterThanOrEqual(1);

    // A memorable line
    expect(screen.getByText(/The die is cast/i)).toBeTruthy();

    // Law text
    expect(screen.getByText(/All debts forgiven/i)).toBeTruthy();
  });

  it('falls back to client chaosFacts when chapter.chaos is absent', () => {
    // A chapter WITHOUT a chaos payload — client reconstruction from history events
    const chapterEvent = ev({
      kind: 'narrator_summary',
      text: 'A quiet chapter.',
      tick: 100,
      payload: { from_tick: 0, to_tick: 100 },
    });
    const speechEvent = ev({
      kind: 'agent_speech',
      text: 'Aria says Hello world.',
      tick: 50,
      actor_id: 'aria',
    });

    render(<ChronicleView world={null} history={[chapterEvent, speechEvent]} />);

    // Client-computed: one speech event → SPOKEN 1
    expect(screen.getByText(/SPOKEN\s*1/i)).toBeTruthy();
    // Cast should include Aria (extracted from text); may also appear as quote speaker
    expect(screen.getAllByText('Aria').length).toBeGreaterThanOrEqual(1);
  });
});
