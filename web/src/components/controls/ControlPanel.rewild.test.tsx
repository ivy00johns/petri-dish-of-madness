/**
 * EM-207 H2 — REWILD button in the MENAGERIE god section.
 *
 * Covers:
 *  • The Rewild button renders inside the MENAGERIE section.
 *  • Clicking it calls onRewild with the current count (default 4).
 *  • The count input changes the argument passed to onRewild.
 *  • A flash confirmation appears after a successful rewild ("N critters rewilded").
 *  • The cap-reached message surfaces when the backend reports cap_reached:true.
 *  • The button is disabled while the request is in flight.
 *
 * The inspectorApi module is mocked (same pattern as ControlPanel.god.test.tsx).
 * No network calls are made.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../inspector/api', () => ({
  inspectorApi: {
    personas: vi.fn(async () => []),
    godIntervene: vi.fn(),
    godWhisper: vi.fn(),
    godMiracle: vi.fn(),
  },
}));

import { ControlPanel } from './ControlPanel';
import { agent, profile, world } from '../../test-utils/fixtures';

const PLACES = [
  { id: 'plaza', name: 'Central Plaza', x: 100, y: 100, kind: 'social' as const, description: '' },
];

function renderPanel(onRewild = vi.fn(async () => ({ spawned: 3, cap_reached: false }))) {
  render(
    <ControlPanel
      world={world({ places: PLACES, agents: [agent({ id: 'bram', name: 'Bram' })] })}
      onStart={vi.fn()}
      onPause={vi.fn()}
      onStep={vi.fn()}
      onReset={vi.fn()}
      onSpeed={vi.fn()}
      onReassign={vi.fn()}
      onInject={vi.fn()}
      onSpawn={vi.fn()}
      onSpawnAnimal={vi.fn()}
      onRewild={onRewild}
      onZooEscape={vi.fn(async () => ({ escaped: 0, zoos: 0 }))}
      onBillboardReply={vi.fn()}
      mockMode={false}
      profiles={[profile({ name: 'model-a' })]}
    />,
  );
  return { onRewild };
}

beforeEach(() => vi.clearAllMocks());

describe('MENAGERIE — REWILD button (EM-207 H2)', () => {
  it('renders the REWILD button in the MENAGERIE section', () => {
    renderPanel();
    expect(screen.getByRole('button', { name: /Rewild/i })).toBeInTheDocument();
  });

  it('calls onRewild with the default count (4) when clicked', async () => {
    const user = userEvent.setup();
    const { onRewild } = renderPanel();
    await user.click(screen.getByRole('button', { name: /Rewild/i }));
    expect(onRewild).toHaveBeenCalledTimes(1);
    expect(onRewild).toHaveBeenCalledWith(4);
  });

  it('passes the count input value to onRewild', async () => {
    const user = userEvent.setup();
    const { onRewild } = renderPanel();
    const countInput = screen.getByLabelText('Rewild count');
    await user.tripleClick(countInput);
    await user.keyboard('7');
    await user.click(screen.getByRole('button', { name: /Rewild/i }));
    expect(onRewild).toHaveBeenCalledWith(7);
  });

  it('flashes "N critters rewilded" on success', async () => {
    const user = userEvent.setup();
    renderPanel(vi.fn(async () => ({ spawned: 3, cap_reached: false })));
    await user.click(screen.getByRole('button', { name: /Rewild/i }));
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/3 critters rewilded/),
    );
  });

  it('includes "cap reached" in the flash when cap_reached is true', async () => {
    const user = userEvent.setup();
    renderPanel(vi.fn(async () => ({ spawned: 2, cap_reached: true })));
    await user.click(screen.getByRole('button', { name: /Rewild/i }));
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/cap reached/i),
    );
  });

  it('disables the button while the request is in flight', async () => {
    const user = userEvent.setup();
    let release!: (v: { spawned: number; cap_reached: boolean }) => void;
    const slowRewild = vi.fn(
      () => new Promise<{ spawned: number; cap_reached: boolean }>((res) => { release = res; }),
    );
    renderPanel(slowRewild);
    await user.click(screen.getByRole('button', { name: /Rewild/i }));
    expect(screen.getByRole('button', { name: /Rewild/i })).toBeDisabled();
    release({ spawned: 4, cap_reached: false });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Rewild/i })).toBeEnabled(),
    );
  });
});
