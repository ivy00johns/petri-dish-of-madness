/**
 * The Blind Lineup (EM-309) — panel + masking integration.
 *
 * Renders the guess card together with a real consumer (the ModelLegend) inside
 * one BlindLineupProvider so the reveal wiring is exercised end-to-end: while a
 * round is live every model NAME reads ???; REVEAL flips them to their real
 * models and grades the round; the per-family scorecard persists to
 * localStorage. Also proves the flag gates the whole feature OFF by default.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BlindLineupProvider } from './BlindLineupContext';
import { BlindLineupPanel } from './BlindLineupPanel';
import { ModelLegend } from '../legend/ModelLegend';
import { loadScorecard } from '../../lib/blindLineup';
import { agent, profile, world } from '../../test-utils/fixtures';

const PROFILES = [
  profile({ name: 'groq-llama', model_id: 'llama-3.3-70b-versatile', color: '#e74c3c' }),
  profile({ name: 'gemini-flash', model_id: 'gemini-2.0-flash-exp', color: '#3498db' }),
];

const WORLD = world({
  profiles: PROFILES,
  // First-seen agent.profile order fixes the slot order: A = llama, B = gemini.
  agents: [
    agent({ id: 'a1', name: 'Ada', profile: 'groq-llama', profile_color: '#e74c3c' }),
    agent({ id: 'a2', name: 'Bo', profile: 'gemini-flash', profile_color: '#3498db' }),
  ],
});

function renderWithFlag() {
  return render(
    <BlindLineupProvider>
      <BlindLineupPanel world={WORLD} />
      <ModelLegend profiles={PROFILES} />
    </BlindLineupProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('BlindLineupPanel — flag gating', () => {
  it('renders NOTHING and masks NOTHING when the flag is off (default)', () => {
    renderWithFlag(); // no VITE_BLIND_LINEUP stub
    expect(screen.queryByText(/BLIND LINEUP/i)).not.toBeInTheDocument();
    // The legend shows real model names — no masking with the flag off.
    expect(screen.getByText('groq-llama')).toBeInTheDocument();
    expect(screen.queryByText('???')).not.toBeInTheDocument();
  });
});

describe('BlindLineupPanel — the round (flag on)', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_BLIND_LINEUP', '1');
  });

  it('hides every model name behind ??? while the round is live', () => {
    renderWithFlag();
    expect(screen.getByText(/BLIND LINEUP/i)).toBeInTheDocument();
    // The legend's model names + ids are hidden.
    expect(screen.queryByText('groq-llama')).not.toBeInTheDocument();
    expect(screen.queryByText('llama-3.3-70b-versatile')).not.toBeInTheDocument();
    expect(screen.getAllByText('???').length).toBe(2);
    // The guess card shows anonymous slots + a guess control per slot.
    expect(screen.getByText('Model A')).toBeInTheDocument();
    expect(screen.getByText('Model B')).toBeInTheDocument();
    expect(screen.getByLabelText('Guess for Model A')).toBeInTheDocument();
  });

  it('reveals real models, grades the round, and persists a per-family scorecard', async () => {
    const user = userEvent.setup();
    renderWithFlag();

    // Guess both correctly: A is llama, B is gemini.
    await user.selectOptions(screen.getByLabelText('Guess for Model A'), 'llama');
    await user.selectOptions(screen.getByLabelText('Guess for Model B'), 'gemini');
    expect(screen.getByText('2/2 guessed')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /reveal/i }));

    // Chips flipped: real names now visible (legend + panel), score shown.
    expect(screen.getAllByText('groq-llama').length).toBeGreaterThan(0);
    expect(screen.getByText('You matched 2/2')).toBeInTheDocument();
    expect(screen.queryByText('???')).not.toBeInTheDocument();

    // Scorecard accumulated + persisted.
    expect(screen.getByText(/accuracy by family/i)).toBeInTheDocument();
    const sc = loadScorecard();
    expect(sc.llama).toEqual({ seen: 1, correct: 1 });
    expect(sc.gemini).toEqual({ seen: 1, correct: 1 });
  });

  it('marks a wrong guess with ✗ and scores it 0', async () => {
    const user = userEvent.setup();
    renderWithFlag();

    await user.selectOptions(screen.getByLabelText('Guess for Model A'), 'gemini'); // wrong
    await user.click(screen.getByRole('button', { name: /reveal/i }));

    // 2 slots in the lineup; only A was answered and it was wrong ⇒ 0 of 2.
    expect(screen.getByText('You matched 0/2')).toBeInTheDocument();
    const sc = loadScorecard();
    // Actual family of slot A is llama; guessed gemini ⇒ llama seen 1 correct 0.
    expect(sc.llama).toEqual({ seen: 1, correct: 0 });
    // Slot B went unanswered — it must NOT be folded into the scorecard.
    expect(sc.gemini).toBeUndefined();
  });

  it('New round re-hides the chips and clears guesses', async () => {
    const user = userEvent.setup();
    renderWithFlag();

    await user.selectOptions(screen.getByLabelText('Guess for Model A'), 'llama');
    await user.click(screen.getByRole('button', { name: /reveal/i }));
    expect(screen.getByText(/You matched/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /new round/i }));

    // Masked again, selects back, guess reset to the placeholder.
    expect(screen.getAllByText('???').length).toBe(2);
    const selectA = screen.getByLabelText('Guess for Model A') as HTMLSelectElement;
    expect(selectA.value).toBe('');
  });

  it('shows a labeled empty state when no models are in play', () => {
    render(
      <BlindLineupProvider>
        <BlindLineupPanel world={world({ profiles: PROFILES, agents: [] })} />
      </BlindLineupProvider>,
    );
    expect(screen.getByText(/No models on stage yet/i)).toBeInTheDocument();
  });
});
