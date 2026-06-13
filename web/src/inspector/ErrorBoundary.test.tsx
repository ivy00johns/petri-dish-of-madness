/**
 * Wave F (EM-151) — per-panel ErrorBoundary.
 *
 * The white-panel symptom: one panel throwing on hostile run data unmounted
 * the whole annex. The boundary must render a LABELED dead-panel fallback
 * (panel name + "the rest of the annex is fine") while sibling panels keep
 * rendering, and "retry panel" must remount the children.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { ErrorBoundary } from './ErrorBoundary';

let detonated = true;

function Bomb() {
  if (detonated) throw new Error('node not found: bld_42');
  return <p>panel recovered</p>;
}

beforeEach(() => {
  detonated = true;
  // React + the boundary both console.error the crash — keep test output quiet.
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ErrorBoundary — EM-151 panel isolation', () => {
  it('renders the labeled dead-panel fallback instead of blanking', () => {
    render(
      <ErrorBoundary name="Social Graph">
        <Bomb />
      </ErrorBoundary>,
    );
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent(/this panel crashed — Social Graph; the rest of the annex is fine\./);
    // The underlying error is surfaced for diagnosis, not swallowed silently.
    expect(alert).toHaveTextContent('node not found: bld_42');
  });

  it('a crashing panel leaves its SIBLING panels alive', () => {
    render(
      <div>
        <ErrorBoundary name="Social Graph">
          <Bomb />
        </ErrorBoundary>
        <ErrorBoundary name="AWI Dashboard">
          <p>healthy sibling panel</p>
        </ErrorBoundary>
      </div>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/Social Graph/);
    expect(screen.getByText('healthy sibling panel')).toBeInTheDocument();
  });

  it('"retry panel" remounts the children', () => {
    render(
      <ErrorBoundary name="Decision Trace">
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    detonated = false;
    fireEvent.click(screen.getByRole('button', { name: /retry panel/i }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('panel recovered')).toBeInTheDocument();
  });

  it('renders children untouched when nothing throws', () => {
    detonated = false;
    render(
      <ErrorBoundary name="Animal Chaos Feed">
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('panel recovered')).toBeInTheDocument();
  });
});
