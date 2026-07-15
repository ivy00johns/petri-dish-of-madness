/**
 * FaithPanel (Wave O / EM-260–263) — THE religion surface: the town's faiths,
 * who congregates around them, and which rivals they've turned hostile toward. A
 * collapsible left-column section modeled EXACTLY on WarPanel; it reads
 * world.faiths / world.congregations (+ joins world.agents for devotion), all
 * serialized into every world_state broadcast ONLY when non-empty.
 *
 * A RELIGION-FREE WORLD RENDERS NOTHING — with no faiths the panel returns null,
 * so the golden pre-religion UI stays byte-identical (religion ships dormant
 * behind world.faith.enabled; the whole faith registry is absent until it fires).
 *
 * Each faith shows its name · deity · member count · (aggregate) devotion, a
 * ✞/☾ faith badge, and — when it has declared hostilities — the ⚔ marker in the
 * crime-red conflict register (the SAME token the war panel wears). Its
 * congregations render as chips in the candle-brass --faith-tint register — the
 * SAME chip chrome MemeLineagePanel's culture camps use (which itself reused
 * WarPanel's belligerent chips), recolored to the faith accent so the register
 * reads as a coherent sibling of war + culture. A schismed faith notes its parent
 * lineage (parent_id → the faith it split from).
 *
 * Token-only styling; the collapse preference persists to localStorage.
 */

import { useEffect, useMemo, useState } from 'react';
import type { WorldState, Faith, CultureCamp, Agent } from '../../types';
import '../../inspector/inspector-tokens.css';

interface FaithPanelProps {
  world: WorldState | null;
}

const COLLAPSE_KEY = 'em.faith.collapsed';
const MAX_FAITHS_SHOWN = 8;

// The two invented-faith badge glyphs (a ✞/☾ pair). Picked deterministically per
// faith id so a given faith always wears the same badge — visual variety without
// state. Purely cosmetic; the invented faiths map to neither real symbol.
const FAITH_BADGES = ['✞', '☾'] as const;

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

/** A tiny stable hash (djb2-ish) → a non-negative int, for the badge pick. */
function hashId(id: string): number {
  let h = 5381;
  for (let i = 0; i < id.length; i += 1) h = ((h << 5) + h + id.charCodeAt(i)) | 0;
  return Math.abs(h);
}

/** The badge glyph a faith wears — deterministic by id (✞ or ☾). */
export function faithBadge(id: string): string {
  return FAITH_BADGES[hashId(id) % FAITH_BADGES.length];
}

/** A faith placed in the render list, with its aggregated devotion + the
 *  congregations that cluster around it (resolved by shared faith_id). */
export interface FaithRow {
  faith: Faith;
  members: number;
  devotion: number;          // mean devotion of resolvable members (0 when none)
  hostile: number;           // count of hostile_to rivals (drives the ⚔ marker)
  congregations: CultureCamp[];
}

/**
 * Build the ordered faith render list, joining members → agents for the mean
 * devotion and grouping congregations by their members' shared faith_id (a
 * congregation clusters agents who share a faith, so its faith is whichever
 * faith_id its members carry). Sorted most-populous first, then founding tick,
 * then id — stable. Pure so the contract can be pinned directly in a test.
 */
export function faithRows(world: WorldState | null): FaithRow[] {
  const faiths = Object.values(world?.faiths ?? {});
  if (faiths.length === 0) return [];

  const agentById = new Map<string, Agent>((world?.agents ?? []).map((a) => [a.id, a]));

  // Group congregations under the faith their members share.
  const congByFaith = new Map<string, CultureCamp[]>();
  for (const cong of Object.values(world?.congregations ?? {})) {
    const fid = cong.members
      .map((id) => agentById.get(id)?.faith_id)
      .find((f): f is string => typeof f === 'string' && f.length > 0);
    if (!fid) continue;
    const list = congByFaith.get(fid) ?? [];
    list.push(cong);
    congByFaith.set(fid, list);
  }

  const rows: FaithRow[] = faiths.map((faith) => {
    const memberIds = faith.members ?? [];
    const devotions = memberIds
      .map((id) => agentById.get(id)?.devotion)
      .filter((d): d is number => typeof d === 'number');
    const devotion = devotions.length
      ? Math.round(devotions.reduce((s, d) => s + d, 0) / devotions.length)
      : 0;
    const congregations = (congByFaith.get(faith.id) ?? [])
      .slice()
      .sort((a, b) => b.members.length - a.members.length || a.founded_tick - b.founded_tick);
    return {
      faith,
      members: memberIds.length,
      devotion,
      hostile: (faith.hostile_to ?? []).length,
      congregations,
    };
  });

  return rows.sort(
    (a, b) =>
      b.members - a.members ||
      a.faith.founded_tick - b.faith.founded_tick ||
      (a.faith.id < b.faith.id ? -1 : a.faith.id > b.faith.id ? 1 : 0),
  );
}

/** A short, readable faith label: its name, else a truncated id. */
function faithLabel(id: string, faiths: Record<string, Faith> | undefined): string {
  const name = faiths?.[id]?.name;
  if (name && name.trim()) return name;
  return id.length > 10 ? `${id.slice(0, 10)}…` : id;
}

