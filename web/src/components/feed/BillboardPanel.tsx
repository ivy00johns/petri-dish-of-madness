/**
 * BillboardPanel (W11b EM-091c) — the village notice board, surfaced in the
 * live view as a collapsible section directly under the story-so-far digest
 * (the chat-first column owns the reading surfaces).
 *
 * Posts come from `world.billboard` (the engine's capped-20 state, serialized
 * into every world_state broadcast). When a backend predates the billboard
 * (or an old snapshot omits it) the panel degrades to deriving posts from
 * `billboard_posted` events in the rolling history — and when neither source
 * has anything it renders a labeled empty state (§7 rule), never a blank.
 *
 * Rendering: newest-first; each post shows the author + their model chip
 * (resolved live from world.agents — data-driven colors, the established
 * hex-only alpha-append idiom). God replies read in GOD INK (the violet
 * --lab-god register) with a ✦ GOD chip, visually distinct from agent posts.
 *
 * Token-only styling; the collapse preference persists to localStorage.
 */

import { useEffect, useMemo, useState } from 'react';
import type { WorldState, WorldEvent, BillboardPost } from '../../types';
import '../../inspector/inspector-tokens.css';

interface BillboardPanelProps {
  world: WorldState | null;
  /** Rolling history (newest-first) — the fallback post source. */
  history: WorldEvent[];
}

const COLLAPSE_KEY = 'em.billboard.collapsed';
const MAX_POSTS_SHOWN = 8;

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * The post list, newest-first. Primary source: world.billboard (the engine
 * caps it at the 20 newest). Fallback: billboard_posted events from history
 * (pre-W11b backend / snapshot without the field).
 */
export function billboardPosts(
  world: WorldState | null,
  history: WorldEvent[],
): BillboardPost[] {
  const fromState = world?.billboard;
  if (Array.isArray(fromState) && fromState.length > 0) {
    // Defensive sort — the cap promises "20 newest", not an order.
    return [...fromState].sort((a, b) => b.tick - a.tick);
  }
  const derived: BillboardPost[] = [];
  for (const e of history) {
    if (e.kind !== 'billboard_posted') continue;
    const text =
      typeof e.payload?.text === 'string' && e.payload.text.length > 0
        ? e.payload.text
        : e.text ?? '';
    if (!text || !e.actor_id) continue;
    derived.push({
      tick: e.tick,
      actor_id: e.actor_id,
      actor_type: e.actor_type ?? 'human_agent',
      text,
    });
    if (derived.length >= 20) break; // history is newest-first; mirror the cap
  }
  return derived;
}

export function BillboardPanel({ world, history }: BillboardPanelProps) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
  }, [collapsed]);

  const posts = useMemo(() => billboardPosts(world, history), [world, history]);

  // actor_id → {name, profile, color} for author attribution + model chips.
  const authorOf = useMemo(() => {
    const m = new Map<string, { name: string; profile: string | null; color: string | null }>();
    for (const a of world?.agents ?? []) {
      m.set(a.id, { name: a.name, profile: a.profile, color: a.profile_color ?? null });
    }
    return m;
  }, [world]);

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label="Village billboard — public notices and god replies"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">
          📌 BILLBOARD
        </h2>
        <div className="flex items-center gap-2">
          {posts.length > 0 && (
            <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
              {posts.length} post{posts.length === 1 ? '' : 's'}
            </span>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand the billboard panel' : 'Collapse the billboard panel'}
            title={collapsed ? 'Expand the billboard' : 'Collapse the billboard'}
            className="font-mono text-[10px] px-1.5 py-0.5 border border-lab-border text-lab-muted
                       hover:border-lab-acid hover:text-lab-acid rounded-sm cursor-pointer
                       transition-colors duration-100"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        </div>
      </div>

      {!collapsed && (
        posts.length === 0 ? (
          // §7: labeled empty state — explain where posts come from.
          <p className="m-0 px-3 py-2 font-mono text-[10px] text-lab-dim leading-relaxed">
            The notice board is bare. Agents pin notes from the plaza or town
            hall (post_billboard); your replies from the god panel land here too.
          </p>
        ) : (
          <ul className="m-0 p-0 list-none max-h-44 overflow-y-auto">
            {posts.slice(0, MAX_POSTS_SHOWN).map((post, i) => (
              <PostRow key={`${post.tick}-${post.actor_id}-${i}`} post={post} authorOf={authorOf} />
            ))}
            {posts.length > MAX_POSTS_SHOWN && (
              <li className="px-3 py-1 font-mono text-[9px] text-lab-dim">
                +{posts.length - MAX_POSTS_SHOWN} older post{posts.length - MAX_POSTS_SHOWN === 1 ? '' : 's'} on the board
              </li>
            )}
          </ul>
        )
      )}
    </section>
  );
}

function PostRow({
  post,
  authorOf,
}: {
  post: BillboardPost;
  authorOf: Map<string, { name: string; profile: string | null; color: string | null }>;
}) {
  const god = post.actor_type === 'god';
  const author = god ? null : authorOf.get(post.actor_id);
  const name = god ? 'THE WATCHERS' : author?.name ?? post.actor_id;

  return (
    <li
      className="px-3 py-1.5 border-b border-lab-border/40"
      style={{ borderLeft: `3px solid ${god ? 'var(--lab-god)' : author?.color ?? 'var(--marker-other)'}` }}
    >
      <p
        className={`m-0 font-mono text-[11px] leading-snug break-words ${god ? 'font-semibold' : 'text-lab-text'}`}
        style={god ? { color: 'var(--lab-god-bright)' } : undefined}
      >
        “{post.text}”
      </p>
      <p className="m-0 mt-0.5 flex items-center gap-1.5 font-mono text-[9px] text-lab-muted">
        {god ? (
          <span
            className="font-bold px-1 py-px border rounded-sm uppercase tracking-wider"
            style={{ color: 'var(--lab-god-bright)', borderColor: 'var(--lab-god)' }}
            title="A god-mode reply — agents read it on the notice board"
          >
            ✦ god
          </span>
        ) : (
          <>
            <span className="text-lab-text">{name}</span>
            {/* Model chip (hex-only alpha-append idiom — data-driven color). */}
            {author?.profile && author.color && author.color.startsWith('#') && (
              <span
                className="px-1 py-px border rounded-sm whitespace-nowrap"
                style={{ color: author.color, borderColor: author.color + '50' }}
                title={`posted by a ${author.profile} villager`}
              >
                {author.profile}
              </span>
            )}
          </>
        )}
        <span className="text-lab-dim tabular-nums ml-auto">T{post.tick}</span>
      </p>
    </li>
  );
}
