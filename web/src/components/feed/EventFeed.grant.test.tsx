/**
 * Wave E (EM-185, contracts/wave-e.md B6 item 2) — GRANT-a-petition.
 *
 * The affordance shows on petition-shaped entries (an AGENT's billboard_posted
 * / proclamation_answered), never on the god's own posts. Granting fires BOTH
 * halves of the loop, optimistic-free:
 *   (a) POST /api/god/intervene — a WORLD kind's body carries NO agent_id key;
 *       targeted kinds aim at the petitioner (event.actor_id);
 *   (b) the god billboard reply quoting the petition via the existing
 *       in_reply_to channel (the onGrantReply prop = useSimulation.postBillboard).
 * fetch is stubbed (the real inspectorApi runs); no network, no local echo.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { EventFeed } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';
import type { WorldEvent } from '../../types';

const fetchMock = vi.fn();

beforeEach(() => {
  resetSeq();
  localStorage.clear();
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function petition(partial: Partial<WorldEvent> = {}): WorldEvent {
  return ev({
    kind: 'billboard_posted',
    tick: 4,
    actor_id: 'agent_ada',
    actor_type: 'human_agent',
    text: 'Ada pins a note: "please send rain for the gardens"',
    payload: { place: 'plaza', text: 'please send rain for the gardens' },
    ...partial,
  });
}

function requestBody(call = 0): Record<string, unknown> {
  const init = fetchMock.mock.calls[call][1] as RequestInit;
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

describe('GRANT — petition detection (EM-185)', () => {
  it('shows GRANT on an agent billboard post', () => {
    render(<EventFeed events={[petition()]} onGrantReply={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Grant this petition' })).toBeInTheDocument();
  });

  it('shows GRANT on a proclamation_answered by an agent', () => {
    const e = ev({
      kind: 'proclamation_answered',
      tick: 6,
      actor_id: 'agent_bram',
      text: '↳ Bram answers the god: "spare us the famine"',
      payload: { text: 'spare us the famine', in_reply_to: 'WHAT DO YOU NEED?' },
    });
    render(<EventFeed events={[e]} onGrantReply={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Grant this petition' })).toBeInTheDocument();
  });

  it('does NOT show GRANT on the god’s own billboard posts', () => {
    const godPost = petition({ actor_id: 'god', actor_type: 'god', text: 'I hear you.' });
    render(<EventFeed events={[godPost]} onGrantReply={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Grant this petition' })).not.toBeInTheDocument();
  });

  it('does NOT show GRANT on non-petition kinds', () => {
    const speech = ev({ kind: 'agent_speech', tick: 2, actor_id: 'agent_ada', text: 'nice day' });
    render(<EventFeed events={[speech]} onGrantReply={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Grant this petition' })).not.toBeInTheDocument();
  });

  it('does NOT show GRANT when no reply channel is wired (prop absent)', () => {
    render(<EventFeed events={[petition()]} />);
    expect(screen.queryByRole('button', { name: 'Grant this petition' })).not.toBeInTheDocument();
  });
});

describe('GRANT — the picker + both halves of the flow', () => {
  it('opens the picker pre-filled with the petition quote', async () => {
    const user = userEvent.setup();
    render(<EventFeed events={[petition()]} onGrantReply={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Grant this petition' }));
    const picker = screen.getByRole('group', { name: /Grant the petition/ });
    expect(picker).toHaveTextContent('please send rain for the gardens');
    // 3 world miracles + 2 targeted interventions.
    expect(screen.getByRole('button', { name: 'Grant via send_rain' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Grant via bountiful_harvest' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Grant via calm_spirits' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Grant via bless_energy' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Grant via grant_credits' })).toBeInTheDocument();
  });

  it('a WORLD kind posts {kind} with NO agent_id key, then replies quoting the petition', async () => {
    const user = userEvent.setup();
    const onGrantReply = vi.fn();
    render(<EventFeed events={[petition()]} onGrantReply={onGrantReply} />);
    await user.click(screen.getByRole('button', { name: 'Grant this petition' }));
    await user.click(screen.getByRole('button', { name: 'Grant via send_rain' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0][0]).toBe('/api/god/intervene');
    const body = requestBody();
    expect(body).toEqual({ kind: 'send_rain' });
    expect('agent_id' in body).toBe(false);

    await waitFor(() => expect(onGrantReply).toHaveBeenCalledTimes(1));
    const [text, inReplyTo] = onGrantReply.mock.calls[0] as [string, string];
    expect(text).toContain('please send rain for the gardens');
    expect(text).toMatch(/Granted/);
    expect(inReplyTo).toBe('please send rain for the gardens');
    // Optimistic-free: the affordance flips to a status chip, no echo row.
    expect(await screen.findByRole('status')).toHaveTextContent(/granted/i);
  });

  it('a TARGETED kind posts {kind, agent_id: petitioner}', async () => {
    const user = userEvent.setup();
    const onGrantReply = vi.fn();
    render(<EventFeed events={[petition()]} onGrantReply={onGrantReply} />);
    await user.click(screen.getByRole('button', { name: 'Grant this petition' }));
    await user.click(screen.getByRole('button', { name: 'Grant via bless_energy' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(requestBody()).toEqual({ kind: 'bless_energy', agent_id: 'agent_ada' });
    await waitFor(() => expect(onGrantReply).toHaveBeenCalledTimes(1));
  });

  it('a failed intervention renders the labeled error and does NOT reply', async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({}) });
    const onGrantReply = vi.fn();
    render(<EventFeed events={[petition()]} onGrantReply={onGrantReply} />);
    await user.click(screen.getByRole('button', { name: 'Grant this petition' }));
    await user.click(screen.getByRole('button', { name: 'Grant via send_rain' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/HTTP 422/);
    expect(onGrantReply).not.toHaveBeenCalled();
  });
});
