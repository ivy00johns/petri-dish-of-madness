/**
 * SpawnForm persona integration (W11b EM-092), through ControlPanel: picking a
 * card PREFILLS name/personality/profile (all still editable) and the spawn
 * spec carries `persona` — but any edit after the pick flips to explicit
 * fields and the stale persona name is NOT sent (edit-wins). The api module
 * is mocked; no network.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../inspector/api', () => ({
  inspectorApi: { personas: vi.fn() },
}));

import { inspectorApi } from '../../inspector/api';
import { ControlPanel } from './ControlPanel';
import { profile, world } from '../../test-utils/fixtures';

const personasMock = inspectorApi.personas as Mock;

const MOX = {
  name: 'Mox',
  archetype: 'Conspiracy Theorist',
  personality: 'Reads hidden messages in billboard typos.',
  suggested_profile: 'qwen-next',
};

const PROFILES = [
  profile({ name: 'model-a', color: '#00ff00' }),
  profile({ name: 'qwen-next', color: '#ff00aa' }),
];

function renderPanel() {
  const onSpawn = vi.fn();
  render(
    <ControlPanel
      world={world({
        places: [
          { id: 'plaza', name: 'Plaza', x: 0, y: 0, kind: 'social', description: '' },
        ],
      })}
      onStart={vi.fn()}
      onPause={vi.fn()}
      onStep={vi.fn()}
      onReset={vi.fn()}
      onSpeed={vi.fn()}
      onReassign={vi.fn()}
      onInject={vi.fn()}
      onSpawn={onSpawn}
      onBillboardReply={vi.fn()}
      mockMode={false}
      profiles={PROFILES}
    />,
  );
  return { onSpawn };
}

beforeEach(() => {
  personasMock.mockReset();
  personasMock.mockResolvedValue([MOX]);
});

describe('SpawnForm × PersonaPicker (EM-092)', () => {
  it('picking a card prefills name/personality/profile and sends the persona', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderPanel();

    await user.click(await screen.findByRole('option', { name: /Mox/ }));

    // Prefilled — and still plain editable inputs.
    expect(screen.getByLabelText(/^Name/)).toHaveValue('Mox');
    expect(screen.getByLabelText('Personality')).toHaveValue(MOX.personality);
    expect(screen.getByLabelText(/Model profile/)).toHaveValue('qwen-next');
    expect(
      screen.getByText(/spawning as persona “Mox” — edit any field to go freeform/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Spawn agent' }));
    expect(onSpawn).toHaveBeenCalledTimes(1);
    expect(onSpawn).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Mox',
        personality: MOX.personality,
        profile: 'qwen-next',
        persona: 'Mox', // untouched prefill ⇒ the persona name rides along
      }),
    );
  });

  it('editing a prefilled field flips to explicit and DROPS the persona (edit-wins)', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderPanel();

    await user.click(await screen.findByRole('option', { name: /Mox/ }));
    await user.clear(screen.getByLabelText(/^Name/));
    await user.type(screen.getByLabelText(/^Name/), 'Override');

    expect(
      screen.getByText(/edited since picking “Mox” — explicit fields will be sent/),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Spawn agent' }));
    expect(onSpawn).toHaveBeenCalledTimes(1);
    const spec = onSpawn.mock.calls[0][0];
    expect(spec.name).toBe('Override');
    expect(spec).not.toHaveProperty('persona');
  });

  it('does not preselect a suggested profile this run does not have', async () => {
    const user = userEvent.setup();
    personasMock.mockResolvedValue([
      { ...MOX, suggested_profile: 'profile-from-another-run' },
    ]);
    renderPanel();

    await user.click(await screen.findByRole('option', { name: /Mox/ }));
    // Name/personality still prefill; profile keeps the existing selection.
    expect(screen.getByLabelText(/^Name/)).toHaveValue('Mox');
    expect(screen.getByLabelText(/Model profile/)).toHaveValue('model-a');
  });
});
