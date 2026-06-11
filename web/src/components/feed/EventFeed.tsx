/**
 * EventFeed — live terminal-style event log.
 * Newest entries on top. Left-bordered with profile_color.
 * agent_action entries show thought on hover; animal lines read inline.
 *
 * Scroll stability (EM-093, contract §9): while the reader is scrolled away
 * from the live edge the rendered list is a FROZEN SNAPSHOT of what was
 * visible the moment they left the top. Arrivals mutate nothing in the DOM —
 * neither the prepend-at-top shift nor the 200-cap trim-at-bottom clamp can
 * move the viewport, because the row set literally does not change. The
 * "X new" pill counts live arrivals against the snapshot; clicking it (or
 * scrolling back to the top) thaws the list and re-pins to newest. This is a
 * stronger form of scrollTop compensation: the compensation needed is zero.
 *
 * Filtering is inclusive: click a category chip to show ONLY that category,
 * click more to stack two or three, click an active chip to drop it. With none
 * focused, everything shows except the default-muted trace chain. The focus set
 * is persisted to localStorage.
 */

import { useRef, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import type { WorldEvent, EventKind } from '../../types';
import { llmDecidedAnimalTurns, isLlmDecidedAction } from '../../lib/animalIdentity';

interface EventFeedProps {
  events: WorldEvent[];
}

// Icon per event kind. EventKind is permissive (open string union); FeedEntry
// falls back to '·' for kinds not listed here, so this stays a partial map.
const KIND_ICON: Partial<Record<EventKind, string>> = {
  turn_start:       '▷',
  agent_action:     '◆',
  agent_speech:     '◉',
  agent_moved:      '→',
  economy:          '¢',
  conflict:         '✖',
  relationship:     '♡',
  agent_died:       '✦',
  agent_spawned:    '✧',
  // W9 survival/extinction surfacing (EM-070/071): starvation warnings read as
  // alarms, extinction as the run's full stop.
  agent_starving:   '⚠',
  world_extinct:    '☠',
  rule_proposed:    '⚖',
  rule_vote:        '☑',
  rule_passed:      '★',
  rule_rejected:    '✘',
  memory:           '◈',
  parse_failure:    '⚠',
  model_reassigned: '⇄',
  // Wave D2 (EM-158) — per-agent cadence tier reassignment receipt.
  cadence_tier_changed: '⇄',
  random_event:     '⊕',
  control:          '⏏',
  // Animal chaos layer (W8) — critter glyphs so the cat/dog read at a glance.
  animal_spawned:   '🐾',
  animal_action:    '🐾',
  animal_died:      '🐾',
  // W11b sim texture (event-log.md v1.3.0): the notice board, the diary, and
  // commitments. commitment_lapsed defaults to ⌛ (expired); the FeedEntry
  // overrides it with the 👻 phantom treatment when reason:"phantom".
  billboard_posted:  '📌',
  // EM-145 — god-voice delivery receipts ("✦ Bram hears the whisper" /
  // "📌 Ada reads the god's note"). Uncategorized ON PURPOSE, like
  // whisper_posted: the god's feedback channel is never filterable away.
  god_voice_heard:   '✦',
  reflection:        '✎',
  commitment_made:   '⚑',
  commitment_lapsed: '⌛',
  usage_alert:       '⚠',
  run_forked:        '⑂',
  // Decision-trace chain (event-log.md §3) — default-muted via the Trace
  // category so these don't flood the live feed.
  perceived:        '◌',
  memory_retrieved: '◈',
  llm_call:         '⌁',
  reasoning:        '∴',
  action_chosen:    '◇',
  action_resolved:  '◆',
};

// Color tint for event kinds without a profile color
const KIND_FALLBACK_COLOR: Partial<Record<EventKind, string>> = {
  agent_died:       '#ff3333',
  agent_spawned:    '#c8ff00',
  rule_passed:      '#c8ff00',
  rule_rejected:    '#ff3333',
  random_event:     '#ff9900',
  model_reassigned: '#c8ff00',
  parse_failure:    '#ff9900',
  control:          '#5a5a72',
};

// W8 — the animal chaos magenta, referenced as the shared --marker-animal token
// (declared in inspector-tokens.css; the SAME magenta the chaos panel + replay
// timeline + 3D critter accent use), so an animal event reads as one color
// everywhere. Animal events ALWAYS use this border regardless of any model
// profile_color, so the critters pop out. It's a dynamic var() reference (the
// established ReplayScrubber/GovernanceHistory pattern) → design-token-guard
// clean. Animal events carry profile:null, so this never hits the hex-only
// alpha-append profile-badge path below.
const ANIMAL_MAGENTA = 'var(--marker-animal)';

/** True when an event belongs to the animal chaos channel (W8). */
function isAnimalEvent(e: WorldEvent): boolean {
  return (
    e.actor_type === 'animal' ||
    e.kind === 'animal_spawned' ||
    e.kind === 'animal_action' ||
    e.kind === 'animal_died'
  );
}

// ── Filter categories ─────────────────────────────────────────────────────────
// Every EventKind maps to exactly one category so nothing is orphaned.
interface FeedCategory {
  key: string;
  label: string;
  icon: string;
  kinds: EventKind[];
}

const CATEGORIES: FeedCategory[] = [
  { key: 'chat',    label: 'Chat',    icon: '◉', kinds: ['agent_speech'] },
  { key: 'actions', label: 'Actions', icon: '◆', kinds: ['agent_action', 'agent_moved'] },
  { key: 'economy', label: 'Economy', icon: '¢', kinds: ['economy'] },
  { key: 'social',  label: 'Social',  icon: '♡', kinds: ['relationship', 'conflict', 'agent_died', 'agent_spawned', 'agent_starving', 'world_extinct'] },
  { key: 'rules',   label: 'Rules',   icon: '⚖', kinds: ['rule_proposed', 'rule_vote', 'rule_passed', 'rule_rejected'] },
  // W11b (EM-091): the notice board gets its own chip — also the contract's
  // suggested feed-filter affordance for billboard traffic.
  { key: 'board',   label: 'Board',   icon: '📌', kinds: ['billboard_posted'] },
  // W11b (EM-079/080): the inner-life channel — diary reflections + spoken
  // commitments (made / kept / 👻 phantom-lapsed).
  { key: 'diary',   label: 'Diary',   icon: '✎', kinds: ['reflection', 'commitment_made', 'commitment_lapsed'] },
  { key: 'system',  label: 'System',  icon: '⊕', kinds: ['turn_start', 'control', 'model_reassigned', 'cadence_tier_changed', 'random_event', 'memory', 'run_forked'] },
  // W8 — the cat & dog chaos channel (magenta). Its OWN category, NOT folded
  // into Trace, so the default-muted trace chain never hides the critters.
  { key: 'animals', label: 'Animals', icon: '🐾', kinds: ['animal_spawned', 'animal_action', 'animal_died'] },
  { key: 'errors',  label: 'Errors',  icon: '⚠', kinds: ['parse_failure', 'usage_alert'] },
  // Decision-trace chain (event-log.md §3). DEFAULT-MUTED: these are the
  // inspector's substrate, not live-feed reading material. Dissect them in the
  // /inspector annex; here they're collapsed so the feed isn't flooded.
  { key: 'trace',   label: 'Trace',   icon: '⌁', kinds: ['perceived', 'memory_retrieved', 'llm_call', 'reasoning', 'action_chosen', 'action_resolved'] },
];

// Categories muted on first load (no saved preference). The trace chain is
// noisy and belongs to the inspector, so it starts collapsed in the live feed.
const DEFAULT_MUTED: string[] = ['trace'];

const KIND_TO_CATEGORY: Partial<Record<EventKind, string>> = {};
CATEGORIES.forEach((c) => c.kinds.forEach((k) => { KIND_TO_CATEGORY[k] = c.key; }));

// Inclusion filter: the set of categories to SHOW. Empty = the default view
// (every category except the noisy DEFAULT_MUTED trace chain). Clicking a chip
// adds it here, so "click a filter" shows FOR that category (and you can stack
// two or three) instead of muting it out.
const STORAGE_KEY = 'em.feed.focusCategories';

function loadFocus(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return new Set(JSON.parse(raw) as string[]);
  } catch { /* ignore */ }
  return new Set();
}

