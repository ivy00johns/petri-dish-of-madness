/**
 * GalleryPanel (Atelier follow-up — Wave I / EM-210) — the read-only artwork
 * viewer. A collapsible thumbnail grid of the agent-generated images the world
 * REMEMBERS, so the operator can actually SEE the art the villagers paint and
 * vote onto the plaza.
 *
 * Source of truth: the live `GET /api/gallery` endpoint, which returns only the
 * records whose PNG actually exists on disk. The gallery record + image_posted
 * are written synchronously at create_image time, but the PNG fetch is
 * best-effort (bounded, skip-under-load, swallows 402s) — so `world.gallery`
 * (the replay-pure sim record) can list pieces whose image never materialized.
 * Reading the disk-aware endpoint keeps the viewer from pointing an <img> at a
 * missing file (no 404 spam, no phantom "art unavailable" tiles). When the
 * endpoint is unavailable (a backend predating it, or offline) the panel
 * degrades to `world.gallery` / image_posted history with a per-thumb
 * placeholder as the final safety net.
 *
 * The PNG bytes are an external side-artifact under /assets/images/<id>.png; the
 * panel reads each record's RELATIVE `url` straight (the same path the 3D
 * PlazaBanner textures — proxied to the backend in dev via vite.config).
 *
 * Clicking a thumbnail opens a lightbox with the full image + the painter's
 * prompt + attribution. The one currently hung over the plaza (matching
 * `plaza_banner_ref`, else the newest promoted) wears a ★ PLAZA badge.
 *
 * Token-only styling; the collapse preference persists to localStorage.
 */

import { useEffect, useMemo, useState } from 'react';
import type { WorldState, WorldEvent, GalleryImage } from '../../types';
import '../../inspector/inspector-tokens.css';

interface GalleryPanelProps {
  world: WorldState | null;
  /** Rolling history (newest-first) — the fallback record source. */
  history: WorldEvent[];
}

/** The `/api/gallery` payload — records filtered to those with a real PNG. */
interface GalleryFeed {
  images: GalleryImage[];
  plaza_banner_ref: string;
  /** Records in the sim's gallery, including ones whose PNG never materialized. */
  total: number;
  /** Records actually backed by a PNG on disk (= images.length). */
  materialized: number;
}

const COLLAPSE_KEY = 'em.gallery.collapsed';
/** Mirror the engine's default max_gallery when deriving from history. */
const DERIVE_CAP = 30;

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * The gallery records, newest-first. Primary source: `world.gallery` (the engine
 * caps it at the newest max_gallery). Fallback: `image_posted` events from
 * history, with `promoted` flipped on for any id that later got an
 * `image_promoted` (pre-Atelier backend / a snapshot without the field).
 */
export function galleryImages(
  world: WorldState | null,
  history: WorldEvent[],
): GalleryImage[] {
  const fromState = world?.gallery;
  if (Array.isArray(fromState) && fromState.length > 0) {
    // Defensive sort — the cap promises "newest", not an order.
    return [...fromState].sort((a, b) => b.created_tick - a.created_tick);
  }

  // Fallback: rebuild from the event log. history is newest-first.
  const promotedIds = new Set<string>();
  for (const e of history) {
    if (e.kind !== 'image_promoted') continue;
    const id = e.payload?.image_id;
    if (typeof id === 'string' && id) promotedIds.add(id);
  }

  const derived: GalleryImage[] = [];
  const seen = new Set<string>();
  for (const e of history) {
    if (e.kind !== 'image_posted') continue;
    const id = e.payload?.image_id;
    const url = e.payload?.url;
    if (typeof id !== 'string' || !id || seen.has(id)) continue;
    if (typeof url !== 'string' || !url) continue;
    seen.add(id);
    derived.push({
      image_id: id,
      prompt: typeof e.payload?.prompt === 'string' ? e.payload.prompt : '',
      proposer_id: e.actor_id ?? '',
      created_tick: e.tick,
      url,
      promoted: promotedIds.has(id),
    });
    if (derived.length >= DERIVE_CAP) break; // mirror the engine cap
  }
  return derived;
}

/**
 * The id currently hung over the plaza: an explicit banner ref when present,
 * else the newest promoted record (the derive path has no banner field).
 */
function currentPlazaRef(bannerRef: string, images: GalleryImage[]): string {
  if (bannerRef) return bannerRef;
  return images.find((g) => g.promoted)?.image_id ?? '';
}

/** A stable key over the sim's gallery id-set — refetch the disk view when it changes. */
function gallerySig(world: WorldState | null): string {
  const g = world?.gallery ?? [];
  return `${g.length}:${g[0]?.image_id ?? ''}:${g[g.length - 1]?.image_id ?? ''}`;
}

