/**
 * StorylinesRail (EM-312) — the feed's drama index. A collapsible left-column
 * section (modeled on WarPanel/BillboardPanel) that pins the town's recurring
 * threads — RIVALRY / REDEMPTION / POWER GRAB — each with a live status chip and
 * a "story so far" recap assembled VERBATIM from the event log. Clicking a
 * storyline selects it: the parent filters the feed to that thread's principals
 * and (with the 3-D view up) snaps a tether between them.
 *
 * ZERO-LLM, pure presentation over lib/storylines.ts — recomputed live from the
 * rolling history + world_state, exactly like the StorySoFar digest. It never
 * touches sim state.
 *
 * EMPTY RENDERS NOTHING — with no promoted threads the section returns null, so
 * a fresh/quiet town adds zero chrome (and the whole feature is gated OFF by
 * default at the mount site, so the golden UI stays byte-identical).
 *
 * Hysteresis is stateful-but-display-only: the previous pass's active ids live
 * in a ref (NOT sim state) and are fed back into applyHysteresis so a thread
 * hovering at the promote line stays put instead of blinking.
 *
 * The scoring lives in the exported useStorylines hook so the PARENT owns the
 * live scored set: the selection is stored as an ID and re-resolved against
 * that set each render, so a thread that persists but evolves (a power grab
 * recruiting new allies) never leaves click-time principals/title stale in the
 * feed filter or the 3-D tether.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { WorldEvent, WorldState } from '../../types';
import {
  scoreStorylines,
  applyHysteresis,
  type Storyline,
  type StorylineKind,
} from '../../lib/storylines';
import '../../inspector/inspector-tokens.css';
import '../panels/roster-tokens.css';

interface StorylinesRailProps {
  /** The live promoted threads (from useStorylines — the parent owns them). */
  storylines: Storyline[];
  /** Currently-selected thread id (drives the feed filter + tether). */
  selectedId: string | null;
  /** Select a thread (or null to clear). The parent owns the selection. */
  onSelect: (storyline: Storyline | null) => void;
}

/**
 * Score the log into the promoted, sticky storyline set. Pure presentation
 * state: the hysteresis feedback lives in a ref, never sim state. `enabled`
 * short-circuits the O(n) scoring when the rail is flag-gated off (it must be
 * a render-stable flag — it only toggles what the memos compute, not hooks).
 */
export function useStorylines(
  history: WorldEvent[],
  world: WorldState | null,
  enabled = true,
): Storyline[] {
  const candidates = useMemo(
    () => (enabled ? scoreStorylines(history, world) : []),
    [enabled, history, world],
  );

  // Two-threshold hysteresis fed from the PREVIOUS pass's active ids (a
  // display-only ref, never sim state) so the rail is sticky, not flickery.
  const prevActiveIds = useRef<Set<string>>(new Set());
  const storylines = useMemo(
    () => applyHysteresis(candidates, prevActiveIds.current),
    [candidates],
  );
  useEffect(() => {
    prevActiveIds.current = new Set(storylines.map((s) => s.id));
  }, [storylines]);

  return storylines;
}

const COLLAPSE_KEY = 'em.storylines.collapsed';

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

/** Per-archetype badge label + token color (design-token-guard: var()s only). */
const KIND_META: Record<string, { label: string; color: string }> = {
  RIVALRY: { label: 'RIVALRY', color: 'var(--marker-crime)' },
  REDEMPTION: { label: 'REDEMPTION', color: 'var(--rel-family)' },
  POWER_GRAB: { label: 'POWER GRAB', color: 'var(--faction-tint)' },
  // War (EM-259) slots into the same container/rail — same crime-red register.
  WAR: { label: 'WAR', color: 'var(--marker-crime)' },
};

function kindMeta(kind: StorylineKind): { label: string; color: string } {
  return KIND_META[kind] ?? { label: String(kind), color: 'var(--marker-crime)' };
}

export function StorylinesRail({ storylines, selectedId, onSelect }: StorylinesRailProps) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
  }, [collapsed]);

  // If the selected thread decayed out of the active set, drop the selection so
  // the feed filter / tether don't cling to a thread that's no longer shown.
  useEffect(() => {
    if (selectedId && !storylines.some((s) => s.id === selectedId)) onSelect(null);
  }, [selectedId, storylines, onSelect]);

  // Nothing promoted ⇒ render nothing at all (golden-safe; the feature also
  // gates OFF at the mount site, so this is the quiet-town / flag-off shape).
  if (storylines.length === 0) return null;

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label="Storylines — the town's running drama threads"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">
          ✦ STORYLINES
        </h2>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-lab-muted tabular-nums">
            {storylines.length}
          </span>
          {selectedId && (
            <button
              type="button"
              onClick={() => onSelect(null)}
              className="font-mono text-[10px] px-1.5 py-0.5 border border-lab-acid text-lab-acid
                         rounded-sm hover:bg-lab-acid/15 cursor-pointer transition-colors duration-100"
              title="Clear the storyline filter"
            >
              CLEAR ✕
            </button>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand the storylines rail' : 'Collapse the storylines rail'}
            title={collapsed ? 'Expand the storylines rail' : 'Collapse the storylines rail'}
            className="font-mono text-[10px] px-1.5 py-0.5 border border-lab-border text-lab-muted
                       hover:border-lab-acid hover:text-lab-acid rounded-sm cursor-pointer
                       transition-colors duration-100"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <ul className="m-0 p-0 list-none max-h-72 overflow-y-auto">
          {storylines.map((s) => (
            <StorylineRow
              key={s.id}
              storyline={s}
              selected={s.id === selectedId}
              onClick={() => onSelect(s.id === selectedId ? null : s)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function StorylineRow({
  storyline: s,
  selected,
  onClick,
}: {
  storyline: Storyline;
  selected: boolean;
  onClick: () => void;
}) {
  const meta = kindMeta(s.kind);
  return (
    <li
      className={`border-b border-lab-border/40 ${selected ? 'bg-lab-acid/10' : ''}`}
      style={{ borderLeft: `3px solid ${meta.color}` }}
    >
      <button
        type="button"
        onClick={onClick}
        aria-pressed={selected}
        title={selected ? 'Click to clear this storyline filter' : 'Click to follow this storyline in the feed'}
        className="w-full text-left px-3 py-1.5 cursor-pointer hover:bg-lab-chrome/60 transition-colors duration-100"
      >
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            className="font-mono text-[9px] uppercase tracking-wider px-1 py-px border rounded-sm whitespace-nowrap"
            style={{ color: meta.color, borderColor: meta.color }}
          >
            {meta.label}
          </span>
          <span className="font-mono text-[11px] text-lab-text font-semibold break-words min-w-0">
            {s.title}
          </span>
          <span
            className="ml-auto font-mono text-[9px] uppercase tracking-wider tabular-nums whitespace-nowrap"
            style={{ color: meta.color }}
          >
            {s.status}
          </span>
        </div>

        {/* "Story so far" — VERBATIM beats from the log, newest-first. Shown
            when the thread is selected so the collapsed rail stays scannable. */}
        {selected && s.beats.length > 0 && (
          <ol className="m-0 mt-1 p-0 list-none space-y-0.5" aria-label="Story so far">
            {s.beats.map((b) => (
              <li
                key={b.seq}
                className="flex gap-1.5 font-mono text-[10px] leading-snug text-lab-muted"
              >
                <span className="text-lab-dim tabular-nums shrink-0">t{b.tick}</span>
                <span className="break-words min-w-0">{b.text}</span>
              </li>
            ))}
          </ol>
        )}
      </button>
    </li>
  );
}