function formatTime(ts: string | undefined): string {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
}

interface FeedEntryProps {
  event: WorldEvent;
  isNew: boolean;
  /**
   * EM-089: true when this animal_action was an LLM decision (it shares a
   * turn_id with an animal llm_call). Reflex actions — and histories where the
   * llm_call fell out of the window — get no marker (graceful degradation).
   */
  llmDecided?: boolean;
}

function FeedEntry({ event, isNew, llmDecided = false }: FeedEntryProps) {
  // W8: animal events ALWAYS take the magenta border + a critter glyph (they have
  // no model profile_color, and we want them to pop out of the human-agent feed).
  const animal = isAnimalEvent(event);
  // W9 (EM-070/071): starvation warnings ALWAYS read in the warn register and
  // extinction in the danger register — even though these events carry a model
  // profile_color, a survival alarm must not blend into the agent's color.
  const starving = event.kind === 'agent_starving';
  const extinct = event.kind === 'world_extinct';
  // W11b (EM-091): a billboard post by the watchers reads in GOD INK — the
  // violet register the god panel already owns — never an agent color.
  // EM-145: delivery receipts (god_voice_heard) share the ink — the whole
  // god↔agent channel reads as one color in the feed.
  const godPost =
    (event.kind === 'billboard_posted' && event.actor_type === 'god') ||
    event.kind === 'god_voice_heard';
  // W11b (EM-080): diary reflections take the muted-italic diary idiom.
  const reflection = event.kind === 'reflection';
  // W11b (EM-079): a phantom-lapsed commitment — claimed in speech, never
  // enacted — gets the 👻 treatment (the headline failure mode).
  const phantom =
    event.kind === 'commitment_lapsed' && event.payload?.reason === 'phantom';
  // W11b (EM-083): usage alerts read in the warn register like other alarms.
  const usageAlert = event.kind === 'usage_alert';
  // Wave D2 (EM-159/166): a background agent's zero-LLM reflex turn — marked
  // subtly so the free-scale machinery is legible without shouting.
  const reflexTurn = event.payload?.reflex === true;
  // W11b (EM-087): a renewal of an already-active law (rule_passed carrying
  // payload.renewed) renders RENEWED, distinct from a fresh PASSED.
  const renewed = event.kind === 'rule_passed' && event.payload?.renewed === true;
  const color = animal
    ? ANIMAL_MAGENTA
    : godPost
      ? 'var(--lab-god)'
      : starving || usageAlert
        ? 'var(--lab-warn)'
        : extinct
          ? 'var(--lab-danger)'
          : event.profile_color ?? KIND_FALLBACK_COLOR[event.kind] ?? 'var(--marker-trace)';
  // The hover profile badge alpha-appends hex digits, so it only renders with a
  // hex source (the agent's data-driven profile color / a kind fallback) — the
  // var()-register warning kinds keep the agent's own color on the badge.
  const badgeColor = event.profile_color ?? KIND_FALLBACK_COLOR[event.kind] ?? null;
  const icon = animal
    ? '🐾'
    : phantom
      ? '👻'
      : renewed
        ? '↻'
        : KIND_ICON[event.kind] ?? '·';
  // Chat-first (contract §9 priority clarification): dialogue is the
  // centerpiece — speech rows read slightly larger with inline speaker/model
  // attribution, so the conversation scans without hovering.
  const speech = event.kind === 'agent_speech';
  // Surface the animal's in-character thought (or any agent_action thought) on hover.
  const tip = animal
    ? (typeof event.payload?.animal_thought === 'string' ? event.payload.animal_thought : event.thought)
    : event.kind === 'agent_action'
      ? event.thought
      : undefined;
  const hasTip = Boolean(tip);

  return (
    <div
      className={`group relative flex items-start gap-2 py-1.5 px-2 border-b border-lab-border/40
                  hover:bg-lab-chrome/50 transition-colors duration-100
                  ${isNew ? 'feed-entry-new' : ''}`}
      style={{ borderLeft: `3px solid ${color}` }}
    >
      {/* Icon */}
      <span
        className={`flex-none font-mono text-xs w-4 text-center mt-px shrink-0 ${phantom ? 'phantom-drift' : ''}`}
        style={{ color }}
        aria-hidden="true"
      >
        {icon}
      </span>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <span
          className={`font-mono leading-relaxed break-words ${speech ? 'text-[13px]' : 'text-xs'} ${
            starving || usageAlert
              ? 'text-lab-warn font-semibold'
              : extinct
                ? 'text-lab-danger font-bold uppercase tracking-wide'
                : reflection || phantom
                  ? 'text-lab-muted italic'
                  : godPost
                    ? 'font-semibold'
                    : 'text-lab-text'
          }`}
          style={godPost ? { color: 'var(--lab-god-bright)' } : undefined}
        >
          {event.text ?? `[${event.kind}]`}
        </span>

        {/* Inline model attribution on dialogue (hex-only alpha-append path,
            same idiom as the hover profile badge below). */}
        {speech && event.profile && badgeColor && badgeColor.startsWith('#') && (
          <span
            className="ml-1.5 font-mono text-[9px] px-1 py-px border rounded-sm align-middle whitespace-nowrap"
            style={{ color: badgeColor, borderColor: badgeColor + '50' }}
            title={`spoken by a ${event.profile} villager`}
          >
            {event.profile}
          </span>
        )}

        {/* W11b (EM-091): the watchers' replies carry the GOD ink chip. */}
        {godPost && (
          <span
            className="ml-1.5 font-mono text-[9px] font-bold px-1 py-px border rounded-sm align-middle whitespace-nowrap uppercase tracking-wider"
            style={{ color: 'var(--lab-god-bright)', borderColor: 'var(--lab-god)' }}
            title="Posted by the watchers (god mode) — agents will see it on the notice board"
          >
            ✦ god
          </span>
        )}

        {/* W11b (EM-079): the phantom-commitment chip — promised aloud, never
            enacted. A 👻 haunts the line so the failure mode is legible. */}
        {phantom && (
          <span
            className="ml-1.5 font-mono text-[9px] px-1 py-px border border-lab-border-bright text-lab-muted rounded-sm align-middle whitespace-nowrap uppercase tracking-wider"
            title="Phantom commitment — claimed in speech, but no matching tool call ever happened. All talk."
          >
            👻 phantom
          </span>
        )}

        {/* W11b (EM-087): renewal of an active law ≠ a fresh enactment. */}
        {renewed && (
          <span
            className="ml-1.5 font-mono text-[9px] font-bold px-1 py-px border rounded-sm align-middle whitespace-nowrap uppercase tracking-wider"
            style={{ color: 'var(--marker-governance)', borderColor: 'var(--marker-governance)' }}
            title="Renewed — re-proposing an identical active law extends it; it never stacks."
          >
            ↻ renewed
          </span>
        )}

        {/* Wave D2 (EM-159/166): zero-LLM background reflex turn — a subtle
            dim chip, the human-agent sibling of the animals' reflex idiom. */}
        {reflexTurn && (
          <span
            className="ml-1.5 font-mono text-[9px] px-1 py-px border border-lab-border text-lab-dim rounded-sm align-middle whitespace-nowrap uppercase tracking-wider"
            title="Reflex turn — a background-tier agent resolved this deterministically with zero LLM calls"
          >
            ⟳ reflex
          </span>
        )}

        {/* EM-089: LLM-decided animal action (vs a zero-cost reflex). */}
        {llmDecided && (
          <span
            className="ml-1.5 font-mono text-[10px] cursor-default"
            title="LLM decision — the animal's model chose this action (reflex actions carry no marker)"
            aria-label="LLM decision"
          >
            🧠
          </span>
        )}

        {/* An animal's in-character line reads INLINE (the chaos dialogue is the
            point) rather than being buried in a hover tooltip. */}
        {animal && hasTip && (
          <span className="block font-mono text-xs text-lab-muted italic leading-relaxed break-words mt-0.5">
            “{tip}”
          </span>
        )}

        {/* Agent reasoning stays on hover so the live feed isn't flooded. */}
        {!animal && hasTip && (
          <div className="lab-tooltip bottom-full left-0 mb-1 w-56">
            <span className="text-lab-muted">thought: </span>
            <span className="text-lab-text">{tip}</span>
          </div>
        )}
      </div>

      {/* Tick + time */}
      <div className="flex-none flex flex-col items-end gap-0.5 shrink-0">
        <span className="font-mono text-[10px] text-lab-muted tabular-nums">T{event.tick}</span>
        {event.ts && (
          <span className="font-mono text-[9px] text-lab-dim">{formatTime(event.ts)}</span>
        )}
      </div>

      {/* Profile badge (hex-only path: badgeColor is alpha-appended) */}
      {event.profile && badgeColor && badgeColor.startsWith('#') && (
        <span
          className="absolute top-1 right-1 font-mono text-[8px] px-1 py-px rounded-sm hidden group-hover:block"
          style={{
            backgroundColor: badgeColor + '30',
            color: badgeColor,
            border: `1px solid ${badgeColor}40`,
          }}
        >
          {event.profile}
        </span>
      )}
    </div>
  );
}

