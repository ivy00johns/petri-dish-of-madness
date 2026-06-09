/**
 * AnimalChaosFeed (EM-065) — the magenta chaos channel.
 *
 * The cat and the dog are a DISTINCT actor class (actor_type:"animal",
 * world-model.md §W8). They act impulsively and IN-CHARACTER, not to optimize —
 * and occasionally the under-constrained LLM has one of them commit arson, steal
 * a snack, or knock the garden over. Those moments are the funniest thing in the
 * sim, and they get lost in the main feed. This panel pulls them OUT into a
 * dedicated magenta stream.
 *
 * Each entry shows the three beats of the joke, one click away:
 *   1. the animal_thought   ("That tall wooden thing offends me.")
 *   2. the action            (knock_over / arson / chase / nap …)
 *   3. the consequence       (the feed text — "the clock tower is now kindling")
 *
 * A `is_chaotic` entry (a crime/structure-targeting / low-prior escalation) is
 * flagged loudly — that's the headline chaos. The whole panel is MAGENTA, the
 * SAME --marker-animal register as the replay-timeline animal markers + the
 * main-feed critter border, so "animal" reads as one color everywhere.
 *
 * Data: PURE projection of `props.events` — filter to actor_type:"animal" (or the
 * animal_* kinds) and re-project AT `props.currentTick` so it follows the shared
 * scrubber like every other panel. No backend required; mock-safe.
 *
 * Styling: token-only (lab-* classes + the --chaos-* / --marker-animal tokens in
 * inspector-tokens.css). The only inline styles are dynamic `var(--token)`
 * references (the established ReplayScrubber/GovernanceHistory pattern) — never a
 * hardcoded design literal. No `any`.
 */

import { useMemo } from 'react';
import type { PanelProps } from './types';
import type { WorldEvent } from '../types';
import './inspector-tokens.css';

// The magenta chaos register, pulled from the shared marker token so it stays in
// lockstep with the replay timeline + main-feed critter border. Dynamic var() in
// inline style is design-token-guard clean.
const CHAOS_ACCENT = 'var(--marker-animal)';
const CHAOS_CHAOTIC = 'var(--chaos-chaotic)';

// A short icon per animal action (open-ended — an unknown action just shows its
// raw key with a paw fallback, never crashes).
const ACTION_ICON: Record<string, string> = {
  wander: '🐾',
  nap: '😴',
  knock_over: '🪴',
  scratch: '🐈',
  mark_territory: '💧',
  pounce: '🐅',
  chase: '🦮',
  idle: '·',
  steal_food: '🍖',
  arson: '🔥',
};

/** True when an event belongs to the animal channel (the chaos-feed filter). */
function isAnimalEvent(e: WorldEvent): boolean {
  return (
    e.actor_type === 'animal' ||
    e.kind === 'animal_action' ||
    e.kind === 'animal_spawned' ||
    e.kind === 'animal_died'
  );
}

/** A species glyph for the actor, read from the event payload when present. */
function speciesIcon(e: WorldEvent): string {
  const species = typeof e.payload?.species === 'string' ? e.payload.species : null;
  if (species === 'cat') return '🐱';
  if (species === 'dog') return '🐶';
  return '🐾';
}

/** The animal's chosen action key (payload.action), or the kind as a fallback. */
function actionOf(e: WorldEvent): string {
  const action = typeof e.payload?.action === 'string' ? e.payload.action : null;
  if (action) return action;
  if (e.kind === 'animal_spawned') return 'spawned';
  if (e.kind === 'animal_died') return 'died';
  return e.kind.replace(/^animal_/, '');
}

/** The in-character thought, from payload.animal_thought (the joke's setup). */
function thoughtOf(e: WorldEvent): string | null {
  const t = e.payload?.animal_thought ?? e.thought;
  return typeof t === 'string' && t.length > 0 ? t : null;
}

interface ChaosEntryProps {
  event: WorldEvent;
}

