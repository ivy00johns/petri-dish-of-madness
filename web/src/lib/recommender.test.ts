import { describe, it, expect } from 'vitest';
import { recommend, DEFAULT_THRESHOLDS } from './recommender';
import type { CapabilityResponse, EstimateResult } from '../types';

const CAP: CapabilityResponse = {
  lanes: [
    { id: 'mistral-small', provider: 'openai', free: true, context_window: 128000, reliability: 'clean' },
    { id: 'kimi', provider: 'openai', free: true, context_window: 128000, reliability: 'reasoning' },
    { id: 'mystery', provider: 'openai', free: true, context_window: null, reliability: 'unknown' },
    { id: 'sonnet', provider: 'anthropic', free: false, context_window: 200000, reliability: 'clean' },
  ],
  cast_pins: { Mox: 'kimi', Vesper: 'mistral-small' },
};
const est = (t: number): EstimateResult => ({ ok: true, total_input_tokens: t, output_budget: 1024, breakdown: [] });

describe('recommend', () => {
  it('light combo → free clean OK', () => {
    const r = recommend(est(3000), CAP, DEFAULT_THRESHOLDS);
    expect(r.verdict).toBe('free_clean_ok');
    expect(r.safe).toContain('mistral-small');
    expect(r.risky).toContain('kimi');
  });
  it('unknown reliability is never safe (fail-closed)', () => {
    const r = recommend(est(3000), CAP, DEFAULT_THRESHOLDS);
    expect(r.safe).not.toContain('mystery');
  });
  it('mid combo → free at risk', () => {
    const r = recommend(est(6000), CAP, DEFAULT_THRESHOLDS);
    expect(r.verdict).toBe('free_at_risk');
  });
  it('heavy combo → needs paid', () => {
    const r = recommend(est(9000), CAP, DEFAULT_THRESHOLDS);
    expect(r.verdict).toBe('needs_paid');
  });
  it('flags risky cast pins with a reason', () => {
    const r = recommend(est(3000), CAP, DEFAULT_THRESHOLDS);
    const mox = r.castPinRisks.find((c) => c.agent === 'Mox');
    expect(mox?.lane).toBe('kimi');
    expect(mox?.reason).toMatch(/truncat/i);
  });
});
