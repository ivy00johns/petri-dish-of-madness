/**
 * expandSection — test helper to open a collapsible ControlPanel <Section> by
 * its disclosure-header name (e.g. /GOD CONSOLE/i).
 *
 * The redesigned god controls (EM-216 controls redesign) render each group
 * behind a collapsible header; collapsed bodies unmount, and the open/closed
 * state persists to localStorage per section id. This helper is IDEMPOTENT — it
 * only clicks when the section is collapsed — so it is safe to call even when a
 * prior test in the same file left the section open in localStorage.
 */
import { fireEvent, screen } from '@testing-library/react';

export function expandSection(name: RegExp | string): void {
  const header = screen.getByRole('button', { name });
  if (header.getAttribute('aria-expanded') !== 'true') {
    fireEvent.click(header);
  }
}
