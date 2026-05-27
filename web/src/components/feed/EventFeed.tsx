/**
 * EventFeed — live terminal-style event log.
 * Newest entries on top. Left-bordered with profile_color.
 * agent_action entries show thought on hover.
 */

import { useRef, useEffect, useState } from 'react';
import type { WorldEvent, EventKind } from '../../types';

interface EventFeedProps {
  events: WorldEvent[];
}

// Icon per event kind
const KIND_ICON: Record<EventKind, string> = {
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

export function EventFeed({ events }: EventFeedProps) {
  const [paused, setPaused] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const prevLengthRef = useRef(0);
  const newEventIdsRef = useRef<Set<number>>(new Set());

  // Track new events
  useEffect(() => {
    if (events.length > prevLengthRef.current) {
      const newCount = events.length - prevLengthRef.current;
      // The first newCount events are new (newest-first)
      const newIds = new Set(events.slice(0, newCount).map(e => e.seq));
      newEventIdsRef.current = newIds;
      // Clear after animation completes
      setTimeout(() => {
        newEventIdsRef.current = new Set();
      }, 300);
    }
    prevLengthRef.current = events.length;
  }, [events]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="lab-header flex items-center justify-between">
        <span>EVENT STREAM</span>
        <div className="flex items-center gap-2">
          <span className="text-lab-muted text-[10px]">
            {events.length > 0 ? `${events.length} events` : 'NO EVENTS'}
          </span>
          <button
            className={`font-mono text-[10px] px-1.5 py-0.5 border transition-colors duration-150 cursor-pointer
                        ${paused
                          ? 'border-lab-acid text-lab-acid'
                          : 'border-lab-border text-lab-muted hover:border-lab-acid hover:text-lab-acid'
                        }`}
            onClick={() => setPaused(p => !p)}
            title={paused ? 'Resume auto-scroll' : 'Pause auto-scroll'}
          >
            {paused ? 'PAUSED' : 'LIVE'}
          </button>
        </div>
      </div>

      {/* Feed list */}
      <div
        ref={listRef}
        className="flex-1 overflow-y-auto"
        onMouseEnter={() => setPaused(true)}
        onMouseLeave={() => setPaused(false)}
      >
        {events.length === 0 ? (
          <div className="flex items-center justify-center h-16 font-mono text-xs text-lab-dim">
            WAITING FOR EVENTS…
          </div>
        ) : (
          events.map((event) => (
            <FeedEntry
              key={event.seq}
              event={event}
              isNew={newEventIdsRef.current.has(event.seq)}
            />
          ))
        )}
      </div>
    </div>
  );
}