// How close to the top counts as "pinned to newest" (px).
const TOP_THRESHOLD = 8;

export function EventFeed({ events }: EventFeedProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const highlightLenRef = useRef(0);
  const newEventIdsRef = useRef<Set<number>>(new Set());

  // EM-093: the frozen snapshot. null = pinned to newest (live, list follows
  // arrivals); an array = the exact row set rendered while the reader is
  // scrolled away. Arrivals never touch the frozen DOM, so the viewport can't
  // move — not on prepend, and not on the upstream 200-cap trim.
  const [frozen, setFrozen] = useState<WorldEvent[] | null>(null);
  const [focus, setFocus] = useState<Set<string>>(loadFocus);

  // Persist focused categories.
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...focus])); } catch { /* ignore */ }
  }, [focus]);

  // EM-089: turn_ids of animal LLM decisions, scanned over the FULL feed pool
  // (the llm_call rows themselves are trace-category and default-muted, but
  // they still inform the 🧠 marker on the visible animal_action lines).
  const llmAnimalTurns = useMemo(() => llmDecidedAnimalTurns(events), [events]);

  // Inclusion filter: with categories focused, show ONLY those; with none
  // focused, show everything except the default-muted trace chain.
  const visibleEvents = useMemo(
    () => (focus.size === 0
      ? events.filter((e) => !DEFAULT_MUTED.includes(KIND_TO_CATEGORY[e.kind] ?? ''))
      : events.filter((e) => focus.has(KIND_TO_CATEGORY[e.kind] ?? ''))),
    [events, focus],
  );

  // What actually renders: the live filtered list while pinned, the snapshot
  // while scrolled away.
  const displayEvents = frozen ?? visibleEvents;
  const scrolledAway = frozen !== null;

  // The "X new" pill: live arrivals not present in the snapshot. Deduped by
  // seq (NOT a max-seq comparison — client-synthesized events carry negative
  // seqs, so set membership is the only safe identity).
  const unseen = useMemo(() => {
    if (!frozen) return 0;
    const held = new Set(frozen.map((e) => e.seq));
    let n = 0;
    for (const e of visibleEvents) if (!held.has(e.seq)) n++;
    return n;
  }, [frozen, visibleEvents]);

  // Highlight freshly-arrived entries briefly. Tracked with its own length ref so
  // it stays independent of the freeze bookkeeping.
  useEffect(() => {
    if (visibleEvents.length > highlightLenRef.current) {
      const added = visibleEvents.length - highlightLenRef.current;
      newEventIdsRef.current = new Set(visibleEvents.slice(0, added).map((e) => e.seq));
      highlightLenRef.current = visibleEvents.length;
      const t = setTimeout(() => { newEventIdsRef.current = new Set(); }, 300);
      return () => clearTimeout(t);
    }
    highlightLenRef.current = visibleEvents.length;
  }, [visibleEvents]);

  // While pinned, newest entries prepend at the top — hold the viewport on
  // the live edge (scrollTop 0). While frozen this is a no-op by design.
  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && frozen === null) el.scrollTop = 0;
  }, [visibleEvents, frozen]);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const atTop = el.scrollTop <= TOP_THRESHOLD;
    if (atTop) {
      // Back at the live edge: thaw and re-pin.
      setFrozen((f) => (f === null ? f : null));
    } else {
      // Leaving the live edge: freeze the row set exactly as rendered now.
      setFrozen((f) => f ?? visibleEvents);
    }
  };

  const jumpToNewest = () => {
    const el = listRef.current;
    if (!el) return;
    setFrozen(null);
    el.scrollTo({ top: 0, behavior: 'smooth' });
  };

  // Click a chip to focus that category (show only it). Click more to stack two
  // or three; click an active one to drop it. Empty focus → default view.
  const toggleFocus = (key: string) => {
    setFocus((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
    // A filter change re-pins to newest so the list doesn't jump unpredictably.
    setFrozen(null);
  };

  const clearFocus = () => {
    setFocus(new Set());
    setFrozen(null);
  };

  const hiddenCount = events.length - visibleEvents.length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="lab-header flex items-center justify-between">
        {/* EM-082 a11y: a real heading so the feed lands in the page outline. */}
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">EVENT STREAM</h2>
        <div className="flex items-center gap-2">
          <span className="text-lab-muted text-[10px]">
            {events.length === 0
              ? 'NO EVENTS'
              : hiddenCount > 0
                ? `${visibleEvents.length}/${events.length}`
                : `${events.length} events`}
          </span>
          <span
            className={`font-mono text-[10px] px-1.5 py-0.5 border
                        ${scrolledAway
                          ? 'border-lab-border text-lab-muted'
                          : 'border-lab-acid text-lab-acid'}`}
            title={scrolledAway ? 'Scrolled — newest entries are paused above' : 'Pinned to newest'}
          >
            {scrolledAway ? 'PAUSED' : 'LIVE'}
          </span>
        </div>
      </div>

      {/* Filter bar — click a chip to show ONLY that category; click more to stack
          two or three; click an active one to drop it. Empty = default view. */}
      <div className="flex flex-wrap items-center gap-1 px-2 py-1 border-b border-lab-border/40 bg-lab-chrome/20">
        {CATEGORIES.map((cat) => {
          // Active = currently shown. With no focus, that's everything except the
          // default-muted trace chain; with a focus set, only the focused chips.
          const isActive = focus.size === 0
            ? !DEFAULT_MUTED.includes(cat.key)
            : focus.has(cat.key);
          return (
            <button
              key={cat.key}
              onClick={() => toggleFocus(cat.key)}
              title={isActive ? `Showing ${cat.label} — click to hide` : `Click to show only ${cat.label}`}
              className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border cursor-pointer transition-colors duration-100
                          ${isActive
                            ? 'border-lab-acid text-lab-acid'
                            : 'border-lab-border/40 text-lab-dim opacity-50 hover:border-lab-acid hover:text-lab-acid hover:opacity-100'}`}
            >
              <span aria-hidden="true">{cat.icon}</span> {cat.label}
            </button>
          );
        })}
        {focus.size > 0 && (
          <button
            onClick={clearFocus}
            title="Clear filters (show all)"
            className="font-mono text-[10px] px-1.5 py-0.5 rounded-sm border border-lab-acid/60
                       text-lab-acid hover:bg-lab-acid/15 cursor-pointer transition-colors duration-100"
          >
            ✕ clear
          </button>
        )}
      </div>

      {/* Feed list */}
      <div className="relative flex-1 min-h-0">
        <div
          ref={listRef}
          onScroll={handleScroll}
          className="absolute inset-0 overflow-y-auto"
        >
          {displayEvents.length === 0 ? (
            <div className="flex items-center justify-center h-16 font-mono text-xs text-lab-dim text-center px-4">
              {events.length === 0
                ? 'WAITING FOR EVENTS…'
                : 'No events in the selected filters yet — click ✕ clear to show all'}
            </div>
          ) : (
            displayEvents.map((event) => (
              <FeedEntry
                key={event.seq}
                event={event}
                isNew={newEventIdsRef.current.has(event.seq)}
                llmDecided={isLlmDecidedAction(event, llmAnimalTurns)}
              />
            ))
          )}
        </div>

        {/* Jump-to-newest pill — only while scrolled away from the top */}
        {scrolledAway && (
          <button
            onClick={jumpToNewest}
            title="Jump back to the newest events (re-pins the feed)"
            className="absolute top-2 left-1/2 -translate-x-1/2 z-10 cursor-pointer
                       font-mono text-[10px] px-2 py-1 rounded-full
                       bg-lab-chrome border border-lab-acid text-lab-acid
                       shadow-lg hover:bg-lab-acid/20 transition-colors duration-150"
          >
            ↑ {unseen > 0 ? `${unseen} new` : 'newest'}
          </button>
        )}
      </div>
    </div>
  );
}
