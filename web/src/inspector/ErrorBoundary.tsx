/**
 * ErrorBoundary (wave F, EM-151) — per-panel crash isolation for the annex.
 *
 * The EM-151 white-panel symptom: one selector throwing on hostile run data
 * (run #189) unmounted the WHOLE inspector tree — every panel blanked because
 * React tears down to the nearest boundary, and there was none. Each grid
 * panel + the scrubber now mounts inside one of these, so a crash renders a
 * labeled dead-panel fallback and the rest of the annex keeps working.
 *
 * Class component by necessity: error boundaries are the one React feature
 * with no hook equivalent (getDerivedStateFromError/componentDidCatch).
 *
 * Token-only styling (lab-* classes) — no hardcoded design literals.
 */

import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface ErrorBoundaryProps {
  /** Human panel name for the labeled fallback ("Decision Trace", …). */
  name: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Console-surface the crash (the fallback shows the message; the stack
    // lives here for the dev tools). Never rethrows — isolation is the point.
    console.error(`[inspector] panel crashed: ${this.props.name}`, error, info.componentStack);
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (error === null) return this.props.children;
    return (
      <section
        role="alert"
        aria-label={`${this.props.name} crashed`}
        className="lab-panel flex flex-col h-full min-h-[9rem] border border-lab-danger"
      >
        <div className="lab-header flex items-center justify-between gap-2">
          <span className="text-lab-danger">{this.props.name}</span>
          <span className="font-mono text-[10px] text-lab-danger uppercase tracking-widest">
            crashed
          </span>
        </div>
        <div className="flex-1 min-h-0 flex flex-col items-center justify-center gap-2 px-4 py-6 text-center">
          <p className="font-mono text-[11px] font-bold text-lab-danger leading-relaxed">
            this panel crashed — {this.props.name}; the rest of the annex is fine.
          </p>
          <p className="font-mono text-[10px] text-lab-muted leading-relaxed break-all max-w-prose">
            {error.message || String(error)}
          </p>
          <button
            type="button"
            onClick={this.reset}
            className="font-mono text-[10px] font-bold px-2 py-0.5 border border-lab-border-bright text-lab-text bg-lab-bg hover:bg-lab-chrome uppercase tracking-wider"
          >
            retry panel
          </button>
        </div>
      </section>
    );
  }
}
