/**
 * ExtinctionBanner smoke (EM-043 / EM-071) — the banner + NEW RUN CTA render
 * when extinction is computed, and the component stays hidden otherwise.
 */
import { describe, expect, it, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ExtinctionBanner } from './ExtinctionBanner';
import { agent, ev, resetSeq, world } from '../test-utils/fixtures';

beforeEach(resetSeq);

const deadWorld = () =>
  world({
    agents: [agent({ id: 'a1', name: 'Ada', alive: false })],
    running: false,
  });

describe('ExtinctionBanner', () => {
  it('renders the alert + tick + paused chip + NEW RUN cta on extinction', () => {
    const events = [
      ev({ kind: 'world_extinct', tick: 42, payload: { tick: 42, last_agent_id: 'a1', auto_paused: true } }),
      ev({ kind: 'agent_died', tick: 42, actor_id: 'a1' }),
    ];
    const onReset = vi.fn();
    render(<ExtinctionBanner world={deadWorld()} events={events} onReset={onReset} />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/extinction/i);
    expect(alert).toHaveTextContent('42');
    expect(alert).toHaveTextContent(/simulation paused/i);

    const cta = screen.getByRole('button', { name: /new run/i });
    fireEvent.click(cta);
    expect(onReset).toHaveBeenCalledTimes(1);

    // The end-of-run summary opens by default and lists the death.
    expect(screen.getByText(/deaths, in order/i)).toBeInTheDocument();
    expect(screen.getByText('Ada')).toBeInTheDocument();
  });

  it('renders the banner from the zero-living fallback with no world_extinct event', () => {
    render(<ExtinctionBanner world={deadWorld()} events={[]} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    // No onReset prop → no NEW RUN cta.
    expect(screen.queryByRole('button', { name: /new run/i })).not.toBeInTheDocument();
  });

  it('renders NOTHING while anyone is alive', () => {
    const w = world({ agents: [agent({ id: 'a1' }), agent({ id: 'a2', alive: false })] });
    const { container } = render(<ExtinctionBanner world={w} events={[]} onReset={() => {}} />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(container).toBeEmptyDOMElement();
  });
});
