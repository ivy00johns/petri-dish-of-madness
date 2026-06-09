/**
 * UsageAlertBanner (W11b EM-083) — the latest usage_alert per provider+metric
 * surfaces as a dismissible warn banner; dismissal is keyed by event seq so
 * the NEXT window's alert (new event = new seq) re-arms it. Renders nothing
 * with no alerts.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { latestUsageAlerts, UsageAlertBanner } from './UsageAlertBanner';
import { ev, resetSeq } from '../test-utils/fixtures';
import type { WorldEvent } from '../types';

beforeEach(() => resetSeq());

function alertEvent(
  payload: Record<string, unknown>,
  seq?: number,
): WorldEvent {
  return ev({ kind: 'usage_alert', payload, ...(seq !== undefined ? { seq } : {}) });
}

describe('latestUsageAlerts (pure)', () => {
  it('keeps only the LATEST alert per provider+metric, sorted by pct desc', () => {
    const history = [
      alertEvent({ provider: 'groq', metric: 'rpd', pct: 70, limit: 1000 }, 1),
      alertEvent({ provider: 'groq', metric: 'rpd', pct: 91, limit: 1000 }, 5),
      alertEvent({ provider: 'cerebras', metric: 'tpd', pct: 72, limit: 50000 }, 3),
      // Same provider, DIFFERENT metric — its own row.
      alertEvent({ provider: 'groq', metric: 'tpd', pct: 80, limit: 9000 }, 4),
    ];
    const alerts = latestUsageAlerts(history);
    expect(alerts.map((a) => [a.provider, a.metric, a.pct])).toEqual([
      ['groq', 'rpd', 91],
      ['groq', 'tpd', 80],
      ['cerebras', 'tpd', 72],
    ]);
    expect(alerts[0].seq).toBe(5);
  });

  it('ignores other kinds and rows with a non-finite pct', () => {
    const history = [
      ev({ kind: 'agent_speech', payload: { provider: 'groq', pct: 99 } }),
      alertEvent({ provider: 'groq', metric: 'rpd', pct: 'high' }),
      alertEvent({ provider: 'groq', metric: 'rpd' }), // no pct at all
    ];
    expect(latestUsageAlerts(history)).toEqual([]);
  });
});

describe('UsageAlertBanner', () => {
  it('renders nothing when the history has no alerts', () => {
    const { container } = render(<UsageAlertBanner history={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the alert with provider, rounded pct and the limit', () => {
    render(
      <UsageAlertBanner
        history={[alertEvent({ provider: 'groq', metric: 'rpd', pct: 70.4, limit: 1000 })]}
      />,
    );
    const banner = screen.getByRole('alert');
    expect(banner).toHaveTextContent('Usage alert:');
    expect(banner).toHaveTextContent('groq');
    expect(banner).toHaveTextContent('70%');
    expect(banner).toHaveTextContent('limit 1,000');
    expect(banner).toHaveTextContent('daily request cap');
  });

  it('dismissal hides the alert, and a NEW seq re-arms the banner', async () => {
    const user = userEvent.setup();
    const first = alertEvent({ provider: 'groq', metric: 'rpd', pct: 70, limit: 1000 }, 10);
    const { rerender } = render(<UsageAlertBanner history={[first]} />);

    await user.click(screen.getByRole('button', { name: /Dismiss the groq usage alert/ }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    // Same event again: stays dismissed (seq-keyed).
    rerender(<UsageAlertBanner history={[first]} />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    // Next window's alert = a new event with a new seq → re-raised.
    const next = alertEvent({ provider: 'groq', metric: 'rpd', pct: 73, limit: 1000 }, 20);
    rerender(<UsageAlertBanner history={[first, next]} />);
    expect(screen.getByRole('alert')).toHaveTextContent('73%');
  });
});
