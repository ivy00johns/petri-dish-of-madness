/**
 * EM-089 — the animal model chip in the feed.
 *
 * An animal_action carries no `profile` by design (it keeps the magenta critter
 * register); the model that decided the turn is sourced from the sibling animal
 * `llm_call` via animalModelByTurn. The feed names that model inline (next to
 * the 🧠 marker) so a viewer can tell WHICH model the critter is running — a
 * reflex bark (no sibling llm_call) stays unattributed.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EventFeed } from './EventFeed';
import { ev, resetSeq } from '../../test-utils/fixtures';

beforeEach(() => {
  resetSeq();
  localStorage.clear();
});

describe('EventFeed — animal model chip (EM-089)', () => {
  it('names the model + 🧠 on an LLM-decided animal action', () => {
    render(
      <EventFeed
        events={[
          ev({ kind: 'animal_action', actor_id: 'cat-1', actor_type: 'animal',
               turn_id: 'at-1', text: 'Mochi scratches at the stall.' }),
          // sibling animal llm_call (trace-category, not itself rendered) carries
          // the model identity for turn at-1.
          ev({ kind: 'llm_call', actor_id: 'cat-1', actor_type: 'animal',
               turn_id: 'at-1', profile: 'gemini-flash' }),
        ]}
      />,
    );
    expect(screen.getByText('gemini-flash')).toBeInTheDocument();
    expect(screen.getByText('🧠')).toBeInTheDocument();
  });

  it('shows no model chip on a reflex animal action (no sibling llm_call)', () => {
    render(
      <EventFeed
        events={[
          ev({ kind: 'animal_action', actor_id: 'cat-1', actor_type: 'animal',
               turn_id: 'at-9', text: 'Mochi naps in the sun.' }),
        ]}
      />,
    );
    expect(screen.getByText('Mochi naps in the sun.')).toBeInTheDocument();
    expect(screen.queryByText('gemini-flash')).not.toBeInTheDocument();
    expect(screen.queryByText('🧠')).not.toBeInTheDocument();
  });
});
