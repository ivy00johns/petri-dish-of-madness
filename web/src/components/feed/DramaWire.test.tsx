/**
 * DramaWire rail (EM-316) — the flag gate + the camera hand-off. Selector logic
 * (salience, rate cap, index, focus resolution) is covered in
 * lib/dramaWire.test.ts; this file pins the UI contract: OFF renders nothing,
 * ON breaks the news, and a card click flies the shipped camera.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Mock } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Pass-through wraps of the scorers so the OFF-path tests can assert the deep
// history is NEVER scanned when the flag is off (isDramaWireEnabled stays real).
vi.mock('../../lib/dramaWire', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/dramaWire')>();
  return {
    ...actual,
    dramaBeats: vi.fn(actual.dramaBeats),
    dramaIndex: vi.fn(actual.dramaIndex),
    dramaSparkline: vi.fn(actual.dramaSparkline),
  };
});

import { dramaBeats, dramaIndex, dramaSparkline } from '../../lib/dramaWire';
import { DramaWire } from './DramaWire';
import { agent, ev, resetSeq, world } from '../../test-utils/fixtures';
import type { WorldEvent } from '../../types';

beforeEach(() => {
  resetSeq();
  vi.clearAllMocks();
});
afterEach(() => vi.unstubAllEnvs());

function newestFirst(events: WorldEvent[]): WorldEvent[] {
  return [...events].sort((a, b) => b.seq - a.seq);
}

const W = world({
  agents: [agent({ id: 'a1', name: 'Ada', location: 'market' })],
});

describe('DramaWire — flag gate', () => {
  it('renders NOTHING when the flag is unset (default OFF)', () => {
    const { container } = render(
      <DramaWire world={W} history={newestFirst([ev({ kind: 'agent_died', tick: 5 })])} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('renders NOTHING when the flag is explicitly off', () => {
    vi.stubEnv('VITE_DRAMA_WIRE', '0');
    const { container } = render(
      <DramaWire world={W} history={newestFirst([ev({ kind: 'agent_died', tick: 5 })])} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('does NO scoring with the flag off — the full history is never scanned (C6)', () => {
    const history = newestFirst([
      ev({ kind: 'agent_died', tick: 5 }),
      ev({ kind: 'war_clash', tick: 6 }),
    ]);
    const { rerender } = render(<DramaWire world={W} history={history} />);
    // Simulate a live feed update: a new history array arrives.
    rerender(<DramaWire world={W} history={[...history]} />);
    expect(dramaBeats as Mock).not.toHaveBeenCalled();
    expect(dramaIndex as Mock).not.toHaveBeenCalled();
    expect(dramaSparkline as Mock).not.toHaveBeenCalled();
  });
});

describe('DramaWire — enabled', () => {
  beforeEach(() => vi.stubEnv('VITE_DRAMA_WIRE', '1'));

  it('shows the wire header + Drama Index when on', () => {
    render(<DramaWire world={W} history={[]} />);
    expect(screen.getByText('DRAMA WIRE')).toBeInTheDocument();
    // Empty history reads a quiet wire, index 0.
    expect(screen.getByText(/Quiet on the wire/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Drama Index 0')).toBeInTheDocument();
  });

  it('breaks a death into a red BREAKING card', () => {
    render(
      <DramaWire
        world={W}
        history={newestFirst([
          ev({ kind: 'agent_died', tick: 12, text: 'Ada has fallen', actor_id: 'a1' }),
        ])}
      />,
    );
    expect(screen.getByText('DEATH')).toBeInTheDocument();
    expect(screen.getByText('Ada has fallen')).toBeInTheDocument();
  });

  it('flies the camera to the scene on click (zoom-to-place)', async () => {
    const onFocus = vi.fn();
    const user = userEvent.setup();
    render(
      <DramaWire
        world={W}
        history={newestFirst([
          ev({ kind: 'agent_died', tick: 12, text: 'Ada has fallen', actor_id: 'a1' }),
        ])}
        onFocus={onFocus}
      />,
    );
    await user.click(screen.getByRole('button', { name: /Fly the camera/i }));
    expect(onFocus).toHaveBeenCalledWith({ type: 'place', id: 'market' });
  });

  it('disables fly-to when the beat resolves to no place', () => {
    const onFocus = vi.fn();
    render(
      <DramaWire
        world={W}
        history={newestFirst([ev({ kind: 'world_extinct', tick: 20, text: 'the town falls silent' })])}
        onFocus={onFocus}
      />,
    );
    const btn = screen.getByRole('button', { name: /No place to fly to/i });
    expect(btn).toBeDisabled();
  });

  it('rate-caps: a same-tick clash burst surfaces one card', () => {
    render(
      <DramaWire
        world={W}
        history={newestFirst([
          ev({ kind: 'war_clash', tick: 30, text: 'clash A' }),
          ev({ kind: 'war_clash', tick: 31, text: 'clash B' }),
          ev({ kind: 'war_clash', tick: 32, text: 'clash C' }),
        ])}
      />,
    );
    expect(screen.getAllByText('CLASH')).toHaveLength(1);
    expect(screen.getByText('clash C')).toBeInTheDocument();
  });
});
