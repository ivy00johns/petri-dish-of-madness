/**
 * ChronicleView (EM-201) — the Chronicle tab: a data-dense "reading room"
 * with a chapter index (jump to ANY chapter), a story column with a scroll-progress
 * bar, and a chaos panel reconstructed from history events for the active chapter's
 * tick window.
 *
 * Three-region layout at lg+: [Chapter Index | Story | Chaos]
 * Below lg: both asides slide out as drawers toggled by header buttons.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { WorldEvent, WorldState } from '../../types';
import { chaosFacts, readChapters, toRoman } from './chronicle';

interface ChronicleViewProps {
  world: WorldState | null;
  history: WorldEvent[];
}

// ============================================================
// Chapter Index
// ============================================================

interface IndexPanelProps {
  chapters: ReturnType<typeof readChapters>;
  activeIdx: number;
  filter: string;
  onFilterChange: (v: string) => void;
  onSelect: (idx: number) => void;
  activeEntryRef: React.RefObject<HTMLButtonElement | null>;
}

function ChapterIndex({
  chapters,
  activeIdx,
  filter,
  onFilterChange,
  onSelect,
  activeEntryRef,
}: IndexPanelProps) {
  const filtered = useMemo(() => {
    if (!filter.trim()) return chapters.map((c, i) => ({ c, i }));
    const q = filter.toLowerCase();
    return chapters
      .map((c, i) => ({ c, i }))
      .filter(
        ({ c, i }) =>
          c.text.toLowerCase().includes(q) ||
          c.title.toLowerCase().includes(q) ||
          String(c.fromTick).includes(q) ||
          String(c.toTick).includes(q) ||
          String(i + 1).includes(q),
      );
  }, [chapters, filter]);

  return (
    <aside className="w-64 flex flex-col bg-lab-surface border-r border-lab-border overflow-hidden">
      {/* Header */}
      <div className="shrink-0 px-3 py-2 border-b border-lab-border">
        <span className="font-mono text-xs uppercase tracking-widest text-lab-muted-bright">
          Chapters · {chapters.length}
        </span>
      </div>

      {/* Filter */}
      <div className="shrink-0 px-2 py-2 border-b border-lab-border">
        <input
          className="lab-input w-full text-[11px] py-1"
          placeholder="Filter chapters…"
          value={filter}
          onChange={(e) => onFilterChange(e.target.value)}
          aria-label="Filter chapters"
        />
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <p className="font-mono text-[10px] text-lab-muted-bright px-3 py-4">No chapters match.</p>
        ) : (
          filtered.map(({ c, i }) => {
            const isActive = i === activeIdx;
            return (
              <button
                key={i}
                type="button"
                ref={isActive ? (activeEntryRef as React.RefObject<HTMLButtonElement>) : undefined}
                aria-current={isActive ? 'page' : undefined}
                onClick={() => onSelect(i)}
                className={[
                  'w-full text-left px-3 py-2.5 cursor-pointer transition-colors border-l-2',
                  isActive
                    ? 'border-lab-acid bg-lab-chrome'
                    : 'border-transparent hover:bg-lab-chrome',
                ].join(' ')}
              >
                {/* Row 1: roman numeral + tick range */}
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[10px] text-lab-acid font-semibold shrink-0">
                    {toRoman(i + 1)}
                  </span>
                  <span className="font-mono text-[9px] text-lab-muted-bright tabular-nums">
                    {c.fromTick}–{c.toTick}
                  </span>
                </div>
                {/* Row 2: derived title */}
                <p className="font-serif text-[12px] text-lab-text leading-snug line-clamp-2 mt-0.5">
                  {c.title}
                </p>
                {/* Row 3: model badge + version */}
                {(c.profile || c.chroniclerVersion !== undefined) && (
                  <span className="font-mono text-[9px] text-lab-muted-bright block mt-0.5 truncate">
                    {c.profile
                      ? c.routedVia && c.routedVia !== c.profile
                        ? `${c.profile} → ${c.routedVia}`
                        : c.profile
                      : ''}
                    {c.chroniclerVersion !== undefined
                      ? `${c.profile ? ' · ' : ''}chronicle v${c.chroniclerVersion}`
                      : ''}
                  </span>
                )}
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}

// ============================================================
// Chaos Panel
// ============================================================

function ChaosPanel({
  history,
  fromTick,
  toTick,
  payloadChaos,
}: {
  history: WorldEvent[];
  fromTick: number;
  toTick: number;
  payloadChaos?: import('./chronicle').ChaosFacts;
}) {
  // Prefer server-stamped payload facts; fall back to client reconstruction only
  // when payload is absent (legacy/unstamped chapters). This fixes all-zero stats
  // for old chapters that are no longer in the browser history buffer.
  const clientFacts = useMemo(
    () =>
      payloadChaos === undefined
        ? chaosFacts(history, fromTick, toTick)
        : null,
    [payloadChaos, history, fromTick, toTick],
  );
  const facts = payloadChaos ?? clientFacts!;

  const allEmpty =
    facts.cast.length === 0 &&
    facts.quotes.length === 0 &&
    facts.laws.length === 0 &&
    facts.conflicts.length === 0 &&
    facts.deaths.length === 0;

  return (
    <aside className="w-80 flex flex-col bg-lab-surface border-l border-lab-border overflow-hidden">
      <div className="shrink-0 px-3 py-2 border-b border-lab-border">
        <span className="font-mono text-xs uppercase tracking-widest text-lab-acid">
          The Chaos · ticks {fromTick}–{toTick}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-4">
        {/* Chaos meter chips */}
        <div className="flex flex-wrap gap-1.5">
          {([
            { label: 'SPOKEN', value: facts.counts.spoken, danger: false },
            { label: 'LAWS', value: facts.counts.laws, danger: false },
            { label: 'CLASHES', value: facts.counts.clashes, danger: false },
            { label: 'DEATHS', value: facts.counts.deaths, danger: facts.counts.deaths > 0 },
          ] as const).map(({ label, value, danger }) => (
            <span
              key={label}
              className={[
                'font-mono text-[10px] px-1.5 py-0.5 border border-lab-border bg-lab-chrome rounded-sm',
                danger ? 'text-lab-danger' : 'text-lab-muted-bright',
              ].join(' ')}
            >
              {label} {value}
            </span>
          ))}
        </div>

        {allEmpty ? (
          <p className="font-serif italic text-lab-muted-bright text-[13px] leading-relaxed">
            A quiet stretch — the town held its breath.
          </p>
        ) : (
          <>
            {/* Cast */}
            {facts.cast.length > 0 && (
              <section>
                <h3 className="font-mono text-[9px] uppercase tracking-widest text-lab-muted-bright mb-1.5">
                  Cast
                </h3>
                <div className="flex flex-wrap gap-1">
                  {facts.cast.map((name) => (
                    <span
                      key={name}
                      className="font-mono text-[10px] text-lab-text border border-lab-border bg-lab-chrome px-1.5 py-0.5 rounded-sm"
                    >
                      {name}
                    </span>
                  ))}
                </div>
              </section>
            )}

            {/* Memorable Lines */}
            {facts.quotes.length > 0 && (
              <section>
                <h3 className="font-mono text-[9px] uppercase tracking-widest text-lab-muted-bright mb-1.5">
                  Memorable Lines
                </h3>
                <div className="flex flex-col gap-3">
                  {facts.quotes.map(({ speaker, said }, qi) => (
                    <div key={qi}>
                      <div className="font-mono text-[9px] text-lab-muted-bright mb-0.5">{speaker}</div>
                      <p className="font-serif italic text-[12px] text-lab-text leading-snug">
                        "{said}"
                      </p>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Laws & Namings */}
            {facts.laws.length > 0 && (
              <section>
                <h3 className="font-mono text-[9px] uppercase tracking-widest text-lab-muted-bright mb-1.5">
                  Laws &amp; Namings
                </h3>
                <ul className="flex flex-col gap-1.5">
                  {facts.laws.map((law, li) => (
                    <li key={li} className="font-mono text-[10px] text-lab-text leading-snug">
                      {law}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Conflict */}
            {facts.conflicts.length > 0 && (
              <section>
                <h3 className="font-mono text-[9px] uppercase tracking-widest text-lab-muted-bright mb-1.5">
                  Conflict
                </h3>
                <ul className="flex flex-col gap-1.5">
                  {facts.conflicts.map((c, ci) => (
                    <li key={ci} className="font-mono text-[10px] text-lab-warn leading-snug">
                      {c}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* Deaths */}
            {facts.deaths.length > 0 && (
              <section>
                <h3 className="font-mono text-[9px] uppercase tracking-widest text-lab-muted-bright mb-1.5">
                  Deaths
                </h3>
                <ul className="flex flex-col gap-1.5">
                  {facts.deaths.map((d, di) => (
                    <li key={di} className="font-mono text-[10px] text-lab-muted-bright leading-snug">
                      {d}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

// ============================================================
// Main component
// ============================================================

export function ChronicleView({ world, history }: ChronicleViewProps) {
  const chapters = useMemo(() => readChapters(history), [history]);
  const [selected, setSelected] = useState<number | null>(null); // null = latest
  const [model, setModel] = useState('');
  const [building, setBuilding] = useState(false);
  const [buildMsg, setBuildMsg] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [scrollPct, setScrollPct] = useState(0);
  const [indexOpen, setIndexOpen] = useState(false);
  const [chaosOpen, setChaosOpen] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const activeEntryRef = useRef<HTMLButtonElement | null>(null);

  const profiles = world?.profiles ?? [];
  const townName = world?.town_name?.trim() || '';

  const N = chapters.length;
  // Clamp idx: if selected is null → last; if chapters just grew and selected is OOB → last
  const idx = N > 0 ? (selected === null ? N - 1 : Math.min(selected, N - 1)) : 0;
  const chapter = chapters[idx];

  // Auto-scroll the active index entry into view whenever the active chapter changes
  useEffect(() => {
    const el = activeEntryRef.current;
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'nearest' });
    }
  }, [idx]);

  // Reset scroll progress when chapter changes
  useEffect(() => {
    setScrollPct(0);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [idx]);

  // Keyboard navigation — ArrowLeft/Right; guard: ignore inside inputs
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      // Escape closes any open drawer, regardless of focus.
      if (e.key === 'Escape') {
        setIndexOpen(false);
        setChaosOpen(false);
        return;
      }
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target?.isContentEditable) {
        return;
      }
      if (!N) return;
      if (e.key === 'ArrowLeft') {
        setSelected((prev) => {
          const cur = prev === null ? N - 1 : Math.min(prev, N - 1);
          return Math.max(0, cur - 1);
        });
      } else if (e.key === 'ArrowRight') {
        setSelected((prev) => {
          const cur = prev === null ? N - 1 : Math.min(prev, N - 1);
          return Math.min(N - 1, cur + 1);
        });
      }
    }
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [N]);

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const el = e.currentTarget;
    const pct = el.scrollHeight > el.clientHeight
      ? el.scrollTop / (el.scrollHeight - el.clientHeight)
      : 0;
    setScrollPct(pct);
  }, []);

  function selectChapter(i: number) {
    setSelected(i);
    setIndexOpen(false);
    setChaosOpen(false);
  }

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

  async function rebuild() {
    setBuilding(true);
    setBuildMsg(null);
    try {
      const res = await fetch('/api/chronicle/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rebuild: true, ...(model ? { model } : {}) }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setBuildMsg(`Couldn't rebuild: ${data.detail ?? res.status}`);
      } else if (data.status === 'already_running') {
        setBuildMsg('Already building the chronicle…');
      } else {
        setBuildMsg('Rebuilding all chapters…');
      }
    } catch {
      setBuildMsg("Couldn't reach the backend.");
    } finally {
      setBuilding(false);
    }
  }

  // EM-225 — request a MULTI-PASS deep dive: a richer one-off saga reviewed per
  // dimension (governance / chat / growth) then synthesised. Off the agent
  // critical path; the chapter streams in as a deep-dive narrator_summary.
  async function deepDive() {
    setBuilding(true);
    setBuildMsg(null);
    try {
      const res = await fetch('/api/chronicle/deepdive', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(model ? { model } : {}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setBuildMsg(`Couldn't deep dive: ${data.detail ?? res.status}`);
      } else if (data.status === 'already_running') {
        setBuildMsg('A deep dive is already underway…');
      } else {
        setBuildMsg(
          `Deep dive underway (${data.model}) — a richer chapter appears when the passes finish.`,
        );
      }
    } catch {
      setBuildMsg("Couldn't reach the backend.");
    } finally {
      setBuilding(false);
    }
  }

  // ---- Toolbar ----
  const toolbar = (
    <div className="shrink-0 flex flex-wrap items-center gap-2 border-b border-lab-border px-4 py-2 bg-lab-surface">
      <h2 className="font-mono text-xs uppercase tracking-widest text-lab-acid mr-auto">
        <span aria-hidden="true">📖</span>{' '}
        The Chronicle{townName ? ` of ${townName}` : ''}
      </h2>
      <label className="font-mono text-[10px] uppercase text-lab-muted-bright flex items-center gap-1">
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
        className="font-mono text-[10px] uppercase tracking-wide px-2 py-0.5 border border-lab-acid text-lab-acid bg-lab-chrome rounded-sm hover:bg-lab-border disabled:opacity-50 disabled:cursor-default transition-colors cursor-pointer"
      >
        {building ? 'Building…' : 'Build from history'}
      </button>
      <button
        type="button"
        onClick={rebuild}
        disabled={building}
        title="Re-generate ALL chapters from scratch, stamping server-computed chaos facts"
        className="font-mono text-[10px] uppercase tracking-wide px-2 py-0.5 border border-lab-border text-lab-muted-bright bg-lab-chrome rounded-sm hover:bg-lab-border hover:text-lab-text disabled:opacity-50 disabled:cursor-default transition-colors cursor-pointer"
      >
        Rebuild all
      </button>
      <button
        type="button"
        onClick={deepDive}
        disabled={building}
        title="Multi-pass deep dive: review the whole run per dimension (governance / chat / growth), then synthesise one richer chapter"
        className="font-mono text-[10px] uppercase tracking-wide px-2 py-0.5 border border-lab-acid text-lab-acid bg-lab-chrome rounded-sm hover:bg-lab-acid hover:text-lab-bg disabled:opacity-50 disabled:cursor-default transition-colors cursor-pointer"
      >
        <span aria-hidden="true">🔬</span> Deep Dive
      </button>
    </div>
  );

  // ---- Empty state ----
  if (N === 0) {
    return (
      <section className="flex-1 min-h-0 flex flex-col bg-lab-bg" aria-label="The Chronicle">
        {toolbar}
        {buildMsg && (
          <div
            className="shrink-0 px-4 py-1.5 font-mono text-[11px] text-lab-muted-bright bg-lab-chrome border-b border-lab-border"
            role="status"
          >
            {buildMsg}
          </div>
        )}
        <div className="flex-1 min-h-0 overflow-y-auto flex items-center justify-center p-8">
          <div className="max-w-md text-center">
            <div className="text-3xl mb-3" aria-hidden="true">📖</div>
            <p className="font-mono text-lab-muted-bright text-sm leading-relaxed">
              The chronicle has not yet begun. New chapters are written as the town
              lives — or hit{' '}
              <span className="text-lab-acid">Build from history</span>{' '}
              to chronicle the saga so far.
            </p>
          </div>
        </div>
      </section>
    );
  }

  // ---- Full reading room ----
  const paragraphs = chapter.text.split(/\n{2,}/);

  return (
    <section className="flex-1 min-h-0 flex flex-col bg-lab-bg" aria-label="The Chronicle">
      {toolbar}
      {buildMsg && (
        <div
          className="shrink-0 px-4 py-1.5 font-mono text-[11px] text-lab-muted-bright bg-lab-chrome border-b border-lab-border"
          role="status"
        >
          {buildMsg}
        </div>
      )}

      {/* Main body: three columns at lg+ */}
      <div className="flex-1 min-h-0 flex relative overflow-hidden">

        {/* ---- Mobile backdrop ---- */}
        {(indexOpen || chaosOpen) && (
          <div
            className="absolute inset-0 z-20 bg-black/60 lg:hidden"
            onClick={() => { setIndexOpen(false); setChaosOpen(false); }}
            aria-hidden="true"
          />
        )}

        {/* ---- Chapter Index (lg: static, mobile: drawer) ---- */}
        <div
          className={[
            'absolute inset-y-0 left-0 z-30 transition-transform duration-200',
            'lg:static lg:flex lg:translate-x-0',
            indexOpen
              ? 'flex translate-x-0 visible'
              : '-translate-x-full invisible lg:translate-x-0 lg:visible',
          ].join(' ')}
        >
          <ChapterIndex
            chapters={chapters}
            activeIdx={idx}
            filter={filter}
            onFilterChange={setFilter}
            onSelect={selectChapter}
            activeEntryRef={activeEntryRef}
          />
        </div>

        {/* ---- Story (center) ---- */}
        <main className="flex-1 min-w-0 flex flex-col overflow-hidden">
          {/* Story header with mobile drawer toggles */}
          <div className="shrink-0 flex items-center gap-2 px-3 py-1.5 border-b border-lab-border bg-lab-surface">
            {/* Hamburger: Chapters toggle (mobile only) */}
            <button
              type="button"
              className="lg:hidden font-mono text-[10px] text-lab-muted-bright flex items-center gap-1.5 cursor-pointer hover:text-lab-text transition-colors"
              onClick={() => { setIndexOpen((o) => !o); setChaosOpen(false); }}
              aria-label="Toggle chapter index"
              aria-expanded={indexOpen}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true"
                   stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <line x1="1" y1="3" x2="13" y2="3" />
                <line x1="1" y1="7" x2="13" y2="7" />
                <line x1="1" y1="11" x2="13" y2="11" />
              </svg>
              Chapters
            </button>

            {/* Chapter meta (center) */}
            <span className="flex-1 font-mono text-[10px] text-lab-muted-bright text-center tabular-nums truncate">
              {toRoman(idx + 1)} · ticks {chapter.fromTick}–{chapter.toTick}
            </span>

            {/* Chaos toggle (mobile only) */}
            <button
              type="button"
              className="lg:hidden font-mono text-[10px] text-lab-muted-bright hover:text-lab-text transition-colors cursor-pointer"
              onClick={() => { setChaosOpen((o) => !o); setIndexOpen(false); }}
              aria-label="Toggle chaos panel"
              aria-expanded={chaosOpen}
            >
              Chaos
            </button>
          </div>

          {/* Scroll progress bar */}
          <div className="shrink-0 h-0.5 bg-lab-chrome relative">
            <div
              className="absolute inset-y-0 left-0 bg-lab-acid"
              style={{ width: `${scrollPct * 100}%` }}
            />
          </div>

          {/* Scroll container */}
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto"
            onScroll={handleScroll}
          >
            <article className="mx-auto max-w-[68ch] px-6 sm:px-10 py-10">
              {/* Chapter header */}
              <header className="mb-8">
                <div className="flex items-center gap-3 mb-3">
                  <div className="font-serif text-6xl text-lab-acid leading-none">
                    {toRoman(idx + 1)}
                  </div>
                  {chapter.mode === 'deepdive' && (
                    <span
                      data-testid="deepdive-badge"
                      className="font-mono text-[10px] uppercase tracking-widest text-lab-bg bg-lab-acid px-2 py-0.5 rounded-sm self-center"
                    >
                      🔬 Deep Dive
                    </span>
                  )}
                </div>
                <p className="font-mono text-[11px] text-lab-muted-bright tabular-nums">
                  {chapter.mode === 'deepdive' ? 'Deep Dive' : `Chapter ${idx + 1} of ${N}`} · ticks{' '}
                  {chapter.fromTick}–{chapter.toTick}
                  {chapter.profile
                    ? ` · ${
                        chapter.routedVia && chapter.routedVia !== chapter.profile
                          ? `${chapter.profile} → ${chapter.routedVia}`
                          : chapter.profile
                      }`
                    : ''}
                  {chapter.chroniclerVersion !== undefined
                    ? ` · chronicle v${chapter.chroniclerVersion}`
                    : ''}
                </p>
              </header>

              {/* EM-225 — deep-dive dimension notes: the per-lens study the
                  synthesis was woven from (governance / chat / growth). */}
              {chapter.mode === 'deepdive' &&
                chapter.dimensions &&
                Object.keys(chapter.dimensions).length > 0 && (
                  <section
                    data-testid="deepdive-dimensions"
                    className="mb-8 border-l-2 border-lab-acid pl-4 flex flex-col gap-3"
                  >
                    {Object.entries(chapter.dimensions).map(([dim, note]) => (
                      <div key={dim}>
                        <h3 className="font-mono text-[9px] uppercase tracking-widest text-lab-acid mb-1">
                          {dim}
                        </h3>
                        <p className="font-mono text-[11px] text-lab-muted-bright leading-snug whitespace-pre-line">
                          {note}
                        </p>
                      </div>
                    ))}
                  </section>
                )}

              {/* Prose */}
              <div data-testid="chapter-prose" className="font-serif text-[17px] leading-[1.8] text-lab-text">
                {paragraphs.map((para, pi) => (
                  <p
                    key={pi}
                    className={pi === 0 ? 'chronicle-dropcap' : 'mt-[1.2em]'}
                  >
                    {para}
                  </p>
                ))}
              </div>
            </article>
          </div>

          {/* Footer nav */}
          <nav className="shrink-0 flex items-center justify-center gap-3 border-t border-lab-border px-4 py-2 bg-lab-surface">
            <button
              type="button"
              disabled={idx <= 0}
              onClick={() => setSelected(Math.max(0, idx - 1))}
              className="font-mono text-[11px] uppercase px-2 py-0.5 border border-lab-border text-lab-text rounded-sm hover:bg-lab-border hover:text-lab-acid disabled:opacity-40 disabled:cursor-default transition-colors cursor-pointer"
            >
              ◀ Prev
            </button>
            <span className="font-mono text-[11px] text-lab-muted-bright tabular-nums">
              {idx + 1} / {N}
            </span>
            <button
              type="button"
              disabled={idx >= N - 1}
              onClick={() => setSelected(Math.min(N - 1, idx + 1))}
              className="font-mono text-[11px] uppercase px-2 py-0.5 border border-lab-border text-lab-text rounded-sm hover:bg-lab-border hover:text-lab-acid disabled:opacity-40 disabled:cursor-default transition-colors cursor-pointer"
            >
              Next ▶
            </button>
            <span className="font-mono text-[9px] text-lab-muted-bright ml-2 hidden sm:inline">
              ← → to turn pages
            </span>
          </nav>
        </main>

        {/* ---- Chaos Panel (lg: static, mobile: drawer) ---- */}
        <div
          className={[
            'absolute inset-y-0 right-0 z-30 transition-transform duration-200',
            'lg:static lg:flex lg:translate-x-0',
            chaosOpen
              ? 'flex translate-x-0 visible'
              : 'translate-x-full invisible lg:translate-x-0 lg:visible',
          ].join(' ')}
        >
          <ChaosPanel
            history={history}
            fromTick={chapter.fromTick}
            toTick={chapter.toTick}
            payloadChaos={chapter.chaos}
          />
        </div>
      </div>
    </section>
  );
}
