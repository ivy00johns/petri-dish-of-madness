/**
 * MemeLineagePanel (Wave O / EM-251–255) — THE culture surface: the town's
 * meme FAMILY TREE (idea → drifted idea → drifted-again), the belief camps that
 * cluster around them, and the one meme the town canonized as its motif. A
 * collapsible left-column section modeled EXACTLY on WarPanel; it reads
 * world.memes / world.culture_camps / world.town_motif_ref /
 * world.dominant_meme_ids (all serialized into every world_state broadcast ONLY
 * when non-empty).
 *
 * A CULTURE-FREE WORLD RENDERS NOTHING — with no memes and no camps the panel
 * returns null, so the golden pre-culture UI stays byte-identical (culture ships
 * dormant behind world.culture.enabled; the whole meme graph is absent until it
 * fires).
 *
 * The tree is built from `parent_id`/`generation`: roots (no resolvable parent)
 * head each lineage, children indent by depth in generation order. An image meme
 * (`image_id` set) shows its gallery thumbnail (join image_id → the gallery
 * entry's `url`), so the "fox in a crown → fox in a paper crown" drift reads as
 * a visible image family tree. Memes in `dominant_meme_ids` wear the ⭐ marker;
 * every row shows its generation + carrier count + virality.
 *
 * Culture camps render as faction-style chips in the mint (--faction-tint)
 * register — the SAME chip chrome WarPanel's belligerents use, recolored to the
 * culture accent so the register reads as a coherent sibling of war/factions.
 *
 * Token-only styling; the collapse preference persists to localStorage.
 */

import { useEffect, useMemo, useState } from 'react';
import type { WorldState, Meme, CultureCamp, GalleryImage } from '../../types';
import '../../inspector/inspector-tokens.css';

interface MemeLineagePanelProps {
  world: WorldState | null;
}

const COLLAPSE_KEY = 'em.culture.collapsed';
const MAX_LINEAGE_SHOWN = 12;

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

/** A meme placed in the flattened lineage tree: `depth` is its distance from
 *  the lineage root (0 = a root), used to indent the drift chain. */
export interface LineageRow {
  meme: Meme;
  depth: number;
}

/**
 * Flatten the meme graph into an ordered, depth-tagged render list: each root
 * (a meme with no `parent_id`, OR whose parent isn't in the map — an orphan is
 * promoted rather than dropped so no meme goes unrendered) is followed
 * depth-first by its descendants in generation order. Roots are ordered most-
 * viral first, then by origin tick, then id, so the ordering is stable. Pure so
 * the tree contract can be pinned directly in a test.
 */
export function memeLineageRows(memes: Record<string, Meme> | undefined): LineageRow[] {
  const all = Object.values(memes ?? {});
  if (all.length === 0) return [];

  const byId = new Map(all.map((m) => [m.id, m]));
  const childrenOf = new Map<string, Meme[]>();
  const roots: Meme[] = [];
  for (const m of all) {
    const pid = m.parent_id;
    if (pid && byId.has(pid) && pid !== m.id) {
      const kids = childrenOf.get(pid) ?? [];
      kids.push(m);
      childrenOf.set(pid, kids);
    } else {
      // No parent, a dangling parent id, or a self-reference ⇒ treat as a root.
      roots.push(m);
    }
  }

  const cmp = (a: Meme, b: Meme) =>
    (b.virality || 0) - (a.virality || 0) ||
    a.origin_tick - b.origin_tick ||
    (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);

  roots.sort(cmp);

  const rows: LineageRow[] = [];
  const visited = new Set<string>();
  const walk = (m: Meme, depth: number) => {
    if (visited.has(m.id)) return; // cycle guard
    visited.add(m.id);
    rows.push({ meme: m, depth });
    const kids = (childrenOf.get(m.id) ?? [])
      .slice()
      .sort((a, b) => a.generation - b.generation || cmp(a, b));
    for (const k of kids) walk(k, depth + 1);
  };
  for (const r of roots) walk(r, 0);
  return rows;
}

