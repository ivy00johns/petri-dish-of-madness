/**
 * EM-202 — A/B persona-across-models, the spawn-form half (through ControlPanel).
 *
 * Covers:
 *  • OFF (default): a normal spawn omits `ab_models` entirely — byte-identical
 *    to the pre-EM-202 single-profile payload.
 *  • ON + ≥2 models picked: the spawn emits `ab_models` with the chosen names.
 *  • ON + <2 models picked: the spawn is BLOCKED (the submit disables) — the
 *    A/B group needs at least two models, so it can't fire a 1-model "group".
 *  • The A/B toggle is god-mode only — switching to governance clears it (the
 *    backend 400s ab_models under governance).
 *
 * The persona api is mocked; no network.
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
import { expandSection } from '../../test-utils/expandSection';

const personasMock = inspectorApi.personas as Mock;

const PROFILES = [
  profile({ name: 'mistral-small', color: '#00ff00' }),
  profile({ name: 'groq-llama', color: '#ff00aa' }),
  profile({ name: 'kimi', color: '#00aaff' }),
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
      onSpawnAnimal={vi.fn()}
      onRewild={vi.fn(async () => ({ spawned: 0, cap_reached: false }))}
      onZooEscape={vi.fn(async () => ({ escaped: 0, zoos: 0 }))}
      onBillboardReply={vi.fn()}
      mockMode={false}
      profiles={PROFILES}
    />,
  );
  expandSection(/GOD PANEL/i);
  return { onSpawn };
}

beforeEach(() => {
  personasMock.mockReset();
  personasMock.mockResolvedValue([]);
  // Each test starts from a clean GOD PANEL disclosure state.
  try { localStorage.clear(); } catch { /* ignore */ }
});

describe('SpawnForm × A/B (EM-202)', () => {
  it('OFF by default: a normal spawn omits ab_models', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderPanel();

    await user.type(screen.getByLabelText(/^Name/), 'Vesper');
    await user.click(screen.getByRole('button', { name: 'Spawn agent' }));

    expect(onSpawn).toHaveBeenCalledTimes(1);
    const spec = onSpawn.mock.calls[0][0];
    expect(spec.name).toBe('Vesper');
    expect(spec).not.toHaveProperty('ab_models');
  });

  it('ON + ≥2 models picked: the spawn emits ab_models with the chosen names', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderPanel();

    await user.type(screen.getByLabelText(/^Name/), 'Vesper');
    await user.click(
      screen.getByLabelText(/A\/B test this persona across multiple models/i),
    );
    await user.click(screen.getByRole('button', { name: /Toggle mistral-small/i }));
    await user.click(screen.getByRole('button', { name: /Toggle groq-llama/i }));

    // The submit label flips to the A/B affordance once ≥2 are picked.
    await user.click(screen.getByRole('button', { name: 'Spawn A/B group' }));

    expect(onSpawn).toHaveBeenCalledTimes(1);
    const spec = onSpawn.mock.calls[0][0];
    expect(spec.name).toBe('Vesper');
    expect(spec.ab_models).toEqual(['mistral-small', 'groq-llama']);
  });

  it('ON + only 1 model picked: the spawn is blocked (needs ≥2)', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderPanel();

    await user.type(screen.getByLabelText(/^Name/), 'Vesper');
    await user.click(
      screen.getByLabelText(/A\/B test this persona across multiple models/i),
    );
    await user.click(screen.getByRole('button', { name: /Toggle mistral-small/i }));

    // With A/B armed and <2 picked, the spawn button is disabled and does
    // nothing — no 1-model "group" can fire.
    const submit = screen.getByRole('button', { name: /Spawn agent/i });
    expect(submit).toBeDisabled();
    await user.click(submit);
    expect(onSpawn).not.toHaveBeenCalled();
  });

  it('switching to governance clears the A/B arm (ab_models is god-mode only)', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderPanel();

    await user.type(screen.getByLabelText(/^Name/), 'Vesper');
    await user.click(
      screen.getByLabelText(/A\/B test this persona across multiple models/i),
    );
    await user.click(screen.getByRole('button', { name: /Toggle mistral-small/i }));
    await user.click(screen.getByRole('button', { name: /Toggle groq-llama/i }));

    // Flip to GOV — the A/B multi-select collapses and the checkbox disables.
    await user.click(screen.getByRole('radio', { name: /⚖ GOV/ }));
    expect(
      screen.getByLabelText(/A\/B test this persona across multiple models/i),
    ).toBeDisabled();
    expect(
      screen.queryByRole('button', { name: /Toggle mistral-small/i }),
    ).not.toBeInTheDocument();

    // The spawn now goes through as a single-profile governance spawn — no
    // ab_models leaks through.
    await user.click(screen.getByRole('button', { name: 'Spawn agent' }));
    expect(onSpawn).toHaveBeenCalledTimes(1);
    const spec = onSpawn.mock.calls[0][0];
    expect(spec.mode).toBe('governance');
    expect(spec).not.toHaveProperty('ab_models');
  });
});
