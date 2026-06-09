/**
 * EventFeed — live terminal-style event log.
 * Newest entries on top. Left-bordered with profile_color.
 * agent_action entries show thought on hover.
 *
 * Filtering: events are bucketed into categories; each can be muted via the
 * filter bar (persisted to localStorage). Muting "Errors" hides the noisy
 * parse_failure / idle-fallback lines.
 */

import { useRef, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import type { WorldEvent, EventKind } from '../../types';

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
  rule_proposed:    '⚖',
  rule_vote:        '☑',
  rule_passed:      '★',
  rule_rejected:    '✘',
  memory:           '◈',
  parse_failure:    '⚠',
  model_reassigned: '⇄',
  random_event:     '⊕',
  control:          '⏏',
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
  { key: 'social',  label: 'Social',  icon: '♡', kinds: ['relationship', 'conflict', 'agent_died', 'agent_spawned'] },
  { key: 'rules',   label: 'Rules',   icon: '⚖', kinds: ['rule_proposed', 'rule_vote', 'rule_passed', 'rule_rejected'] },
  { key: 'system',  label: 'System',  icon: '⊕', kinds: ['turn_start', 'control', 'model_reassigned', 'random_event', 'memory'] },
  { key: 'errors',  label: 'Errors',  icon: '⚠', kinds: ['parse_failure'] },
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

const STORAGE_KEY = 'em.feed.mutedCategories';

function loadMuted(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    // Only honor DEFAULT_MUTED when the user has no saved preference yet, so we
    // never re-mute a category a returning user deliberately un-muted.
    if (raw) return new Set(JSON.parse(raw) as string[]);
  } catch { /* ignore */ }
  return new Set(DEFAULT_MUTED);
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
}

