/**
 * EM-208 H3 — Zoo escape button in the MENAGERIE god section.
 *
 * Covers:
 *  • The "Zoo escape" button renders inside the MENAGERIE section.
 *  • Clicking it POSTs /api/god/zoo_escape (calls onZooEscape).
 *  • A flash confirmation appears: "N animals escaped!" on success.
 *  • "No zoo to escape from." when zoos === 0.
 *  • The button is disabled while the request is in flight.
 *  • Existing REWILD button still renders alongside it.
 *
 * The inspectorApi module is mocked (same pattern as ControlPanel.rewild.test.tsx).
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
import { expandSection } from '../../test-utils/expandSection';

const PLACES = [
  { id: 'plaza', name: 'Central Plaza', x: 100, y: 100, kind: 'social' as const, description: '' },
];

function renderPanel(
  onZooEscape = vi.fn(async () => ({ escaped: 3, zoos: 1 })),
) {
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
      onRewild={vi.fn(async () => ({ spawned: 0, cap_reached: false }))}
      onZooEscape={onZooEscape}
      onBillboardReply={vi.fn()}
      mockMode={false}
      profiles={[profile({ name: 'model-a' })]}
    />,
  );
  expandSection(/MENAGERIE/i);
  return { onZooEscape };
}

beforeEach(() => vi.clearAllMocks());

describe('MENAGERIE — Zoo escape button (EM-208 H3)', () => {
  it('renders the Zoo escape button in the MENAGERIE section', () => {
    renderPanel();
    expect(
      screen.getByRole('button', { name: /Trigger zoo escape/i }),
    ).toBeInTheDocument();
  });

  it('calls onZooEscape when clicked', async () => {
    const user = userEvent.setup();
    const { onZooEscape } = renderPanel();
    await user.click(screen.getByRole('button', { name: /Trigger zoo escape/i }));
    expect(onZooEscape).toHaveBeenCalledTimes(1);
  });

  it('flashes "N animals escaped!" on success', async () => {
    const user = userEvent.setup();
    renderPanel(vi.fn(async () => ({ escaped: 3, zoos: 1 })));
    await user.click(screen.getByRole('button', { name: /Trigger zoo escape/i }));
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/3 animals escaped!/),
    );
  });

  it('flashes "No zoo to escape from." when zoos === 0', async () => {
    const user = userEvent.setup();
    renderPanel(vi.fn(async () => ({ escaped: 0, zoos: 0 })));
    await user.click(screen.getByRole('button', { name: /Trigger zoo escape/i }));
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/No zoo to escape from/),
    );
  });

  it('disables the button while the request is in flight', async () => {
    const user = userEvent.setup();
    let release!: (v: { escaped: number; zoos: number }) => void;
    const slowEscape = vi.fn(
      () => new Promise<{ escaped: number; zoos: number }>((res) => { release = res; }),
    );
    renderPanel(slowEscape);
    await user.click(screen.getByRole('button', { name: /Trigger zoo escape/i }));
    expect(screen.getByRole('button', { name: /Trigger zoo escape/i })).toBeDisabled();
    release({ escaped: 2, zoos: 1 });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Trigger zoo escape/i })).toBeEnabled(),
    );
  });

  it('the Rewild button still renders alongside Zoo escape', () => {
    renderPanel();
    expect(screen.getByRole('button', { name: /Rewild/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Trigger zoo escape/i })).toBeInTheDocument();
  });
});
