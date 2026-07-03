/**
 * EM-294 — DiaryView never blanks when the selected diarist disappears (offline
 * review 2026-07-01).
 *
 * The EM-215 per-agent filter had no guard for a selected diarist that later
 * vanished from grouped history (an archived-run switch, or a history replace
 * that no longer carries their reflections): the stale id filtered to zero
 * groups → a silently blank reading room. The fix falls back deterministically
 * to "all agents" (and resets the selector) when the selection is no longer
 * present.
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DiaryView } from './DiaryView';
import { ev, agent, world } from '../../test-utils/fixtures';
import type { WorldEvent } from '../../types';

function refl(actor_id: string, text: string, tick: number): WorldEvent {
  return ev({ kind: 'reflection', actor_id, text, tick, payload: { text } });
}

const WORLD = world({
  agents: [agent({ id: 'ada', name: 'Ada' }), agent({ id: 'bram', name: 'Bram' })],
});

describe('DiaryView — missing selected diarist (EM-294)', () => {
  it('falls back to all diarists (never blank) when the selected diarist vanishes', async () => {
    const withBoth: WorldEvent[] = [refl('ada', 'Ada writes.', 10), refl('bram', 'Bram writes.', 12)];
    const { rerender } = render(<DiaryView world={WORLD} history={withBoth} />);

    // Reader filters to Bram.
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /filter to one agent/i }),
      'bram',
    );
    expect(screen.getByTestId('diary-agent-bram')).toBeTruthy();
    expect(screen.queryByTestId('diary-agent-ada')).toBeNull();

    // History no longer carries Bram (e.g. an archived-run switch).
    const withoutBram: WorldEvent[] = [refl('ada', 'Ada writes.', 10)];
    rerender(<DiaryView world={WORLD} history={withoutBram} />);

    // Deterministic fallback: Ada's column shows (not a silent blank), and the
    // selector reset to "All agents".
    expect(screen.getByTestId('diary-agent-ada')).toBeTruthy();
    const select = screen.getByRole('combobox', { name: /filter to one agent/i }) as HTMLSelectElement;
    expect(select.value).toBe('');
  });

  it('still filters normally while the selected diarist is present', async () => {
    const both: WorldEvent[] = [refl('ada', 'Ada writes.', 10), refl('bram', 'Bram writes.', 12)];
    render(<DiaryView world={WORLD} history={both} />);

    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /filter to one agent/i }),
      'ada',
    );
    expect(screen.getByTestId('diary-agent-ada')).toBeTruthy();
    expect(screen.queryByTestId('diary-agent-bram')).toBeNull();
  });
});