function FeedEntry({ event, isNew }: FeedEntryProps) {
  const color = event.profile_color ?? KIND_FALLBACK_COLOR[event.kind] ?? '#3a3a50';
  const icon = KIND_ICON[event.kind] ?? '·';
  const hasTip = event.kind === 'agent_action' && event.thought;

  return (
    <div
      className={`group relative flex items-start gap-2 py-1.5 px-2 border-b border-lab-border/40
                  hover:bg-lab-chrome/50 transition-colors duration-100
                  ${isNew ? 'feed-entry-new' : ''}`}
      style={{ borderLeft: `3px solid ${color}` }}
    >
      {/* Icon */}
      <span
        className="flex-none font-mono text-xs w-4 text-center mt-px shrink-0"
        style={{ color }}
        aria-hidden="true"
      >
        {icon}
      </span>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <span className="font-mono text-xs text-lab-text leading-relaxed break-words">
          {event.text ?? `[${event.kind}]`}
        </span>

        {/* Thought tooltip */}
        {hasTip && (
          <div className="lab-tooltip bottom-full left-0 mb-1 w-56">
            <span className="text-lab-muted">thought: </span>
            <span className="text-lab-text">{event.thought}</span>
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

      {/* Profile badge */}
      {event.profile && (
        <span
          className="absolute top-1 right-1 font-mono text-[8px] px-1 py-px rounded-sm hidden group-hover:block"
          style={{ backgroundColor: color + '30', color, border: `1px solid ${color}40` }}
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
  const prevLengthRef = useRef(0);
  const prevScrollHeightRef = useRef(0);
  const highlightLenRef = useRef(0);
  // Pinned to the top (newest) vs. scrolled down reading history. A ref so the
  // layout effect reads the latest value without re-subscribing.
  const pinnedRef = useRef(true);
  const newEventIdsRef = useRef<Set<number>>(new Set());

  const [scrolledAway, setScrolledAway] = useState(false);
  const [unseen, setUnseen] = useState(0);
  const [muted, setMuted] = useState<Set<string>>(loadMuted);

  // Persist muted categories.
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...muted])); } catch { /* ignore */ }
  }, [muted]);

  // Apply category filter. Unmapped kinds (none, by construction) stay visible.
  const visibleEvents = useMemo(
    () => (muted.size === 0
      ? events
      : events.filter((e) => !muted.has(KIND_TO_CATEGORY[e.kind] ?? ''))),
    [events, muted],
  );

  // Highlight freshly-arrived entries briefly. Tracked with its own length ref so
  // it stays independent of the scroll effect's bookkeeping.
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

  // Newest entries are prepended at the top. Preserve the reader's position:
  //  • Pinned to top → stay pinned to the newest entry.
  //  • Scrolled down → offset scrollTop by the height of the inserted content
  //    so the entries being read stay put, and count them as "unseen".
  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    const added = visibleEvents.length - prevLengthRef.current;

    if (pinnedRef.current) {
      el.scrollTop = 0;
    } else if (added > 0) {
      const delta = el.scrollHeight - prevScrollHeightRef.current;
      if (delta > 0) el.scrollTop += delta;
      setUnseen((c) => c + added);
    }

    prevScrollHeightRef.current = el.scrollHeight;
    prevLengthRef.current = visibleEvents.length;
  }, [visibleEvents]);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const atTop = el.scrollTop <= TOP_THRESHOLD;
    pinnedRef.current = atTop;
    setScrolledAway(!atTop);
    if (atTop) setUnseen(0);
  };

  const jumpToNewest = () => {
    const el = listRef.current;
    if (!el) return;
    pinnedRef.current = true;
    setScrolledAway(false);
    setUnseen(0);
    el.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const toggleCategory = (key: string) => {
    setMuted((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
    // A filter change re-pins to newest so the list doesn't jump unpredictably.
    pinnedRef.current = true;
    setScrolledAway(false);
    setUnseen(0);
  };

  // Shift-click a chip to "solo" it: mute everything else.
  const soloCategory = (key: string) => {
    setMuted(new Set(CATEGORIES.map((c) => c.key).filter((k) => k !== key)));
    pinnedRef.current = true;
    setScrolledAway(false);
    setUnseen(0);
  };

  const hiddenCount = events.length - visibleEvents.length;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="lab-header flex items-center justify-between">
        <span>EVENT STREAM</span>
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

      {/* Filter bar — click to mute/unmute a category, shift-click to focus one */}
      <div className="flex flex-wrap items-center gap-1 px-2 py-1 border-b border-lab-border/40 bg-lab-chrome/20">
        {CATEGORIES.map((cat) => {
          const isMuted = muted.has(cat.key);
          return (
            <button
              key={cat.key}
              onClick={(e) => (e.shiftKey ? soloCategory(cat.key) : toggleCategory(cat.key))}
              title={isMuted ? `Show ${cat.label} (shift-click: focus)` : `Mute ${cat.label} (shift-click: focus)`}
              className={`font-mono text-[10px] px-1.5 py-0.5 rounded-sm border cursor-pointer transition-colors duration-100
                          ${isMuted
                            ? 'border-lab-border/40 text-lab-dim opacity-50 line-through'
                            : 'border-lab-border text-lab-muted hover:border-lab-acid hover:text-lab-acid'}`}
            >
              <span aria-hidden="true">{cat.icon}</span> {cat.label}
            </button>
          );
        })}
        {muted.size > 0 && (
          <button
            onClick={() => { setMuted(new Set()); pinnedRef.current = true; setScrolledAway(false); setUnseen(0); }}
            title="Show all categories"
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
          {visibleEvents.length === 0 ? (
            <div className="flex items-center justify-center h-16 font-mono text-xs text-lab-dim text-center px-4">
              {events.length === 0
                ? 'WAITING FOR EVENTS…'
                : 'ALL CATEGORIES MUTED — click a filter to show events'}
            </div>
          ) : (
            visibleEvents.map((event) => (
              <FeedEntry
                key={event.seq}
                event={event}
                isNew={newEventIdsRef.current.has(event.seq)}
              />
            ))
          )}
        </div>

        {/* Jump-to-newest pill — only while scrolled away from the top */}
        {scrolledAway && (
          <button
            onClick={jumpToNewest}
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
