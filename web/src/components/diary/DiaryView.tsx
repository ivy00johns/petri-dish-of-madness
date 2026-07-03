/**
 * DiaryView (EM-215) — The Diary: a dedicated, full-screen reading room for the
 * agents' inner life. The individual cousin to the town Chronicle.
 *
 * The live feed surfaces reflections only as ONE category among many
 * (EventFeed `diary` chip); here they get their own room, re-organised by
 * AUTHOR. Each agent owns a column — avatar + name + mood + model chip across
 * the top, then their `reflection` lines stacked chronologically (oldest →
 * newest, the natural reading order of a kept diary).
 *
 * Like /chronicle and /inspector this route renders WITHOUT LiveLayout, so the
 * CozyWorld <Canvas> unmounts and the WebGL context is released (App.tsx Routes).
 *
 * Backend reflection-cadence tuning (EM-080) is out of scope for this view; if
 * the stream reads thin, that's a backend follow-up, not a DiaryView bug.
 */
import { useMemo, useState } from 'react';

import type { Agent, WorldEvent, WorldState } from '../../types';
import { groupReflectionsByAgent, type DiaryEntry } from './diary';

interface DiaryViewProps {
  world: WorldState | null;
  history: WorldEvent[];
}

/** Two-letter monogram avatar — the EM-096 RosterStrip idiom, token-tinted. */
function Monogram({ label, color }: { label: string; color: string }) {
  return (
    <span
      className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 font-mono text-[11px] font-bold"
      style={{
        backgroundColor: `color-mix(in srgb, ${color} 20%, transparent)`,
        border: `1.5px solid ${color}`,
        color,
      }}
      aria-hidden="true"
    >
      {label.slice(0, 2).toUpperCase()}
    </span>
  );
}

function DiaryEntryRow({ entry, color }: { entry: DiaryEntry; color: string }) {
  return (
    <li
      data-testid="diary-entry"
      className="border-l-2 pl-3 py-1.5"
      style={{ borderColor: `color-mix(in srgb, ${color} 45%, transparent)` }}
    >
      <div className="flex items-baseline gap-2 mb-0.5">
        <span className="font-mono text-[9px] text-lab-muted tabular-nums shrink-0">
          T{entry.tick}
        </span>
        {entry.profile && (
          <span className="font-mono text-[8px] text-lab-dim truncate" title={`authored by ${entry.profile}`}>
            {entry.profile}
          </span>
        )}
      </div>
      <p className="m-0 font-serif text-[13px] italic leading-relaxed text-lab-text break-words">
        {entry.text}
      </p>
    </li>
  );
}

function AgentColumn({ actorId, entries, agent }: {
  actorId: string;
  entries: DiaryEntry[];
  agent: Agent | undefined;
}) {
  // Identity: prefer the live snapshot; fall back to the actor id + the model
  // last seen authoring the diary (graceful degradation for departed agents).
  const name = agent?.name ?? actorId;
  const mood = agent?.mood ?? null;
  const color =
    agent?.profile_color ??
    entries.find((e) => e.profile_color)?.profile_color ??
    'var(--inspector-node-neutral)';

  return (
    <section
      data-testid={`diary-agent-${actorId}`}
      className="lab-panel shrink-0 w-80 flex flex-col overflow-hidden self-stretch"
      aria-label={`${name}'s diary`}
    >
      {/* Identity header */}
      <header className="shrink-0 flex items-center gap-2 px-3 py-2 border-b border-lab-border bg-lab-chrome/40">
        <Monogram label={name} color={color} />
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[12px] font-semibold text-lab-text truncate" title={name}>
            {name}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            {mood && (
              <span className="font-mono text-[10px] text-lab-muted truncate" title={`mood: ${mood}`}>
                {mood}
              </span>
            )}
            <span className="font-mono text-[9px] text-lab-dim tabular-nums shrink-0">
              {entries.length} {entries.length === 1 ? 'entry' : 'entries'}
            </span>
          </div>
        </div>
      </header>

      {/* The diary itself — chronological, oldest at the top. */}
      <ol className="flex-1 overflow-y-auto px-2 py-2 flex flex-col gap-2 m-0 list-none">
        {entries.map((entry) => (
          <DiaryEntryRow key={entry.seq} entry={entry} color={color} />
        ))}
      </ol>
    </section>
  );
}