export function FaithPanel({ world }: FaithPanelProps) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
  }, [collapsed]);

  const rows = useMemo(() => faithRows(world), [world]);
  const faiths = world?.faiths;

  // Religion-free: no faiths ⇒ render nothing at all, so the panel adds zero
  // chrome until a faith is actually founded (golden-safe).
  if (rows.length === 0) return null;

  const shown = rows.slice(0, MAX_FAITHS_SHOWN);
  const overflow = rows.length - shown.length;
  const hostileCount = rows.filter((r) => r.hostile > 0).length;

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label="Faith — the town's religions and congregations"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">
          ✞ FAITH
        </h2>
        <div className="flex items-center gap-2">
          {hostileCount > 0 && (
            <span
              className="font-mono text-[10px] px-1 py-px border rounded-sm normal-case tracking-normal"
              style={{ color: 'var(--marker-crime)', borderColor: 'var(--marker-crime)' }}
              title="Faiths with declared hostilities"
            >
              ⚔ {hostileCount}
            </span>
          )}
          <span
            className="font-mono text-[10px] px-1 py-px border rounded-sm normal-case tracking-normal"
            style={{ color: 'var(--faith-tint)', borderColor: 'var(--faith-tint)' }}
            title="Distinct faiths kept in the town"
          >
            {rows.length} faith{rows.length === 1 ? '' : 's'}
          </span>
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand the faith panel' : 'Collapse the faith panel'}
            title={collapsed ? 'Expand the faith panel' : 'Collapse the faith panel'}
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
          <ul className="m-0 p-0 list-none">
            {shown.map((row) => (
              <FaithRowView key={row.faith.id} row={row} faiths={faiths} />
            ))}
            {overflow > 0 && (
              <li className="px-3 py-1 font-mono text-[9px] text-lab-dim">
                +{overflow} more faiths
              </li>
            )}
          </ul>
        </div>
      )}
    </section>
  );
}

/** One faith — name · deity · members · devotion, its ✞/☾ badge, an ⚔ marker
 *  when it has declared hostilities, a schism-lineage note, and its congregation
 *  chips. Reads in the candle-brass --faith-tint register. */
function FaithRowView({
  row,
  faiths,
}: {
  row: FaithRow;
  faiths: Record<string, Faith> | undefined;
}) {
  const { faith } = row;
  const badge = faithBadge(faith.id);
  const parent = faith.parent_id ? faithLabel(faith.parent_id, faiths) : null;

  return (
    <li
      className="px-3 py-1.5 border-b border-lab-border/40"
      style={{ borderLeft: `3px solid var(--faith-tint)` }}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span
          className="inline-flex items-center gap-1 font-mono text-[11px] font-semibold"
          style={{ color: 'var(--faith-tint)' }}
          title={`${faith.name} — faith of ${faith.deity}`}
        >
          <span aria-hidden="true">{badge}</span>
          <span className="truncate max-w-[10rem]">{faith.name}</span>
        </span>
        {row.hostile > 0 && (
          <span
            className="inline-flex items-center gap-0.5 font-mono text-[9px] px-1 py-px border rounded-sm"
            style={{ color: 'var(--marker-crime)', borderColor: 'var(--marker-crime)' }}
            title={`Hostile toward ${row.hostile} rival faith${row.hostile === 1 ? '' : 's'}`}
          >
            <span aria-hidden="true">⚔</span>
            {row.hostile}
          </span>
        )}
      </div>

      <p className="m-0 mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[9px] text-lab-dim">
        <span className="italic">of {faith.deity}</span>
        <span className="tabular-nums" title="devotees of this faith">
          {row.members} member{row.members === 1 ? '' : 's'}
        </span>
        <span className="tabular-nums" title="mean devotion across members">
          devotion {row.devotion}
        </span>
      </p>

      {parent && (
        <p
          className="m-0 mt-0.5 font-mono text-[9px] text-lab-dim"
          title="This faith schismed from another"
        >
          <span aria-hidden="true">⚡ </span>
          schism of {parent}
        </p>
      )}

      {row.congregations.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {row.congregations.map((cong) => (
            <CongregationChip key={`${cong.name}:${cong.founded_tick}`} congregation={cong} />
          ))}
        </div>
      )}
    </li>
  );
}

/** A congregation chip in the candle-brass (--faith-tint) register — the SAME
 *  chip chrome MemeLineagePanel's culture camps + WarPanel's belligerents use,
 *  recolored to the faith accent (⛪ the house-of-worship glyph). */
function CongregationChip({ congregation }: { congregation: CultureCamp }) {
  const label = congregation.name && congregation.name.trim() ? congregation.name : '(unnamed congregation)';
  const size = congregation.members.length;
  return (
    <span
      className="inline-flex items-center gap-1 font-mono text-[10px] px-1 py-px border rounded-sm
                 whitespace-nowrap max-w-[9rem]"
      style={{ color: 'var(--faith-tint)', borderColor: 'var(--faith-tint)' }}
      title={`${label} — a congregation of ${size} member${size === 1 ? '' : 's'}`}
    >
      <span aria-hidden="true">⛪</span>
      <span className="truncate">{label}</span>
      <span className="tabular-nums opacity-70">{size}</span>
    </span>
  );
}
