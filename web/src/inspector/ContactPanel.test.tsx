/**
 * ContactPanel (EM-334) — component tests.
 *
 * The inspectorApi module is mocked (the panel is a pure view over it):
 *  - the unarmed world ({enabled:false}) renders its labeled explainer;
 *  - an armed world renders the two town cards, the cast-family chips, the
 *    not-yet-crossing line, and the empty ledger line;
 *  - the marker + ledger + crossings/travels render when present (fidelity
 *    percentage = 1 − mutated/hops);
 *  - the unreachable backend (null) renders the reading/zero state.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ContactPanel from './ContactPanel';
import type { ContactSummary } from './api';

vi.mock('./api', () => ({
  inspectorApi: {
    contact: vi.fn(),
  },
}));

import { inspectorApi } from './api';

const contactMock = vi.mocked(inspectorApi.contact);

const DISABLED: ContactSummary = {
  enabled: false,
  tick: 0,
  settlements: [],
  contact_made: null,
  ledger: null,
  crossings: [],
  travels: [],
};

const ARMED: ContactSummary = {
  enabled: true,
  tick: 40,
  settlements: [
    { id: 'stl_a', name: 'Mossmarket', founded_tick: 0, member_count: 3, families: { gemini: 3 } },
    { id: 'stl_b', name: 'Windrow', founded_tick: 0, member_count: 2, families: { llama: 2 } },
  ],
  contact_made: {
    tick: 31,
    agent_id: 'agent_ann_0',
    from_settlement: 'stl_a',
    to_settlement: 'stl_b',
  },
  ledger: {
    crossings: 3,
    by_family: {
      gemini: { hops: 2, mutated: 1 },
      llama: { hops: 1, mutated: 0 },
    },
  },
  crossings: [
    { tick: 34, kind: 'meme_crossed_border', actor_id: 'agent_ann_0', text: '⟐ Ann carries the idea from Mossmarket into Windrow.' },
  ],
  travels: [
    { tick: 31, kind: 'travel_departed', actor_id: 'agent_ann_0', text: 'Ann sets out from Mossmarket for Windrow.' },
    { tick: 33, kind: 'travel_arrived', actor_id: 'agent_ann_0', text: 'Ann arrives in Windrow.' },
  ],
};

describe('ContactPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the labeled explainer when contact is not armed', async () => {
    contactMock.mockResolvedValue(DISABLED);
    render(<ContactPanel />);
    await waitFor(() => expect(screen.getByTestId('contact-disabled')).toBeTruthy());
    expect(screen.queryByTestId('contact-town-families')).toBeNull();
  });

  it('renders both towns with cast families while nobody has crossed', async () => {
    contactMock.mockResolvedValue({ ...ARMED, contact_made: null, ledger: null, crossings: [], travels: [] });
    render(<ContactPanel />);
    await waitFor(() => expect(screen.getByTestId('contact-town-families')).toBeTruthy());
    expect(screen.getByText('Mossmarket')).toBeTruthy();
    expect(screen.getByText('Windrow')).toBeTruthy();
    expect(screen.getByText('gemini×3')).toBeTruthy();
    expect(screen.getByText('llama×2')).toBeTruthy();
    expect(screen.getByTestId('contact-not-yet')).toBeTruthy();
    expect(screen.getByText(/no crossings recorded/)).toBeTruthy();
    expect(screen.queryByTestId('contact-made')).toBeNull();
  });

  it('renders the first-contact marker, ledger fidelity, and event lists', async () => {
    contactMock.mockResolvedValue(ARMED);
    render(<ContactPanel />);
    await waitFor(() => expect(screen.getByTestId('contact-made')).toBeTruthy());
    expect(screen.getByTestId('contact-made').textContent).toContain('tick 31');
    expect(screen.getByTestId('contact-made').textContent).toContain('agent_ann_0');
    // Fidelity: gemini 1−1/2 = 50%; llama 1−0/1 = 100%.
    const fids = screen.getAllByTestId('contact-fidelity').map((el) => el.textContent);
    expect(fids.some((t) => t?.includes('50%'))).toBe(true);
    expect(fids.some((t) => t?.includes('100%'))).toBe(true);
    expect(screen.getByText(/3 crossings/)).toBeTruthy();
    expect(screen.getByTestId('contact-crossings').textContent).toContain('Ann carries the idea');
    expect(screen.getByTestId('contact-travels').textContent).toContain('Ann sets out');
  });

  it('renders the zero state when the backend is unreachable', async () => {
    contactMock.mockResolvedValue(null);
    render(<ContactPanel />);
    await waitFor(() => expect(screen.getByTestId('contact-panel')).toBeTruthy());
    expect(screen.queryByTestId('contact-town-families')).toBeNull();
  });
});