export function DiaryView({ world, history }: DiaryViewProps) {
  const groups = useMemo(() => groupReflectionsByAgent(history), [history]);
  const [selectedActor, setSelectedActor] = useState<string>(''); // '' = all

  const agentsById = useMemo(() => {
    const m = new Map<string, Agent>();
    for (const a of world?.agents ?? []) m.set(a.id, a);
    return m;
  }, [world]);

  // Resolve a label for the selector: live name when known, else the actor id.
  const selectorOptions = useMemo(
    () =>
      groups.map((g) => ({
        actorId: g.actorId,
        label: agentsById.get(g.actorId)?.name ?? g.actorId,
        count: g.entries.length,
      })),
    [groups, agentsById],
  );

  // EM-294: a selected diarist can later vanish from grouped history (an
  // archived-run switch, or a history replace that no longer carries their
  // reflections). A stale id then filters to zero groups → a silently blank
  // reading room. Fall back deterministically to "all agents" when the selection
  // is no longer present, and drive the <select> off the SAME resolved value so
  // it never shows a phantom option.
  const effectiveActor = groups.some((g) => g.actorId === selectedActor) ? selectedActor : '';
  const visibleGroups =
    effectiveActor === '' ? groups : groups.filter((g) => g.actorId === effectiveActor);

  const totalEntries = groups.reduce((n, g) => n + g.entries.length, 0);

  // ---- Toolbar (always present, like the Chronicle's) ----
  const toolbar = (
    <div className="shrink-0 flex flex-wrap items-center gap-2 border-b border-lab-border px-4 py-2 bg-lab-surface">
      <h2 className="font-mono text-xs uppercase tracking-widest text-lab-acid mr-auto">
        <span aria-hidden="true">✎</span> The Diary
      </h2>
      <span className="font-mono text-[10px] text-lab-muted tabular-nums">
        {groups.length} {groups.length === 1 ? 'diarist' : 'diarists'} · {totalEntries}{' '}
        {totalEntries === 1 ? 'entry' : 'entries'}
      </span>
      <label className="font-mono text-[10px] uppercase text-lab-muted-bright flex items-center gap-1">
        Diary
        <select
          value={effectiveActor}
          onChange={(e) => setSelectedActor(e.target.value)}
          aria-label="Diary — filter to one agent"
          className="font-mono text-[10px] bg-lab-chrome border border-lab-border text-lab-text rounded-sm px-1 py-0.5"
        >
          <option value="">All agents</option>
          {selectorOptions.map((o) => (
            <option key={o.actorId} value={o.actorId}>
              {o.label} ({o.count})
            </option>
          ))}
        </select>
      </label>
    </div>
  );

  // ---- Empty state ----
  if (groups.length === 0) {
    return (
      <section className="flex-1 min-h-0 flex flex-col bg-lab-bg" aria-label="The Diary">
        {toolbar}
        <div className="flex-1 min-h-0 overflow-y-auto flex items-center justify-center p-8">
          <div className="max-w-md text-center">
            <div className="text-3xl mb-3" aria-hidden="true">✎</div>
            <p className="font-mono text-lab-muted-bright text-sm leading-relaxed">
              No diary entries yet — the villagers keep their inner life to themselves
              for now. As they live, their reflections collect here, one diary per soul.
            </p>
          </div>
        </div>
      </section>
    );
  }

  // ---- Columns ----
  return (
    <section className="flex-1 min-h-0 flex flex-col bg-lab-bg" aria-label="The Diary">
      {toolbar}
      <div className="flex-1 min-h-0 flex items-stretch gap-3 overflow-x-auto overflow-y-hidden px-4 py-4">
        {visibleGroups.map((g) => (
          <AgentColumn
            key={g.actorId}
            actorId={g.actorId}
            entries={g.entries}
            agent={agentsById.get(g.actorId)}
          />
        ))}
      </div>
    </section>
  );
}
