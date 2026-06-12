/**
 * CityNameChip tests (EM-188 item 3) — the city's title as a HUD chip:
 *   • renders world.town_name ONCE when present
 *   • ABSENT-SAFE: missing / null / empty / whitespace ⇒ renders nothing
 *     (mock mode and pre-naming snapshots lack town_name)
 *   • token-styled DOM (no inline styles — design-token-guard)
 */

import { describe, expect, it, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { CityNameChip } from './CityNameChip';

afterEach(cleanup);

describe('EM-188 — CityNameChip', () => {
  it('renders the town name exactly once', () => {
    const { getAllByTestId } = render(<CityNameChip name="New Emergence" />);
    const chips = getAllByTestId('city-name-chip');
    expect(chips).toHaveLength(1);
    expect(chips[0].textContent).toContain('New Emergence');
  });

  it('is absent-safe: missing/null/empty/whitespace names render nothing', () => {
    for (const name of [undefined, null, '', '   ']) {
      const { container, unmount } = render(<CityNameChip name={name} />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it('styles via token classes, never inline styles (design-token-guard)', () => {
    const { getByTestId } = render(<CityNameChip name="Petriville" />);
    const chip = getByTestId('city-name-chip');
    expect(chip.getAttribute('style')).toBeNull();
    expect(chip.className).toContain('bg-lab-surface');
    expect(chip.className).toContain('text-lab-text');
  });
});