function ChaosEntry({ event }: ChaosEntryProps) {
  const action = actionOf(event);
  const icon = ACTION_ICON[action] ?? '🐾';
  const thought = thoughtOf(event);
  const chaotic = event.is_chaotic === true;

  return (
    <li
      className="flex flex-col gap-1 px-3 py-2 border-b border-lab-border/40"
      style={{
        borderLeft: `3px solid ${chaotic ? CHAOS_CHAOTIC : CHAOS_ACCENT}`,
        background: chaotic ? 'var(--chaos-surface)' : undefined,
      }}
    >
      {/* Top row: species + action + chaos badge + tick */}
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs shrink-0" aria-hidden="true">
          {speciesIcon(event)}
        </span>
        <span
          className="font-mono text-[11px] font-bold uppercase tracking-wide truncate"
          style={{ color: CHAOS_ACCENT }}
          title={action}
        >
          <span aria-hidden="true">{icon}</span> {action.replace(/_/g, ' ')}
        </span>
        {chaotic && (
          <span
            className="font-mono text-[9px] font-bold uppercase px-1.5 py-px rounded-sm shrink-0"
            style={{ color: CHAOS_CHAOTIC, border: `1px solid ${CHAOS_CHAOTIC}` }}
            title="A crime / structure-targeting / low-prior escalation — the headline chaos."
          >
            chaos
          </span>
        )}
        <span className="ml-auto font-mono text-[10px] text-lab-muted tabular-nums shrink-0">
          T{event.tick}
        </span>
      </div>

      {/* Beat 1 — the in-character thought (the joke's setup). */}
      {thought && (
        <p className="font-mono text-[11px] italic text-lab-text leading-relaxed">
          “{thought}”
        </p>
      )}

      {/* Beat 3 — the consequence (the feed line; the funny payoff). */}
      <p className="font-mono text-[10px] text-lab-muted leading-relaxed break-words">
        {event.text ?? `[${event.kind}]`}
      </p>
    </li>
  );
}

export default function AnimalChaosFeed(props: PanelProps) {
  const { events, currentTick } = props;

  // Filter to the animal channel, re-project AT the shared scrub tick (follows
  // the scrubber like every panel), newest-first. The events ref is already
  // newest-first; sorting by seq desc keeps it stable across data sources.
  const chaos = useMemo(
    () =>
      events
        .filter((e) => isAnimalEvent(e) && e.tick <= currentTick)
        .sort((a, b) => b.seq - a.seq),
    [events, currentTick],
  );

  const chaoticCount = useMemo(() => chaos.filter((e) => e.is_chaotic === true).length, [chaos]);

  return (
    <section
      className="lab-panel flex flex-col h-full min-h-[9rem]"
      aria-label="Animal Chaos Feed (EM-065)"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <span style={{ color: CHAOS_ACCENT }}>Animal Chaos Feed</span>
        <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
          EM-065
        </span>
      </div>

      {/* Summary strip */}
      <div className="flex items-center gap-3 px-3 py-1.5 border-b border-lab-border/40 bg-lab-chrome/20">
        <span className="font-mono text-[10px] text-lab-muted">
          {chaos.length} animal event{chaos.length === 1 ? '' : 's'}
        </span>
        {chaoticCount > 0 && (
          <span
            className="font-mono text-[10px] font-bold uppercase tracking-wide"
            style={{ color: CHAOS_CHAOTIC }}
          >
            {chaoticCount} chaotic
          </span>
        )}
      </div>

      {/* The magenta stream */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {chaos.length === 0 ? (
          <div className="flex items-center justify-center h-24 px-4 text-center">
            <span className="font-mono text-[10px] text-lab-dim leading-relaxed">
              No critter mischief yet — the cat and dog haven’t acted by this tick.
            </span>
          </div>
        ) : (
          <ul className="flex flex-col">
            {chaos.map((e) => (
              <ChaosEntry key={e.seq} event={e} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
