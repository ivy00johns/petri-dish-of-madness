/**
 * Wave K (EM-221) — the BUILDERS group in the GOD CONSOLE, through ControlPanel.
 *
 * Covers:
 *  • The BUILDERS group + its four controls render.
 *  • PLACE PROP calls onPlaceProp with {kind, place, count} and flashes.
 *  • CLEAR PROPS calls onClearProps (place id, or undefined for "All places")
 *    and flashes the cleared count.
 *  • DEMOLISH calls onDemolish with the chosen building id and flashes.
 *  • RESKIN calls onReskin with the chosen building id + skin name and flashes.
 *  • The buttons disable while a request is in flight.
 *  • The group is omitted when its callbacks aren't wired (pre-Wave-K callers).
 *
 * Plus mock-generator coverage (placePropMock/clearPropsMock/demolishMock/
 * reskinMock) — the offline fallback the useSimulation BUILDERS client fns
 * call in mock mode: each synthesizes the contract §4 events and returns the
 * right result shape (these are the deterministic, network-free substrate the
 * hook's mock path delegates to, mirroring how `rewild` delegates to
 * mockControls.spawnAnimal).
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
import { mockControls } from '../../mock/generator';
import { agent, building, profile, world } from '../../test-utils/fixtures';
import { expandSection } from '../../test-utils/expandSection';

const PLACES = [
  { id: 'plaza', name: 'Central Plaza', x: 100, y: 100, kind: 'social' as const, description: '' },
  { id: 'market', name: 'Market', x: 200, y: 200, kind: 'work' as const, description: '' },
];

const BUILDINGS = [
  building({ id: 'bld-1', name: 'Old Library', kind: 'library', location: 'plaza' }),
  building({ id: 'bld-2', name: 'The Granary', kind: 'farm', location: 'market' }),
];

function handlers() {
  return {
    onPlaceProp: vi.fn(async () => ({ placed: 1 })),
    onClearProps: vi.fn(async () => ({ cleared: 2 })),
    onDemolish: vi.fn(async () => ({ demolished: true })),
    onReskin: vi.fn(async () => ({ reskinned: true })),
  };
}

function renderPanel(h = handlers()) {
  render(
    <ControlPanel
      world={world({ places: PLACES, buildings: BUILDINGS, agents: [agent({ id: 'bram', name: 'Bram' })] })}
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
      onZooEscape={vi.fn(async () => ({ escaped: 0, zoos: 0 }))}
      onPlaceProp={h.onPlaceProp}
      onClearProps={h.onClearProps}
      onDemolish={h.onDemolish}
      onReskin={h.onReskin}
      onBillboardReply={vi.fn()}
      mockMode={false}
      profiles={[profile({ name: 'model-a' })]}
    />,
  );
  expandSection(/BUILDERS/i);
  return h;
}

beforeEach(() => vi.clearAllMocks());

describe('GOD CONSOLE — BUILDERS group (EM-221)', () => {
  it('renders the BUILDERS heading and its four controls', () => {
    renderPanel();
    expect(screen.getByRole('heading', { name: /BUILDERS/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Place 1 bench/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Clear props everywhere/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Demolish the chosen building/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Reskin the chosen building/i })).toBeInTheDocument();
  });

  it('PLACE PROP posts {kind, place, count} and flashes a confirmation', async () => {
    const user = userEvent.setup();
    const h = renderPanel();
    const kind = screen.getByLabelText('Prop kind');
    await user.clear(kind);
    await user.type(kind, 'lamp');
    const count = screen.getByLabelText('Prop count');
    await user.tripleClick(count);
    await user.keyboard('3');
    await user.selectOptions(screen.getByLabelText('Prop place'), 'market');
    await user.click(screen.getByRole('button', { name: /Place 3 lamp/i }));
    expect(h.onPlaceProp).toHaveBeenCalledTimes(1);
    expect(h.onPlaceProp).toHaveBeenCalledWith({ kind: 'lamp', place: 'market', count: 3 });
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/placed at Market/i),
    );
  });

  it('CLEAR PROPS at "All places" posts undefined and flashes the cleared count', async () => {
    const user = userEvent.setup();
    const h = renderPanel();
    await user.click(screen.getByRole('button', { name: /Clear props everywhere/i }));
    expect(h.onClearProps).toHaveBeenCalledTimes(1);
    expect(h.onClearProps).toHaveBeenCalledWith(undefined);
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/2 props cleared from every place/i),
    );
  });

  it('CLEAR PROPS at a chosen place posts that place id', async () => {
    const user = userEvent.setup();
    const h = renderPanel();
    await user.selectOptions(screen.getByLabelText('Clear props at place'), 'plaza');
    await user.click(screen.getByRole('button', { name: /Clear props at the chosen place/i }));
    expect(h.onClearProps).toHaveBeenCalledWith('plaza');
  });

  it('DEMOLISH posts the chosen building id and flashes', async () => {
    const user = userEvent.setup();
    const h = renderPanel();
    await user.selectOptions(screen.getByLabelText('Building to demolish'), 'bld-2');
    await user.click(screen.getByRole('button', { name: /Demolish the chosen building/i }));
    expect(h.onDemolish).toHaveBeenCalledWith('bld-2');
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/The Granary demolished/i),
    );
  });

  it('RESKIN posts the chosen building id + skin name and flashes', async () => {
    const user = userEvent.setup();
    const h = renderPanel();
    await user.selectOptions(screen.getByLabelText('Building to reskin'), 'bld-1');
    await user.selectOptions(screen.getByLabelText('Skin'), 'sky');
    await user.click(screen.getByRole('button', { name: /Reskin the chosen building/i }));
    expect(h.onReskin).toHaveBeenCalledWith('bld-1', 'sky');
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/Old Library reskinned sky/i),
    );
  });

  it('disables PLACE PROP while the request is in flight', async () => {
    const user = userEvent.setup();
    let release!: (v: { placed: number }) => void;
    const slow = vi.fn(() => new Promise<{ placed: number }>((res) => { release = res; }));
    const h = handlers();
    h.onPlaceProp = slow;
    renderPanel(h);
    await user.click(screen.getByRole('button', { name: /Place 1 bench/i }));
    expect(screen.getByRole('button', { name: /Place 1 bench/i })).toBeDisabled();
    release({ placed: 1 });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Place 1 bench/i })).toBeEnabled(),
    );
  });

  it('omits the BUILDERS group when its callbacks are not wired', () => {
    render(
      <ControlPanel
        world={world({ places: PLACES, buildings: BUILDINGS })}
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
        onZooEscape={vi.fn(async () => ({ escaped: 0, zoos: 0 }))}
        onBillboardReply={vi.fn()}
        mockMode={false}
        profiles={[profile({ name: 'model-a' })]}
      />,
    );
    expect(screen.queryByRole('heading', { name: /BUILDERS/i })).not.toBeInTheDocument();
  });
});

// ── Mock generator BUILDERS helpers (the hook's offline fallback, EM-221) ─────
describe('mock generator BUILDERS helpers (EM-221)', () => {
  beforeEach(() => {
    // Restore the seed world so each case starts from a known state (5 seeded
    // props, no buildings) — mirrors a fresh mock run.
    mockControls.reset();
  });

  it('placeProp adds props at the place and emits one prop_placed per prop', () => {
    const { state, events, placed } = mockControls.placeProp({ kind: 'bench', place: 'plaza', count: 2 });
    expect(placed).toBe(2);
    expect(events).toHaveLength(2);
    expect(events.every((e) => e.kind === 'prop_placed')).toBe(true);
    expect(events[0].payload).toMatchObject({ kind: 'bench', place: 'plaza' });
    // The two new props are the god-stamped ones (prop-god-*), placed at
    // 'plaza' with distinct (dx,dz) ring offsets so they don't stack.
    const placedNow = (state.props ?? []).filter(
      (p) => p.place === 'plaza' && p.kind === 'bench' && p.id.startsWith('prop-god-'),
    );
    expect(placedNow.length).toBe(2);
    expect(placedNow[0].dx === placedNow[1].dx && placedNow[0].dz === placedNow[1].dz).toBe(false);
  });

  it('placeProp clamps the kind to 30 chars and an unknown place to plaza', () => {
    const { events } = mockControls.placeProp({ kind: 'x'.repeat(40), place: 'nowhere', count: 1 });
    expect((events[0].payload?.kind as string).length).toBe(30);
    expect(events[0].payload?.place).toBe('plaza');
  });

  it('clearProps (no place) removes ALL props and emits prop_removed for each', () => {
    const before = (mockControls.placeProp({ kind: 'lamp', place: 'plaza' }).state.props ?? []).length;
    expect(before).toBeGreaterThan(0);
    const { state, events, cleared } = mockControls.clearProps();
    expect(cleared).toBe(before);
    expect(state.props).toHaveLength(0);
    expect(events.every((e) => e.kind === 'prop_removed')).toBe(true);
  });

  it('clearProps at a place removes only that place’s props', () => {
    mockControls.placeProp({ kind: 'bin', place: 'market', count: 3 });
    const { state, cleared } = mockControls.clearProps({ place: 'market' });
    expect(cleared).toBeGreaterThanOrEqual(3);
    expect((state.props ?? []).some((p) => p.place === 'market')).toBe(false);
  });

  it('demolish returns demolished:false (no event) for an unknown building id', () => {
    const { events, demolished } = mockControls.demolish({ building_id: 'does-not-exist' });
    expect(demolished).toBe(false);
    expect(events).toHaveLength(0);
  });

  it('reskin returns reskinned:false (no event) for an unknown building id', () => {
    const { events, reskinned } = mockControls.reskin({ building_id: 'nope', skin: 'rose' });
    expect(reskinned).toBe(false);
    expect(events).toHaveLength(0);
  });
});
