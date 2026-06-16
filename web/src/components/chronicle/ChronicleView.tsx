/**
 * ChronicleView (EM-201) — the Chronicle tab: a full-width READING view of the
 * town's emergent saga, chapter by chapter.
 *
 * The backend chronicler (loop._run_narrator) emits one `narrator_summary` per
 * window — a narrated CHAPTER that threads the previous one. This view is a pure
 * projection over the event history: it gathers those chapters in order and
 * presents one at a time with prev/next navigation, defaulting to the latest.
 * The "Deep dive" trigger (on-demand multi-pass synthesis) is wired in a later
 * slice; it is present but disabled here.
 *
 * Degrades to a labelled empty state before the first chapter exists (a fresh
 * run, or the narrator disabled) — never a blank screen.
 */
import { useMemo, useState } from 'react';

import type { WorldEvent, WorldState } from '../../types';

interface ChronicleViewProps {
  world: WorldState | null;
  history: WorldEvent[];
}

interface Chapter {
  text: string;
  fromTick: number;
  toTick: number;
  profile?: string;
}

/** Gather the narrated chapters from the event history, oldest → newest. */
export function readChapters(history: WorldEvent[]): Chapter[] {
  return history
    .filter((e) => e.kind === 'narrator_summary' && Boolean((e.text || '').trim()))
    .map((e) => ({
      text: (e.text || '').trim(),
      fromTick: Number(e.payload?.['from_tick'] ?? e.tick ?? 0),
      toTick: Number(e.payload?.['to_tick'] ?? e.tick ?? 0),
      profile: typeof e.profile === 'string' ? e.profile : undefined,
    }))
    .sort((a, b) => a.toTick - b.toTick || a.fromTick - b.fromTick);
}

export function ChronicleView({ world, history }: ChronicleViewProps) {
  const chapters = useMemo(() => readChapters(history), [history]);
  // null = pinned to the latest chapter; a number = the user navigated.
  const [selected, setSelected] = useState<number | null>(null);
  const townName =
    (world as { town_name?: string } | null)?.town_name?.trim() || '';

  if (chapters.length === 0) {
    return (
      <section
        className="flex-1 min-h-0 overflow-y-auto flex items-center justify-center p-8 bg-lab-bg"
        aria-label="The Chronicle"
      >
        <div className="max-w-md text-center">
          <div className="text-3xl mb-3" aria-hidden="true">📖</div>
          <h2 className="font-mono text-sm uppercase tracking-widest text-lab-acid mb-3">
            The Chronicle
          </h2>
          <p className="text-lab-muted text-sm leading-relaxed">
            The chronicle has not yet begun. Once the town has lived a while, its
            saga will be written here — chapter by chapter, as the story unfolds.
          </p>
        </div>
      </section>
    );
  }

  const idx = selected ?? chapters.length - 1;
  const chapter = chapters[idx];
  const atFirst = idx <= 0;
  const atLast = idx >= chapters.length - 1;

  return (
    <section
      className="flex-1 min-h-0 flex flex-col bg-lab-bg"
      aria-label="The Chronicle"
    >
      {/* Scrollable reading column */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <article className="mx-auto max-w-2xl px-6 py-8">
          <h2 className="font-mono text-xs uppercase tracking-widest text-lab-acid mb-1">
            📖 The Chronicle{townName ? ` of ${townName}` : ''}
          </h2>
          <div className="font-mono text-[11px] text-lab-dim tabular-nums mb-6">
            Chapter {idx + 1} of {chapters.length} · ticks {chapter.fromTick}–
            {chapter.toTick}
            {chapter.profile ? ` · ${chapter.profile}` : ''}
          </div>
          <p
            className="text-lab-text text-[15px] leading-loose whitespace-pre-line"
            data-testid="chapter-prose"
          >
            {chapter.text}
          </p>
        </article>
      </div>

      {/* Chapter navigation */}
      <nav className="shrink-0 flex items-center justify-center gap-3 border-t border-lab-border px-4 py-2 bg-lab-surface">
        <button
          type="button"
          disabled={atFirst}
          onClick={() => setSelected(Math.max(0, idx - 1))}
          className="font-mono text-[11px] uppercase px-2 py-0.5 border border-lab-border text-lab-text rounded-sm hover:bg-lab-border hover:text-lab-acid disabled:opacity-40 disabled:cursor-default transition-colors"
        >
          ◀ Prev
        </button>
        <span className="font-mono text-[11px] text-lab-muted tabular-nums">
          {idx + 1} / {chapters.length}
        </span>
        <button
          type="button"
          disabled={atLast}
          onClick={() => setSelected(Math.min(chapters.length - 1, idx + 1))}
          className="font-mono text-[11px] uppercase px-2 py-0.5 border border-lab-border text-lab-text rounded-sm hover:bg-lab-border hover:text-lab-acid disabled:opacity-40 disabled:cursor-default transition-colors"
        >
          Next ▶
        </button>
        <span className="text-lab-border" aria-hidden="true">
          |
        </span>
        <button
          type="button"
          disabled
          title="Deep-dive synthesis — coming in the next slice"
          className="font-mono text-[11px] uppercase px-2 py-0.5 border border-lab-border-bright text-lab-dim rounded-sm disabled:opacity-50 disabled:cursor-default"
        >
          Deep dive ⟶
        </button>
      </nav>
    </section>
  );
}
