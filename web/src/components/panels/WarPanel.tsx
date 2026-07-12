/**
 * WarPanel (Wave O / EM-256–259) — the belligerent-factions surface: which
 * circles are at war, the grievances driving them there, and each war's
 * exhaustion. A collapsible left-column section modeled on BillboardPanel; it
 * reads world.wars / world.grievances / world.factions (all serialized into
 * every world_state broadcast ONLY when non-empty).
 *
 * PEACETIME RENDERS NOTHING — with no wars and no grievances the panel returns
 * null, so the golden peacetime UI stays byte-identical (war ships dormant
 * behind war.enabled; the whole grievance ledger is absent until it fires).
 *
 * A war's `belligerents` / `aggressor_id` and the grievance keys
 * (`"{srcFactionId}->{dstFactionId}"`) are FACTION IDS; names resolve from
 * world.factions (fallback: a shortened id). Each belligerent renders as a
 * faction chip in the crime-red conflict register; the aggressor wears the ⚔
 * war badge. Grievances read as directional `src → dst · heat N` rows.
 *
 * Token-only styling; the collapse preference persists to localStorage.
 */

import { useEffect, useMemo, useState } from 'react';
import type { WorldState, War, Faction } from '../../types';
import '../../inspector/inspector-tokens.css';

interface WarPanelProps {
  world: WorldState | null;
}

const COLLAPSE_KEY = 'em.war.collapsed';
const MAX_GRIEVANCES_SHOWN = 6;

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

/** A parsed grievance: the aggrieved faction `src` holds `heat` against `dst`. */
export interface GrievanceRow {
  src: string;
  dst: string;
  heat: number;
}

/**
 * Parse + sort the directional grievance ledger (hottest first). The key is
 * `"{src}->{dst}"`; faction ids carry no `->`, so a single split is safe. A
 * malformed key (no separator) is dropped rather than rendered half-parsed.
 */
export function grievanceRows(grievances: Record<string, number> | undefined): GrievanceRow[] {
  const rows: GrievanceRow[] = [];
  for (const [key, heat] of Object.entries(grievances ?? {})) {
    const i = key.indexOf('->');
    if (i <= 0) continue;
    rows.push({ src: key.slice(0, i), dst: key.slice(i + 2), heat: Number(heat) || 0 });
  }
  return rows.sort((a, b) => b.heat - a.heat);
}

/** Active wars first, then settling ones; stable by start tick within each. */
export function sortedWars(wars: Record<string, War> | undefined): War[] {
  return Object.values(wars ?? {}).sort((a, b) => {
    const active = Number(b.status === 'active') - Number(a.status === 'active');
    if (active !== 0) return active;
    return a.start_tick - b.start_tick;
  });
}

/** A short, readable faction label: its name, else a truncated id. */
function factionLabel(id: string, factions: Record<string, Faction> | undefined): string {
  const name = factions?.[id]?.name;
  if (name && name.trim()) return name;
  return id.length > 10 ? `${id.slice(0, 10)}…` : id;
}

