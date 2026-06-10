/**
 * StorySoFar digest block (EM-146) — the digest must never push the feed (the
 * centerpiece) out of view: the body is height-capped + scrollable, and the
 * heading collapses it entirely, with the preference persisted across loads.
 * Selector logic (incl. the EM-144 stale-starvation guard) is covered in
 * lib/storySoFar.test.ts; this file pins the layout-safety affordances.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StorySoFar } from './StorySoFar';
import { agent, world } from '../../test-utils/fixtures';

const COLLAPSED_KEY = 'em.story.collapsed';

function renderDigest() {
  return render(
    <StorySoFar
      world={world({ agents: [agent({ id: 'ada', name: 'Ada' })] })}
      history={[]}
    />,
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe('StorySoFar — EM-146 layout safety', () => {
  it('renders the body height-capped and scrollable so the feed keeps its space', () => {
    renderDigest();
    const body = document.getElementById('story-so-far-body');
    expect(body).not.toBeNull();
    expect(body!.className).toContain('max-h-48');
    expect(body!.className).toContain('overflow-y-auto');
  });

  it('collapses via the heading toggle and persists the preference', async () => {
    const user = userEvent.setup();
    renderDigest();

    const toggle = screen.getByRole('button', { name: /story so far/i });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(document.getElementById('story-so-far-body')).toBeNull();
    expect(localStorage.getItem(COLLAPSED_KEY)).toBe('1');

    await user.click(toggle);
    expect(document.getElementById('story-so-far-body')).not.toBeNull();
    expect(localStorage.getItem(COLLAPSED_KEY)).toBe('0');
  });

  it('starts collapsed when the persisted preference says so', () => {
    localStorage.setItem(COLLAPSED_KEY, '1');
    renderDigest();
    expect(document.getElementById('story-so-far-body')).toBeNull();
    // The heading is still there to expand it again.
    expect(screen.getByRole('button', { name: /story so far/i })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  });
});
