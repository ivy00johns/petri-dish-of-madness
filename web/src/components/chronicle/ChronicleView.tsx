/**
 * ChronicleView (EM-201) — the Chronicle tab: a full-width READING view of the
 * town's emergent saga, chapter by chapter.
 *
 * The backend chronicler emits one `narrator_summary` per window — a narrated
 * CHAPTER threading the previous one. This view is a pure projection over the
 * event history: it gathers those chapters in order and shows one at a time with
 * prev/next navigation (latest by default).
 *
 * Plus the **backfill**: a "Build from history" button POSTs /api/chronicle/build
 * to chronicle the EXISTING run as chapters (they stream in live as events). A
 * model PICKER chooses who narrates — default FREE (the configured narrator
 * lane), opt into any profile; never forces a paid lane.
 *
 * Degrades to a labelled empty state before the first chapter exists.
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
  const [selected, setSelected] = useState<number | null>(null); // null = latest
  const [model, setModel] = useState(''); // '' = default (free) narrator lane
  const [building, setBuilding] = useState(false);
  const [buildMsg, setBuildMsg] = useState<string | null>(null);

  const profiles = world?.profiles ?? [];
  const townName =
    (world as { town_name?: string } | null)?.town_name?.trim() || '';

  async function build() {
    setBuilding(true);
    setBuildMsg(null);
    try {
      const res = await fetch('/api/chronicle/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(model ? { model } : {}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setBuildMsg(`Couldn't build: ${data.detail ?? res.status}`);
      } else if (data.status === 'already_running') {
        setBuildMsg('Already building the chronicle…');
      } else {
        setBuildMsg(
          `Building from history (${data.model}) — chapters appear as they're written.`,
        );
      }
    } catch {
      setBuildMsg("Couldn't reach the backend.");
    } finally {
      setBuilding(false);
    }
  }

  const toolbar = (
    <div className="shrink-0 flex flex-wrap items-center gap-2 border-b border-lab-border px-4 py-2 bg-lab-surface">
      <h2 className="font-mono text-xs uppercase tracking-widest text-lab-acid mr-auto">
        📖 The Chronicle{townName ? ` of ${townName}` : ''}
      </h2>
      <label className="font-mono text-[10px] uppercase text-lab-muted flex items-center gap-1">
        Narrator
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          aria-label="Chronicle model"
          className="font-mono text-[10px] bg-lab-chrome border border-lab-border text-lab-text rounded-sm px-1 py-0.5"
        >
          <option value="">Default (free)</option>
          {profiles.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        onClick={build}
        disabled={building}
        title="Generate chapters for the run's existing history"
        className="font-mono text-[10px] uppercase tracking-wide px-2 py-0.5 border border-lab-acid text-lab-acid bg-lab-chrome rounded-sm hover:bg-lab-border disabled:opacity-50 disabled:cursor-default transition-colors"
      >
        {building ? 'Building…' : 'Build from history'}
      </button>
    </div>
  );

  const idx = chapters.length ? selected ?? chapters.length - 1 : 0;
  const chapter = chapters[idx];

  return (
    <section className="flex-1 min-h-0 flex flex-col bg-lab-bg" aria-label="The Chronicle">
      {toolbar}
      {buildMsg && (
        <div
          className="shrink-0 px-4 py-1.5 font-mono text-[11px] text-lab-muted bg-lab-chrome border-b border-lab-border"
          role="status"
        >
          {buildMsg}
        </div>
      )}

      {chapters.length === 0 ? (
        <div className="flex-1 min-h-0 overflow-y-auto flex items-center justify-center p-8">
          <div className="max-w-md text-center">
            <div className="text-3xl mb-3" aria-hidden="true">📖</div>
            <p className="text-lab-muted text-sm leading-relaxed">
              The chronicle has not yet begun. New chapters are written as the town
              lives — or hit <span className="text-lab-acid">Build from history</span>{' '}
              to chronicle the saga so far.
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="flex-1 min-h-0 overflow-y-auto">
            <article className="mx-auto max-w-2xl px-6 py-8">
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

          <nav className="shrink-0 flex items-center justify-center gap-3 border-t border-lab-border px-4 py-2 bg-lab-surface">
            <button
              type="button"
              disabled={idx <= 0}
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
              disabled={idx >= chapters.length - 1}
              onClick={() => setSelected(Math.min(chapters.length - 1, idx + 1))}
              className="font-mono text-[11px] uppercase px-2 py-0.5 border border-lab-border text-lab-text rounded-sm hover:bg-lab-border hover:text-lab-acid disabled:opacity-40 disabled:cursor-default transition-colors"
            >
              Next ▶
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
