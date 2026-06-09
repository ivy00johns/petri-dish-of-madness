/**
 * InspectorPanelStub — shared presentational shell for the W6 stage-1 panel
 * STUBS (DecisionTrace / GovernanceHistory / SocialGraph / AWIDashboard).
 *
 * Stage-2 agents REPLACE the four panel files with their real implementations
 * and drop this import; this file then becomes dead and can be removed. It
 * exists only so the stubs share one labeled "loading…" look while keeping the
 * PanelProps contract importable and the layout compiling.
 *
 * Token-only (lab-* classes); no inline styles / hardcoded colors.
 */

interface PanelStubProps {
  title: string;
  /** Tracking item (e.g. EM-056). */
  item: string;
  /** One-line description of what the real panel will show. */
  blurb: string;
  /** Live detail line proving real data is flowing through PanelProps. */
  detail: string;
}

export function InspectorPanelStub({ title, item, blurb, detail }: PanelStubProps) {
  return (
    <section
      className="lab-panel flex flex-col h-full min-h-[9rem]"
      aria-label={`${title} panel (stage-2 build)`}
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <span>{title}</span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          {item}
        </span>
      </div>
      <div className="flex-1 flex flex-col items-center justify-center gap-2 px-4 py-6 text-center">
        <p className="font-mono text-xs text-lab-muted leading-relaxed max-w-prose">{blurb}</p>
        <p className="font-mono text-[10px] text-lab-acid-dim tabular-nums">{detail}</p>
        <span className="font-mono text-[10px] uppercase tracking-widest text-lab-dim border border-lab-border px-2 py-0.5 animate-pulse">
          Loading… (stage-2)
        </span>
      </div>
    </section>
  );
}
