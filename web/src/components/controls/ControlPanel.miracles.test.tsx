/**
 * GOD CONSOLE — MIRACLES row (Wave E EM-184, contracts/wave-e.md B6 item 3),
 * through ControlPanel. The INTERVENE group gains a kind picker (the three
 * WORLD kinds) + CAST, wired to inspectorApi.godMiracle(kind) — no agent
 * involved (world kinds reject one). Optimistic-free: the success line says
 * so; failures render inline via the labeled-result idiom. The api module is
 * mocked; no network.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
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

import { inspectorApi } from '../../inspector/api';
import { ControlPanel } from './ControlPanel';
import { agent, profile, world } from '../../test-utils/fixtures';

const miracleMock = inspectorApi.godMiracle as Mock;

function renderPanel() {
  render(
    <ControlPanel
      world={world({ agents: [agent({ id: 'bram', name: 'Bram' })] })}
      onStart={vi.fn()}
      onPause={vi.fn()}
      onStep={vi.fn()}
      onReset={vi.fn()}
      onSpeed={vi.fn()}
      onReassign={vi.fn()}
      onInject={vi.fn()}
      onSpawn={vi.fn()}
      onBillboardReply={vi.fn()}
      mockMode={false}
      profiles={[profile({ name: 'model-a' })]}
    />,
  );
}

beforeEach(() => {
  miracleMock.mockReset();
  miracleMock.mockResolvedValue({ ok: true });
});

describe('GOD CONSOLE — MIRACLES row (EM-184)', () => {
  it('renders the kind picker with exactly the three world kinds', () => {
    renderPanel();
    const select = screen.getByLabelText('Miracle to cast');
    const values = Array.from(select.querySelectorAll('option')).map((o) => o.getAttribute('value'));
    expect(values).toEqual(['send_rain', 'bountiful_harvest', 'calm_spirits']);
  });

  it('CAST calls godMiracle with the picked kind (default send_rain)', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'Cast the miracle' }));
    expect(miracleMock).toHaveBeenCalledTimes(1);
    expect(miracleMock).toHaveBeenCalledWith('send_rain');
    expect(await screen.findByText(/no local echo/)).toBeInTheDocument();
  });

  it('CAST threads a different picked kind', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.selectOptions(screen.getByLabelText('Miracle to cast'), 'calm_spirits');
    await user.click(screen.getByRole('button', { name: 'Cast the miracle' }));
    expect(miracleMock).toHaveBeenCalledWith('calm_spirits');
  });

  it('disables CAST while in flight and re-enables on resolve', async () => {
    const user = userEvent.setup();
    let release!: (v: { ok: true }) => void;
    miracleMock.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'Cast the miracle' }));
    expect(screen.getByRole('button', { name: 'Cast the miracle' })).toBeDisabled();
    release({ ok: true });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Cast the miracle' })).toBeEnabled(),
    );
  });

  it('renders a labeled failure inline (e.g. miracles disabled ⇒ 422)', async () => {
    const user = userEvent.setup();
    miracleMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      message: 'miracle rejected — unknown/dead agent or invalid input (HTTP 422)',
    });
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'Cast the miracle' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/HTTP 422/);
  });
});
