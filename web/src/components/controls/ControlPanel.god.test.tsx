/**
 * GOD CONSOLE (Wave A.2 EM-138), through ControlPanel — the three labeled
 * groups render; the INTERVENE agent selector lists LIVING agents only;
 * BLESS/GRANT/WHISPER call the api client with the contract arguments
 * (optimistic-free — no local echo asserted anywhere); the whisper input
 * enforces the 280 cap; buttons disable while a request is in flight; and a
 * labeled failure renders inline. The api module is mocked; no network.
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
  },
}));

import { inspectorApi } from '../../inspector/api';
import { ControlPanel } from './ControlPanel';
import { agent, profile, world } from '../../test-utils/fixtures';

const interveneMock = inspectorApi.godIntervene as Mock;
const whisperMock = inspectorApi.godWhisper as Mock;

const AGENTS = [
  agent({ id: 'bram', name: 'Bram', energy: 12, credits: 3 }),
  agent({ id: 'isla', name: 'Isla', energy: 80, credits: 50 }),
  agent({ id: 'mort', name: 'Mort', alive: false }),
];

function renderPanel() {
  const onInject = vi.fn();
  const onBillboardReply = vi.fn();
  render(
    <ControlPanel
      world={world({ agents: AGENTS })}
      onStart={vi.fn()}
      onPause={vi.fn()}
      onStep={vi.fn()}
      onReset={vi.fn()}
      onSpeed={vi.fn()}
      onReassign={vi.fn()}
      onInject={onInject}
      onSpawn={vi.fn()}
      onBillboardReply={onBillboardReply}
      mockMode={false}
      profiles={[profile({ name: 'model-a' })]}
    />,
  );
  return { onInject, onBillboardReply };
}

beforeEach(() => {
  interveneMock.mockReset();
  whisperMock.mockReset();
  interveneMock.mockResolvedValue({ ok: true });
  whisperMock.mockResolvedValue({ ok: true });
});

describe('GOD CONSOLE — the three labeled groups (EM-138)', () => {
  it('renders the console header and the WORLD EVENTS / INTERVENE / VOICE groups', () => {
    renderPanel();
    expect(screen.getByRole('heading', { name: '✦ GOD CONSOLE' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'WORLD EVENTS' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'INTERVENE' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'VOICE' })).toBeInTheDocument();
  });

  it('WORLD EVENTS keeps the existing inject behavior (kind threads through)', async () => {
    const user = userEvent.setup();
    const { onInject } = renderPanel();
    await user.selectOptions(screen.getByLabelText('Event type to inject'), 'famine');
    await user.click(screen.getByRole('button', { name: 'INJECT EVENT' }));
    expect(onInject).toHaveBeenCalledWith('famine');
  });

  it('VOICE keeps the billboard reply wired to onBillboardReply', async () => {
    const user = userEvent.setup();
    const { onBillboardReply } = renderPanel();
    await user.type(screen.getByLabelText(/Reply on billboard/i), 'be kind');
    await user.click(screen.getByRole('button', { name: 'Post the god reply to the billboard' }));
    expect(onBillboardReply).toHaveBeenCalledWith('be kind');
  });
});

describe('GOD CONSOLE — INTERVENE (EM-136/137)', () => {
  it('the agent selector lists LIVING agents only', () => {
    renderPanel();
    const select = screen.getByLabelText('Agent to intervene on');
    const names = Array.from(select.querySelectorAll('option')).map((o) => o.textContent);
    expect(names).toHaveLength(2);
    expect(names[0]).toMatch(/Bram/);
    expect(names[1]).toMatch(/Isla/);
    expect(names.join(' ')).not.toMatch(/Mort/);
  });

  it('BLESS posts bless_energy for the selected agent (no amount = default +25)', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole('button', { name: /Bless Bram/ }));
    expect(interveneMock).toHaveBeenCalledTimes(1);
    expect(interveneMock).toHaveBeenCalledWith('bless_energy', 'bram');
  });

  it('GRANT posts grant_credits for the agent chosen in the selector', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.selectOptions(screen.getByLabelText('Agent to intervene on'), 'isla');
    await user.click(screen.getByRole('button', { name: /Grant Isla/ }));
    expect(interveneMock).toHaveBeenCalledWith('grant_credits', 'isla');
  });

  it('WHISPER sends the text to the selected agent and clears the input on ok', async () => {
    const user = userEvent.setup();
    renderPanel();
    const input = screen.getByLabelText('🜁 Whisper');
    await user.type(input, 'the well is poisoned');
    await user.click(screen.getByRole('button', { name: 'Whisper to Bram' }));
    expect(whisperMock).toHaveBeenCalledWith('bram', 'the well is poisoned');
    await waitFor(() => expect(input).toHaveValue(''));
    expect(screen.getByRole('status')).toHaveTextContent(/no local echo/);
  });

  it('the whisper input enforces the 280 cap and stays disabled while empty', async () => {
    const user = userEvent.setup();
    renderPanel();
    const input = screen.getByLabelText('🜁 Whisper');
    expect(input).toHaveAttribute('maxlength', '280');
    expect(screen.getByRole('button', { name: 'Whisper to Bram' })).toBeDisabled();
    await user.type(input, 'hi');
    // The live counter is the whisper's own (BillboardReply has a separate one).
    expect(screen.getByText('2/280')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Whisper to Bram' })).toBeEnabled();
  });

  it('disables all three action buttons while a request is in flight', async () => {
    const user = userEvent.setup();
    let release!: (v: { ok: true }) => void;
    interveneMock.mockImplementationOnce(
      () => new Promise((resolve) => { release = resolve; }),
    );
    renderPanel();

    await user.click(screen.getByRole('button', { name: /Bless Bram/ }));
    expect(screen.getByRole('button', { name: /Bless Bram/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Grant Bram/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Whisper to Bram' })).toBeDisabled();

    release({ ok: true });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Bless Bram/ })).toBeEnabled(),
    );
  });

  it('renders a 4xx/5xx failure inline via the labeled error treatment', async () => {
    const user = userEvent.setup();
    interveneMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      message: 'intervention rejected — unknown/dead agent or invalid input (HTTP 422)',
    });
    renderPanel();

    await user.click(screen.getByRole('button', { name: /Bless Bram/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/HTTP 422/);
  });
});
