/**
 * EM-315 — The Healing House in the live feed. The `sentenced_healing` verdict
 * card must (a) register in all three feed registries (KIND_ICON,
 * KIND_FALLBACK_COLOR as a token var(), and exactly ONE category — a missing
 * entry silently breaks the inclusion filter), (b) land in the Rules lane it is
 * decided by, and (c) render its ⚕ SENTENCED line alongside the shared
 * `model_reassigned` transplant that morphs the model chip. Mirrors
 * EventFeed.war.test.tsx.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventFeed, KIND_ICON, KIND_FALLBACK_COLOR, CATEGORIES } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';

beforeEach(() => {
  resetSeq();
  localStorage.clear(); // the feed persists its filter focus
});

describe('EM-315 sentenced_healing — all three feed registries', () => {
  it('has the ⚕ icon', () => {
    expect(KIND_ICON['sentenced_healing']).toBe('⚕');
  });

  it('has a fallback color declared as a token var()', () => {
    const color = KIND_FALLBACK_COLOR['sentenced_healing'];
    expect(color).toBeTruthy();
    expect(color).toMatch(/^var\(--[a-z-]+\)$/);
  });

  it('maps to exactly ONE category — the Rules lane', () => {
    const holders = CATEGORIES.filter((c) => c.kinds.includes('sentenced_healing'));
    expect(holders).toHaveLength(1);
    expect(holders[0].key).toBe('rules');
  });
});

describe('EventFeed — the Healing House narrative renders live', () => {
  it('shows the SENTENCED verdict then the chip-morphing transplant', () => {
    render(
      <EventFeed
        events={[
          ev({ kind: 'sentenced_healing', tick: 10, actor_id: 'system', target_id: 'b1',
               actor_type: 'system',
               text: '⚕ By vote, Bram is SENTENCED to the Healing House — the town remakes their mind.' }),
          ev({ kind: 'model_reassigned', tick: 10, actor_id: 'system', target_id: 'b1',
               actor_type: 'system', profile: 'cerebras-qwen',
               text: '⚕ Bram emerges from the Healing House — their mind remade (groq-llama → cerebras-qwen). Do they come back different?' }),
        ]}
      />,
    );
    expect(screen.getByText(/SENTENCED to the Healing House/)).toBeInTheDocument();
    expect(screen.getByText(/emerges from the Healing House/)).toBeInTheDocument();
  });
});
