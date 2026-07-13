/**
 * FingerprintTicker (EM-313) — the pure presentational view + selection helpers.
 *
 * We test the pure half (data in, no fetch) so the render is deterministic:
 *   - disabled / empty backend ⇒ renders NOTHING (zero chrome, golden-safe)
 *   - a locked, correct agent ⇒ confidence %, guessed model, ground-truth ✓
 *   - a wrong guess ⇒ ✗ reveal
 *   - a gathering agent ⇒ the honest "not enough behavior" null state
 *   - pickAgent focus vs most-turns fallback
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FingerprintTickerView } from './FingerprintTicker';
import { pickAgent, pct, shortModel } from '../../lib/fingerprint';
import type { FingerprintAgent, FingerprintResponse } from '../../lib/fingerprint';

function agent(partial: Partial<FingerprintAgent> & { agent_id: string }): FingerprintAgent {
  return {
    turns: 10,
    ground_truth: null,
    guess: null,
    confidence: 0,
    status: 'gathering',
    correct: null,
    candidates: [],
    series: [],
    ...partial,
  };
}

function resp(partial: Partial<FingerprintResponse>): FingerprintResponse {
  return {
    enabled: true,
    feature_version: 1,
    agents: [],
    ...partial,
  };
}

beforeEach(() => {
  localStorage.clear(); // the panel persists its collapse preference
});

describe('pure helpers', () => {
  it('pct clamps to [0,100]', () => {
    expect(pct(0.931)).toBe(93);
    expect(pct(2)).toBe(100);
    expect(pct(-1)).toBe(0);
  });

  it('shortModel truncates long names', () => {
    expect(shortModel(null)).toBe('—');
    expect(shortModel('qwen')).toBe('qwen');
    expect(shortModel('a'.repeat(40)).endsWith('…')).toBe(true);
  });

  it('pickAgent: null when disabled or empty', () => {
    expect(pickAgent(null)).toBeNull();
    expect(pickAgent(resp({ enabled: false, agents: [agent({ agent_id: 'a' })] }))).toBeNull();
    expect(pickAgent(resp({ agents: [] }))).toBeNull();
  });

  it('pickAgent: prefers the focused agent, else the most-turns agent', () => {
    const data = resp({
      agents: [
        agent({ agent_id: 'a', turns: 3 }),
        agent({ agent_id: 'b', turns: 20 }),
      ],
    });
    expect(pickAgent(data, 'a')?.agent_id).toBe('a');
    expect(pickAgent(data)?.agent_id).toBe('b'); // fallback = most turns
    expect(pickAgent(data, 'missing')?.agent_id).toBe('b'); // unknown focus → fallback
  });
});

describe('FingerprintTickerView', () => {
  it('renders nothing when disabled', () => {
    const { container } = render(
      <FingerprintTickerView data={resp({ enabled: false })} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders nothing when there are no agents', () => {
    const { container } = render(<FingerprintTickerView data={resp({ agents: [] })} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows the converging guess, confidence, and a correct ground-truth reveal', () => {
    const locked = agent({
      agent_id: 'ada',
      turns: 21,
      status: 'locked',
      guess: 'cerebras-qwen',
      confidence: 0.93,
      ground_truth: 'cerebras-qwen',
      correct: true,
      candidates: ['cerebras-qwen', 'groq-llama'],
      series: [
        { turn: 1, tick: 1, guess: 'groq-llama', confidence: 0.4, distribution: {} },
        { turn: 21, tick: 21, guess: 'cerebras-qwen', confidence: 0.93, distribution: {} },
      ],
    });
    render(
      <FingerprintTickerView
        data={resp({ agents: [locked] })}
        activeAgentId="ada"
        names={{ ada: 'Ada' }}
      />,
    );
    expect(screen.getByText('Ada')).toBeTruthy();
    expect(screen.getByText('93%')).toBeTruthy();
    // guess model appears (in the guess line) and actual (ground truth) chip.
    expect(screen.getAllByText('cerebras-qwen').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/locked on/)).toBeTruthy();
    const bar = screen.getByRole('progressbar');
    expect(bar.getAttribute('aria-valuenow')).toBe('93');
  });

  it('marks a wrong guess as fooled', () => {
    const wrong = agent({
      agent_id: 'x',
      status: 'tracking',
      guess: 'groq-llama',
      confidence: 0.55,
      ground_truth: 'cerebras-qwen',
      correct: false,
      series: [
        { turn: 1, tick: 1, guess: 'groq-llama', confidence: 0.5, distribution: {} },
        { turn: 5, tick: 5, guess: 'groq-llama', confidence: 0.55, distribution: {} },
      ],
    });
    render(<FingerprintTickerView data={resp({ agents: [wrong] })} />);
    expect(screen.getByText(/fooled/)).toBeTruthy();
  });

  it('shows the honest gathering state', () => {
    const g = agent({ agent_id: 'y', status: 'gathering', turns: 2 });
    render(<FingerprintTickerView data={resp({ agents: [g] })} names={{ y: 'Yara' }} />);
    expect(screen.getByText('Yara')).toBeTruthy();
    expect(screen.getByText(/gathering signal/)).toBeTruthy();
    // no confidence bar in the gathering state
    expect(screen.queryByRole('progressbar')).toBeNull();
  });
});
