/**
 * PersonaPicker (W11b EM-092) — component smoke for the persona-library cards:
 * the four labeled states (§7 idiom — loading / mock-idle / unreachable /
 * empty, never a blank), card rendering with the suggested-profile chip, and
 * pick / deselect semantics (clicking the active card returns to freeform).
 */
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PersonaPicker } from './PersonaPicker';
import type { PersonaRow } from '../../inspector/api';
import { profile } from '../../test-utils/fixtures';

const MOX: PersonaRow = {
  name: 'Mox',
  archetype: 'Conspiracy Theorist',
  personality: 'Reads hidden messages in billboard typos.',
  suggested_profile: 'qwen-next',
};
const VESPER: PersonaRow = {
  name: 'Vesper',
  archetype: 'Serial Entrepreneur',
  personality: 'Eleven ventures, ten abandoned.',
  suggested_profile: '',
};

const PROFILES = [profile({ name: 'qwen-next', color: '#ff00aa' })];

function renderPicker(
  state: Parameters<typeof PersonaPicker>[0]['state'],
  selected: string | null = null,
) {
  const onPick = vi.fn();
  render(
    <PersonaPicker state={state} selected={selected} profiles={PROFILES} onPick={onPick} />,
  );
  return { onPick };
}

describe('PersonaPicker — labeled states (§7)', () => {
  it('labels mock mode (idle) as no-backend, freeform still works', () => {
    renderPicker({ status: 'idle' });
    expect(
      screen.getByText(/no backend \(mock mode\) — persona library unavailable/),
    ).toBeInTheDocument();
  });

  it('labels an unreachable backend distinctly', () => {
    renderPicker({ status: 'unreachable' });
    expect(
      screen.getByText(/persona library unreachable \(\/api\/personas\)/),
    ).toBeInTheDocument();
  });

  it('labels an EMPTY library distinctly from failure', () => {
    renderPicker({ status: 'ready', personas: [] });
    expect(
      screen.getByText(/the persona library is empty \(config\/personas\.yaml\)/),
    ).toBeInTheDocument();
  });

  it('labels the loading state', () => {
    renderPicker({ status: 'loading' });
    expect(screen.getByText(/loading personas from \/api\/personas/)).toBeInTheDocument();
  });
});

describe('PersonaPicker — cards + pick semantics', () => {
  it('renders cards with archetype, personality and the suggested-profile chip', () => {
    renderPicker({ status: 'ready', personas: [MOX, VESPER] });
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getAllByRole('option')).toHaveLength(2);
    expect(screen.getByText('Mox')).toBeInTheDocument();
    expect(screen.getByText('Conspiracy Theorist')).toBeInTheDocument();
    expect(screen.getByText(MOX.personality)).toBeInTheDocument();
    // The suggested-profile chip — data-driven color, only when the card has one.
    expect(screen.getByText('⌁ qwen-next')).toBeInTheDocument();
    expect(screen.queryByText(/⌁\s*$/)).not.toBeInTheDocument();
  });

  it('clicking a card picks it; clicking the ACTIVE card deselects (null)', async () => {
    const user = userEvent.setup();
    const { onPick } = renderPicker({ status: 'ready', personas: [MOX] }, 'Mox');
    const card = screen.getByRole('option', { name: /Mox/ });
    expect(card).toHaveAttribute('aria-selected', 'true');
    await user.click(card);
    expect(onPick).toHaveBeenLastCalledWith(null); // active card → freeform
  });

  it('clicking an inactive card hands the full PersonaRow to onPick', async () => {
    const user = userEvent.setup();
    const { onPick } = renderPicker({ status: 'ready', personas: [MOX, VESPER] });
    await user.click(screen.getByRole('option', { name: /Vesper/ }));
    expect(onPick).toHaveBeenLastCalledWith(VESPER);
  });
});
