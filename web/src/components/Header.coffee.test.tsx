/**
 * Header — VITE_COFFEE_BUTTON flag tests.
 *
 * Verifies the "Buy me a coffee" link shows by default and is hidden when the
 * flag is set to any of the recognised falsy string values ("false", "0", "off").
 *
 * Header uses useLocation, so every render is wrapped in a MemoryRouter.
 * vi.stubEnv mutates import.meta.env in-place; isCoffeeButtonEnabled() reads
 * it at render time so stubs take effect without module re-loading.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Header } from './Header';

const defaultProps = {
  tick: 0,
  day: 1,
  running: false,
  connected: true,
  mockMode: false,
};

function renderHeader() {
  return render(
    <MemoryRouter>
      <Header {...defaultProps} />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('Header — VITE_COFFEE_BUTTON flag', () => {
  it('shows the coffee link by default (flag unset)', () => {
    // No stub — VITE_COFFEE_BUTTON is absent, which means enabled.
    renderHeader();
    expect(screen.getByRole('link', { name: /buy me a coffee/i })).toBeInTheDocument();
  });

  it('hides the coffee link when flag is "false"', () => {
    vi.stubEnv('VITE_COFFEE_BUTTON', 'false');
    renderHeader();
    expect(screen.queryByRole('link', { name: /buy me a coffee/i })).not.toBeInTheDocument();
  });

  it('hides the coffee link when flag is "0"', () => {
    vi.stubEnv('VITE_COFFEE_BUTTON', '0');
    renderHeader();
    expect(screen.queryByRole('link', { name: /buy me a coffee/i })).not.toBeInTheDocument();
  });

  it('hides the coffee link when flag is "off"', () => {
    vi.stubEnv('VITE_COFFEE_BUTTON', 'off');
    renderHeader();
    expect(screen.queryByRole('link', { name: /buy me a coffee/i })).not.toBeInTheDocument();
  });

  it('shows the coffee link when flag is "1" (explicit non-falsy value)', () => {
    vi.stubEnv('VITE_COFFEE_BUTTON', '1');
    renderHeader();
    expect(screen.getByRole('link', { name: /buy me a coffee/i })).toBeInTheDocument();
  });
});