export function WarPanel({ world }: WarPanelProps) {
  const [collapsed, setCollapsed] = useState(loadCollapsed);

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
  }, [collapsed]);

  const wars = useMemo(() => sortedWars(world?.wars), [world]);
  const grievances = useMemo(() => grievanceRows(world?.grievances), [world]);
  const factions = world?.factions;

  // Peacetime: no wars AND no grievances ⇒ render nothing at all, so the panel
  // adds zero chrome until organized violence actually fires (golden-safe).
  if (wars.length === 0 && grievances.length === 0) return null;

  const activeCount = wars.filter((w) => w.status === 'active').length;

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label="War — belligerent factions and grievances"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">
          ⚔ WAR
        </h2>
        <div className="flex items-center gap-2">
          {activeCount > 0 && (
            <span
              className="font-mono text-[10px] px-1 py-px border rounded-sm normal-case tracking-normal"
              style={{ color: 'var(--marker-crime)', borderColor: 'var(--marker-crime)' }}
            >
              {activeCount} active
            </span>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand the war panel' : 'Collapse the war panel'}
            title={collapsed ? 'Expand the war panel' : 'Collapse the war panel'}
            className="font-mono text-[10px] px-1.5 py-0.5 border border-lab-border text-lab-muted
                       hover:border-lab-acid hover:text-lab-acid rounded-sm cursor-pointer
                       transition-colors duration-100"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="max-h-56 overflow-y-auto">
          {wars.length > 0 && (
            <ul className="m-0 p-0 list-none">
              {wars.map((war) => (
                <WarRow key={war.id} war={war} factions={factions} />
              ))}
            </ul>
          )}

          {grievances.length > 0 && (
            <div className="px-3 py-1.5 border-t border-lab-border/40">
              <p className="m-0 mb-1 font-mono text-[9px] uppercase tracking-wider text-lab-dim">
                grievances
              </p>
              <ul className="m-0 p-0 list-none space-y-0.5">
                {grievances.slice(0, MAX_GRIEVANCES_SHOWN).map((g) => (
                  <li
                    key={`${g.src}->${g.dst}`}
                    className="flex items-center gap-1.5 font-mono text-[10px] text-lab-muted"
                  >
                    <span className="text-lab-text truncate">{factionLabel(g.src, factions)}</span>
                    <span className="text-lab-dim" aria-hidden="true">→</span>
                    <span className="text-lab-text truncate">{factionLabel(g.dst, factions)}</span>
                    <span
                      className="ml-auto tabular-nums px-1 py-px border rounded-sm whitespace-nowrap"
                      style={{ color: 'var(--marker-crime)', borderColor: 'var(--marker-crime)' }}
                      title={`grievance heat — casus belli builds toward a declare_war vote`}
                    >
                      heat {g.heat}
                    </span>
                  </li>
                ))}
                {grievances.length > MAX_GRIEVANCES_SHOWN && (
                  <li className="font-mono text-[9px] text-lab-dim">
                    +{grievances.length - MAX_GRIEVANCES_SHOWN} more simmering
                  </li>
                )}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/** A faction chip in the crime-red conflict register. The aggressor of a war
 *  wears the ⚔ war badge (belligerent marker). */
function FactionChip({
  label,
  aggressor = false,
}: {
  label: string;
  aggressor?: boolean;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 font-mono text-[10px] px-1 py-px border rounded-sm
                 whitespace-nowrap max-w-[9rem]"
      style={{ color: 'var(--marker-crime)', borderColor: 'var(--marker-crime)' }}
      title={aggressor ? 'The aggressor — declared this war' : 'A belligerent in this war'}
    >
      {aggressor && <span aria-hidden="true">⚔</span>}
      <span className="truncate">{label}</span>
    </span>
  );
}

function WarRow({
  war,
  factions,
}: {
  war: War;
  factions: Record<string, Faction> | undefined;
}) {
  const settled = war.status !== 'active';
  // Aggressor first, then the other belligerent (the defender).
  const aggressor = war.aggressor_id;
  const defender = war.belligerents.find((b) => b !== aggressor) ?? war.belligerents[1] ?? aggressor;

  return (
    <li
      className={`px-3 py-1.5 border-b border-lab-border/40 ${settled ? 'opacity-60' : ''}`}
      style={{ borderLeft: `3px solid var(--marker-crime)` }}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <FactionChip label={factionLabel(aggressor, factions)} aggressor />
        <span className="font-mono text-[10px] text-lab-dim uppercase tracking-wide" aria-hidden="true">
          vs
        </span>
        <FactionChip label={factionLabel(defender, factions)} />
        {settled && (
          <span className="ml-auto font-mono text-[9px] uppercase tracking-wider text-lab-dim">
            settled
          </span>
        )}
      </div>

      {war.aims && war.aims.trim() && (
        <p className="m-0 mt-0.5 font-mono text-[10px] italic text-lab-muted leading-snug break-words">
          “{war.aims}”
        </p>
      )}

      {war.exhaustion && Object.keys(war.exhaustion).length > 0 && (
        <p className="m-0 mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[9px] text-lab-dim">
          {Object.entries(war.exhaustion).map(([fid, ex]) => (
            <span key={fid} className="tabular-nums">
              {factionLabel(fid, factions)} · exhaustion {ex}
            </span>
          ))}
        </p>
      )}
    </li>
  );
}