/** Culture camps, most-populous first then by founding tick (stable). */
export function sortedCamps(camps: Record<string, CultureCamp> | undefined): CultureCamp[] {
  return Object.values(camps ?? {}).sort(
    (a, b) => b.members.length - a.members.length || a.founded_tick - b.founded_tick,
  );
}

/** Resolve an image meme's gallery thumbnail url (or null when unavailable). */
function thumbUrl(meme: Meme, gallery: GalleryImage[] | undefined): string | null {
  if (!meme.image_id) return null;
  return gallery?.find((g) => g.image_id === meme.image_id)?.url ?? null;
}

export function MemeLineagePanel({ world }: MemeLineagePanelProps) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
  }, [collapsed]);

  const rows = useMemo(() => memeLineageRows(world?.memes), [world]);
  const camps = useMemo(() => sortedCamps(world?.culture_camps), [world]);
  const dominant = useMemo(() => new Set(world?.dominant_meme_ids ?? []), [world]);
  const gallery = world?.gallery;

  // The canonized town motif — resolved from the meme graph so we can show its
  // text (town_motif_ref is only an id). Null ⇒ no motif banner.
  const motif = useMemo(() => {
    const ref = world?.town_motif_ref;
    if (!ref) return null;
    return world?.memes?.[ref] ?? null;
  }, [world]);

  // Culture-free: no memes AND no camps ⇒ render nothing at all, so the panel
  // adds zero chrome until culture actually fires (golden-safe). A motif can
  // only resolve from a present meme, so this also covers the banner.
  if (rows.length === 0 && camps.length === 0) return null;

  const shown = rows.slice(0, MAX_LINEAGE_SHOWN);
  const overflow = rows.length - shown.length;

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label="Culture — memes, camps, and the town motif"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">
          🦊 CULTURE
        </h2>
        <div className="flex items-center gap-2">
          {rows.length > 0 && (
            <span
              className="font-mono text-[10px] px-1 py-px border rounded-sm normal-case tracking-normal"
              style={{ color: 'var(--faction-tint)', borderColor: 'var(--faction-tint)' }}
              title="Distinct memes spreading through the town"
            >
              {rows.length} meme{rows.length === 1 ? '' : 's'}
            </span>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand the culture panel' : 'Collapse the culture panel'}
            title={collapsed ? 'Expand the culture panel' : 'Collapse the culture panel'}
            className="font-mono text-[10px] px-1.5 py-0.5 border border-lab-border text-lab-muted
                       hover:border-lab-acid hover:text-lab-acid rounded-sm cursor-pointer
                       transition-colors duration-100"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="max-h-72 overflow-y-auto">
          {/* Dominant-motif banner — the canonized town motif. Mirrors the
              in-flow banner idiom (a tinted strip with an accent rule); renders
              nothing when town_motif_ref is null / unresolved (golden). */}
          {motif && <MotifBanner motif={motif} thumb={thumbUrl(motif, gallery)} />}

          {shown.length > 0 && (
            <ul className="m-0 p-0 list-none">
              {shown.map(({ meme, depth }) => (
                <MemeRow
                  key={meme.id}
                  meme={meme}
                  depth={depth}
                  dominant={dominant.has(meme.id)}
                  thumb={thumbUrl(meme, gallery)}
                />
              ))}
              {overflow > 0 && (
                <li className="px-3 py-1 font-mono text-[9px] text-lab-dim">
                  +{overflow} more spreading
                </li>
              )}
            </ul>
          )}

          {camps.length > 0 && (
            <div className="px-3 py-1.5 border-t border-lab-border/40">
              <p className="m-0 mb-1 font-mono text-[9px] uppercase tracking-wider text-lab-dim">
                camps
              </p>
              <div className="flex flex-wrap gap-1">
                {camps.map((camp) => (
                  <CampChip key={`${camp.name}:${camp.founded_tick}`} camp={camp} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** The canonized-motif banner — the town's dominant idea, named with its
 *  (image) thumbnail. Reads in the culture (mint) register with a left accent
 *  rule, the same in-flow banner idiom the plaza/notice surfaces use. */
function MotifBanner({ motif, thumb }: { motif: Meme; thumb: string | null }) {
  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5 border-b border-lab-border/40 bg-lab-chrome/40"
      style={{ borderLeft: `3px solid var(--faction-tint)` }}
      role="status"
      aria-label="The town's dominant motif"
    >
      {thumb && (
        <img
          src={thumb}
          alt={motif.text || 'town motif'}
          loading="lazy"
          className="h-8 w-8 object-cover border border-lab-border rounded-sm shrink-0"
        />
      )}
      <p className="m-0 font-mono text-[11px] leading-snug text-lab-text break-words">
        <span aria-hidden="true">🦊 </span>
        <span className="font-semibold" style={{ color: 'var(--faction-tint)' }}>
          “{motif.text || motif.id}”
        </span>{' '}
        <span className="text-lab-muted">is the town&apos;s dominant motif</span>
      </p>
    </div>
  );
}

/** One meme in the lineage tree — indented by depth, tagged with generation,
 *  carrier count, virality, and (for image memes) its gallery thumbnail. A
 *  dominant meme wears the ⭐ marker. */
function MemeRow({
  meme,
  depth,
  dominant,
  thumb,
}: {
  meme: Meme;
  depth: number;
  dominant: boolean;
  thumb: string | null;
}) {
  return (
    <li
      className="px-3 py-1.5 border-b border-lab-border/40"
      style={{
        borderLeft: `3px solid var(--faction-tint)`,
        // Indent the drift chain by depth (nested memes step right).
        paddingLeft: `${0.75 + depth * 0.85}rem`,
      }}
    >
      <div className="flex items-start gap-2">
        {thumb && (
          <img
            src={thumb}
            alt={meme.text || 'meme image'}
            loading="lazy"
            className="h-7 w-7 object-cover border border-lab-border rounded-sm shrink-0 mt-px"
          />
        )}
        <div className="min-w-0 flex-1">
          <p className="m-0 font-mono text-[11px] leading-snug text-lab-text break-words">
            {depth > 0 && <span className="text-lab-dim" aria-hidden="true">↳ </span>}
            {dominant && (
              <span
                title="A dominant meme — past the town's dominance threshold"
                aria-label="dominant"
                className="mr-0.5"
              >
                ⭐
              </span>
            )}
            {meme.text || meme.id}
          </p>
          <p className="m-0 mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[9px] text-lab-dim">
            <span className="uppercase tracking-wide">{meme.kind}</span>
            <span className="tabular-nums">gen {meme.generation}</span>
            <span className="tabular-nums" title="agents carrying this meme">
              {meme.carriers.length} carrier{meme.carriers.length === 1 ? '' : 's'}
            </span>
            <span className="tabular-nums" title="virality — spread pressure">
              vir {meme.virality}
            </span>
          </p>
        </div>
      </div>
    </li>
  );
}

/** A culture-camp chip in the mint (--faction-tint) register — the same chip
 *  chrome WarPanel's belligerents use, recolored to the culture accent. */
function CampChip({ camp }: { camp: CultureCamp }) {
  const label = camp.name && camp.name.trim() ? camp.name : '(unnamed camp)';
  return (
    <span
      className="inline-flex items-center gap-1 font-mono text-[10px] px-1 py-px border rounded-sm
                 whitespace-nowrap max-w-[9rem]"
      style={{ color: 'var(--faction-tint)', borderColor: 'var(--faction-tint)' }}
      title={`${label} — a belief camp of ${camp.members.length} member${camp.members.length === 1 ? '' : 's'}`}
    >
      <span aria-hidden="true">◈</span>
      <span className="truncate">{label}</span>
      <span className="tabular-nums opacity-70">{camp.members.length}</span>
    </span>
  );
}
