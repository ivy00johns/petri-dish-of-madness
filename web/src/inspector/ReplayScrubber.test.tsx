/**
 * ReplayScrubber smoke (EM-043 / audit C2) — the play/pause bug: the button
 * label rendered from a REF read in render, so clicking PLAY started the
 * interval but the DOM never flipped to PAUSE. The label/aria must render
 * from state.
 */
import { describe, expect, it, afterEach, beforeEach, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ReplayScrubber } from './ReplayScrubber';
import { agent, PLACES, profile } from '../test-utils/fixtures';

function renderScrubber(onSeek: (tick: number) => void = () => {}) {
  return render(
    <ReplayScrubber
      events={[]}
      agents={[agent({ id: 'a1' })]}
      profiles={[profile({ name: 'model-a' })]}
      places={PLACES}
      currentTick={0}
      maxTick={10}
      onSeek={onSeek}
    />,
  );
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('ReplayScrubber — play/pause render state (audit C2)', () => {
  it('clicking PLAY flips the button to PAUSE (and back)', () => {
    renderScrubber();
    const btn = screen.getByRole('button', { name: /play or pause the replay/i });
    expect(btn).toHaveTextContent('PLAY');
    expect(btn).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(btn);
    expect(btn).toHaveTextContent('PAUSE');
    expect(btn).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(btn);
    expect(btn).toHaveTextContent('PLAY');
    expect(btn).toHaveAttribute('aria-pressed', 'false');
  });

  it('playing advances the scrub tick via onSeek', () => {
    const onSeek = vi.fn();
    renderScrubber(onSeek);
    fireEvent.click(screen.getByRole('button', { name: /play or pause the replay/i }));
    vi.advanceTimersByTime(701); // BASE_STEP_MS at 1× speed
    expect(onSeek).toHaveBeenCalledWith(1);
  });
});

describe('ReplayScrubber — speed buttons', () => {
  it('clicking a speed updates aria-pressed on the speed group', () => {
    renderScrubber();
    const speed1 = screen.getByRole('button', { name: 'Set replay speed 1x' });
    const speed2 = screen.getByRole('button', { name: 'Set replay speed 2x' });
    expect(speed1).toHaveAttribute('aria-pressed', 'true');
    expect(speed2).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(speed2);
    expect(speed2).toHaveAttribute('aria-pressed', 'true');
    expect(speed1).toHaveAttribute('aria-pressed', 'false');
  });
});
