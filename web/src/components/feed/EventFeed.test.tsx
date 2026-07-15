/**
 * EventFeed smoke (EM-043 / EM-070) — agent_starving rows always read in the
 * warn register (the survival alarm must not blend into the agent's model
 * color), while ordinary rows keep the normal text register.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventFeed } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the feed persists its filter focus
});

describe('EventFeed — agent_starving warning treatment', () => {
  it('gives the starving row the warn text register', () => {
    const events = [
      ev({
        kind: 'agent_starving',
        tick: 7,
        actor_id: 'a1',
        profile: 'model-a',
        profile_color: '#00ff00',
        text: 'Ada is starving',
        payload: { energy: 0, turns_until_death: 3, threshold: 25 },
      }),
      ev({ kind: 'agent_speech', tick: 7, actor_id: 'a2', text: 'lovely day in the plaza' }),
    ];
    render(<EventFeed events={events} />);

    const starvingRow = screen.getByText('Ada is starving');
    expect(starvingRow).toHaveClass('text-lab-warn', 'font-semibold');

    const normalRow = screen.getByText('lovely day in the plaza');
    expect(normalRow).toHaveClass('text-lab-text');
    expect(normalRow).not.toHaveClass('text-lab-warn');
  });

  it('gives world_extinct the danger register', () => {
    const events = [ev({ kind: 'world_extinct', tick: 9, text: 'the last villager has died' })];
    render(<EventFeed events={events} />);
    expect(screen.getByText('the last villager has died')).toHaveClass('text-lab-danger');
  });
});

describe('EventFeed — inline model chip on every model-decided line', () => {
  it('shows the model chip inline on a NON-speech action (no hover needed)', () => {
    render(<EventFeed events={[
      ev({ kind: 'economy', actor_id: 'a1', profile: 'cerebras-glm', profile_color: '#e74c3c',
           text: 'Cleo works and earns 4 credits.' }),
    ]} />);
    const chip = screen.getByText('cerebras-glm');
    expect(chip).toBeInTheDocument();
    expect(chip).not.toHaveClass('hidden'); // the always-visible inline chip, not a hover badge
  });

  it('does not double-chip a speech line (the hover badge is gone)', () => {
    render(<EventFeed events={[
      ev({ kind: 'agent_speech', actor_id: 'a1', profile: 'cerebras-glm', profile_color: '#e74c3c',
           text: 'Cleo says: "hello plaza"' }),
    ]} />);
    expect(screen.getAllByText('cerebras-glm')).toHaveLength(1);
  });

  it('shows ⟳ (not a model chip) on a zero-LLM reflex turn', () => {
    render(<EventFeed events={[
      ev({ kind: 'economy', actor_id: 'a1', profile: 'cerebras-glm', profile_color: '#e74c3c',
           text: 'Cy forages and finds 1 credits.', payload: { reflex: true, cadence_tier: 'background' } }),
    ]} />);
    expect(screen.queryByText('cerebras-glm')).not.toBeInTheDocument();
    expect(screen.getByText('⟳ reflex')).toBeInTheDocument();
  });
});

describe('EventFeed — benign action-rejections are not feed clutter', () => {
  it('hides a parse_failure stamped rejected:true (e.g. funding an abandoned building)', () => {
    render(<EventFeed events={[
      ev({ kind: 'agent_speech', actor_id: 'a1', text: 'Ada says: "let us rebuild the garden"' }),
      ev({
        kind: 'parse_failure', actor_id: 'a1',
        text: "Ada's contribute_funds was rejected: building 'bld_x' is abandoned — cannot fund",
        payload: { action: 'contribute_funds', error: "building 'bld_x' is abandoned — cannot fund", rejected: true },
      }),
    ]} />);
    // the benign rejection is gone; the real chatter stays
    expect(screen.queryByText(/was rejected/)).not.toBeInTheDocument();
    expect(screen.getByText(/let us rebuild the garden/)).toBeInTheDocument();
  });

  it('still shows a GENUINE CONTENT parse_failure (truncated JSON — no rejected flag, not a provider error)', () => {
    render(<EventFeed events={[
      ev({
        kind: 'parse_failure', actor_id: 'a1',
        text: "Ada's turn produced no valid JSON (finish_reason='length')",
        payload: { reason: "no valid JSON object (finish_reason='length')" },
      }),
    ]} />);
    expect(screen.getByText(/no valid JSON/)).toBeInTheDocument();
  });

  it('hides benign rejections even when the Errors channel is focused (a content parse_failure still shows)', () => {
    render(<EventFeed events={[
      ev({
        kind: 'parse_failure', actor_id: 'a1',
        text: "Cleo's build_step was rejected: building 'bld_x' is abandoned, not under_construction",
        payload: { action: 'build_step', error: 'abandoned', rejected: true },
      }),
      ev({
        kind: 'parse_failure', actor_id: 'a2',
        text: "Bram's turn produced no valid JSON (finish_reason='length')",
        payload: { reason: "no valid JSON object (finish_reason='length')" },
      }),
    ]} />);
    // Default view: the benign rejection is hidden, the real content failure shows.
    expect(screen.queryByText(/build_step was rejected/)).not.toBeInTheDocument();
    expect(screen.getByText(/no valid JSON/)).toBeInTheDocument();
  });
});

describe('EventFeed — EM-318 removal: provider_error idle-fallbacks follow the normal rules', () => {
  // Fix-don't-hide: EM-324 fixed the routing root (repin + detour), so the
  // viewer-only feed-silence filter is gone — a routing-exhaustion
  // parse_failure is a REAL error card in the ⚠ errors channel, exactly like
  // a truncated-JSON one.
  it('shows a provider_error idle-fallback in the default view (errors are not muted)', () => {
    render(<EventFeed events={[
      ev({ kind: 'agent_speech', actor_id: 'a1', text: 'Ada says: "another fine morning"' }),
      ev({
        kind: 'parse_failure', actor_id: 'a2',
        text: 'Cleo failed to produce a valid action (idle fallback): provider_error: All models exhausted',
        payload: { reason: 'provider_error: All models exhausted' },
      }),
    ]} />);
    expect(screen.getByText(/All models exhausted/)).toBeInTheDocument();
    expect(screen.getByText(/another fine morning/)).toBeInTheDocument();
  });

  it('a rate-window storm of provider_error idle-fallbacks surfaces every card', () => {
    const storm = Array.from({ length: 6 }, (_, i) =>
      ev({
        kind: 'parse_failure', actor_id: `a${i}`,
        text: `Agent ${i} failed to produce a valid action (idle fallback): provider_error: rate limit`,
        payload: { reason: 'provider_error: rate limit' },
      }),
    );
    render(<EventFeed events={storm} />);
    expect(screen.getAllByText(/idle fallback/)).toHaveLength(6);
  });

  it('treats provider_error exactly like a content parse_failure (both render together)', () => {
    render(<EventFeed events={[
      ev({
        kind: 'parse_failure', actor_id: 'a1',
        text: 'Ada failed to produce a valid action (idle fallback): provider_error: connection down',
        payload: { reason: 'provider_error: connection down' },
      }),
      ev({
        kind: 'parse_failure', actor_id: 'a2',
        text: "Bram's turn produced no valid JSON (finish_reason='length')",
        payload: { reason: "no valid JSON object (finish_reason='length')" },
      }),
    ]} />);
    expect(screen.getByText(/connection down/)).toBeInTheDocument();
    expect(screen.getByText(/no valid JSON/)).toBeInTheDocument();
  });
});