export function GalleryPanel({ world, history }: GalleryPanelProps) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const [selected, setSelected] = useState<GalleryImage | null>(null);
  // undefined = the disk-aware fetch is in flight (don't flash phantom tiles);
  // null     = the endpoint is unavailable (old backend / offline) → use props;
  // GalleryFeed = the materialized records straight from the backend.
  const [feed, setFeed] = useState<GalleryFeed | null | undefined>(undefined);

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
  }, [collapsed]);

  const sig = gallerySig(world);
  useEffect(() => {
    let ignore = false;
    (async () => {
      try {
        const res = await fetch('/api/gallery');
        if (!res.ok) throw new Error(String(res.status));
        const data = await res.json();
        if (ignore) return;
        if (Array.isArray(data?.images)) {
          setFeed({
            images: data.images as GalleryImage[],
            plaza_banner_ref: typeof data.plaza_banner_ref === 'string' ? data.plaza_banner_ref : '',
            total: typeof data.total === 'number' ? data.total : data.images.length,
            materialized: typeof data.materialized === 'number' ? data.materialized : data.images.length,
          });
        } else {
          setFeed(null);
        }
      } catch {
        if (!ignore) setFeed(null); // fall back to props (old backend / offline)
      }
    })();
    return () => { ignore = true; };
  }, [sig]);

  // Prop-derived list — the fallback when the endpoint is unavailable.
  const fallback = useMemo(() => galleryImages(world, history), [world, history]);

  // Resolve the display list + plaza ref + the unmaterialized count.
  const { images, plazaRef, unrendered, loading } = useMemo(() => {
    if (feed) {
      const imgs = [...feed.images].sort((a, b) => b.created_tick - a.created_tick);
      return {
        images: imgs,
        plazaRef: currentPlazaRef(feed.plaza_banner_ref, imgs),
        unrendered: Math.max(0, feed.total - feed.materialized),
        loading: false,
      };
    }
    if (feed === null) {
      // Endpoint unavailable — degrade to the sim record (with the per-thumb
      // placeholder as the final safety net for any missing PNG).
      return {
        images: fallback,
        plazaRef: currentPlazaRef(world?.plaza_banner_ref ?? '', fallback),
        unrendered: 0,
        loading: false,
      };
    }
    // feed === undefined: the disk view is still loading. Don't render the
    // unfiltered prop list (it would flash phantom tiles + their 404s).
    return { images: [] as GalleryImage[], plazaRef: '', unrendered: 0, loading: fallback.length > 0 };
  }, [feed, fallback, world]);

  // actor_id → {name, profile, color} for painter attribution + model chips.
  const painterOf = useMemo(() => {
    const m = new Map<string, { name: string; profile: string | null; color: string | null }>();
    for (const a of world?.agents ?? []) {
      m.set(a.id, { name: a.name, profile: a.profile, color: a.profile_color ?? null });
    }
    return m;
  }, [world]);

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label="Atelier gallery — agent-generated artwork"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">
          🖼 GALLERY
        </h2>
        <div className="flex items-center gap-2">
          {images.length > 0 && (
            <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
              {images.length} piece{images.length === 1 ? '' : 's'}
              {unrendered > 0 && (
                <span title={`${unrendered} piece(s) the agents 'painted' but whose image never rendered (a credit-exhausted or load-skipped fetch)`}>
                  {' '}· +{unrendered} unrendered
                </span>
              )}
            </span>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand the gallery panel' : 'Collapse the gallery panel'}
            title={collapsed ? 'Expand the gallery' : 'Collapse the gallery'}
            className="font-mono text-[10px] px-1.5 py-0.5 border border-lab-border text-lab-muted
                       hover:border-lab-acid hover:text-lab-acid rounded-sm cursor-pointer
                       transition-colors duration-100"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        </div>
      </div>

      {!collapsed && (
        loading ? (
          <p className="m-0 px-3 py-2 font-mono text-[10px] text-lab-dim leading-relaxed">
            Loading the gallery…
          </p>
        ) : images.length === 0 ? (
          // §7: labeled empty state — explain where the art comes from.
          <p className="m-0 px-3 py-2 font-mono text-[10px] text-lab-dim leading-relaxed">
            The gallery is empty. Villagers paint at the Atelier (create_image) and
            vote pieces onto the plaza banner (promote_image). Nothing has been
            hung yet — or image generation is currently switched off.
          </p>
        ) : (
          <div
            className="grid grid-cols-3 gap-1 px-2 py-2 max-h-64 overflow-y-auto"
            role="list"
            aria-label="Gallery thumbnails"
          >
            {images.map((img) => (
              <Thumb
                key={img.image_id}
                img={img}
                onPlaza={img.image_id === plazaRef}
                painter={painterOf.get(img.proposer_id) ?? null}
                onOpen={() => setSelected(img)}
              />
            ))}
          </div>
        )
      )}

      {selected && (
        <Lightbox
          img={selected}
          onPlaza={selected.image_id === plazaRef}
          painter={painterOf.get(selected.proposer_id) ?? null}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  );
}

type Painter = { name: string; profile: string | null; color: string | null } | null;

function Thumb({
  img,
  onPlaza,
  painter,
  onOpen,
}: {
  img: GalleryImage;
  onPlaza: boolean;
  painter: Painter;
  onOpen: () => void;
}) {
  const [broken, setBroken] = useState(false);
  const by = painter?.name ?? img.proposer_id;
  const label = `${img.prompt || 'untitled'} — by ${by}, tick ${img.created_tick}${onPlaza ? ' (on the plaza)' : ''}`;

  return (
    <button
      type="button"
      role="listitem"
      onClick={onOpen}
      title={label}
      aria-label={label}
      className="group relative block aspect-square w-full overflow-hidden border border-lab-border
                 hover:border-lab-acid rounded-sm cursor-pointer transition-colors duration-100
                 bg-lab-bg p-0"
      style={onPlaza ? { borderColor: 'var(--lab-acid)' } : undefined}
    >
      {broken ? (
        <span className="flex h-full w-full items-center justify-center px-1 text-center
                         font-mono text-[8px] leading-tight text-lab-dim">
          art unavailable
        </span>
      ) : (
        <img
          src={img.url}
          alt={img.prompt || 'agent artwork'}
          loading="lazy"
          onError={() => setBroken(true)}
          className="h-full w-full object-cover"
        />
      )}
      {onPlaza && (
        <span
          className="absolute left-0 top-0 px-1 py-px font-mono text-[8px] font-bold uppercase
                     tracking-wider rounded-br-sm"
          style={{ color: 'var(--lab-bg)', background: 'var(--lab-acid)' }}
          title="Currently hung over the plaza by a town vote"
        >
          ★ plaza
        </span>
      )}
    </button>
  );
}

function Lightbox({
  img,
  onPlaza,
  painter,
  onClose,
}: {
  img: GalleryImage;
  onPlaza: boolean;
  painter: Painter;
  onClose: () => void;
}) {
  const [broken, setBroken] = useState(false);

  // Close on Escape — the standard lightbox affordance.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const by = painter?.name ?? img.proposer_id;
  const chip =
    painter?.profile && painter.color && painter.color.startsWith('#') ? painter : null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Artwork: ${img.prompt || 'untitled'}`}
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] max-w-2xl flex-col overflow-hidden border border-lab-border
                   bg-lab-surface rounded-sm shadow-2xl"
      >
        <div className="lab-header flex items-center justify-between gap-2">
          <h3 className="m-0 flex items-center gap-2 font-mono text-xs font-semibold uppercase tracking-widest">
            🖼 ARTWORK
            {onPlaza && (
              <span
                className="px-1 py-px text-[9px] font-bold rounded-sm normal-case tracking-normal"
                style={{ color: 'var(--lab-bg)', background: 'var(--lab-acid)' }}
              >
                ★ on the plaza
              </span>
            )}
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close the artwork view"
            title="Close (Esc)"
            className="font-mono text-[11px] px-1.5 py-0.5 border border-lab-border text-lab-muted
                       hover:border-lab-acid hover:text-lab-acid rounded-sm cursor-pointer
                       transition-colors duration-100"
          >
            ✕
          </button>
        </div>

        <div className="flex min-h-0 items-center justify-center overflow-auto bg-lab-bg p-3">
          {broken ? (
            <p className="m-0 px-6 py-12 font-mono text-[11px] text-lab-dim text-center leading-relaxed">
              The PNG for this piece isn't available right now
              <br />
              (image generation may be switched off, or the file was pruned).
            </p>
          ) : (
            <img
              src={img.url}
              alt={img.prompt || 'agent artwork'}
              onError={() => setBroken(true)}
              className="max-h-[60vh] w-auto max-w-full object-contain"
            />
          )}
        </div>

        <div className="px-3 py-2 border-t border-lab-border">
          <p className="m-0 font-mono text-[11px] leading-snug text-lab-text break-words">
            "{img.prompt || 'untitled'}"
          </p>
          <p className="m-0 mt-1 flex items-center gap-1.5 font-mono text-[9px] text-lab-muted">
            <span className="text-lab-text">{by}</span>
            {chip && (
              <span
                className="px-1 py-px border rounded-sm whitespace-nowrap"
                style={{ color: chip.color!, borderColor: chip.color! + '50' }}
                title={`painted by a ${chip.profile} villager`}
              >
                {chip.profile}
              </span>
            )}
            <span className="text-lab-dim tabular-nums ml-auto">T{img.created_tick}</span>
          </p>
        </div>
      </div>
    </div>
  );
}
