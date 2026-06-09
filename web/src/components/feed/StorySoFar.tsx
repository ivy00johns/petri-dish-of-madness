/**
 * StorySoFar (EM-094) — the compact, always-on digest block at the top of the
 * feed column. Pure presentation over the zero-LLM `storySoFar` selector
 * (lib/storySoFar.ts): roster + death ticks, active rules, project statuses,
 * and the "current drama" heuristic — all recomputed live from the rolling
 * history + world_state. No backend calls, works identically in mock mode.
 *
 * The NARRATOR toggle is client-side display only: when on, the newest
 * `narrator_summary` event (the optional server-side LLM narrator,
 * event-log.md v1.2.0) renders prominently; when none exist it shows a
 * labeled "narrator off on the server" state. The preference persists.
 */

import { useEffect, useMemo, useState } from 'react';
import type { WorldEvent, WorldState } from '../../types';
import { storySoFar } from '../../lib/storySoFar';

interface StorySoFarProps {
  world: WorldState | null;
  /** The deep rolling history (newest-first) — NOT the 200-cap feed. */
  history: WorldEvent[];
}

const NARRATOR_KEY = 'em.story.narrator';

function loadNarratorPref(): boolean {
  try {
    return localStorage.getItem(NARRATOR_KEY) === '1';
  } catch {
    return false;
  }
}

/** One labeled digest line: a fixed-width label + wrapping value text. */
function DigestLine({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="font-mono text-[9px] uppercase tracking-wider text-lab-muted w-14 shrink-0">
        {label}
      </span>
      <span className="font-mono text-[11px] leading-snug text-lab-text break-words min-w-0">
        {children}
      </span>
    </div>
  );
}

export function StorySoFar({ world, history }: StorySoFarProps) {
  const [narratorOn, setNarratorOn] = useState(loadNarratorPref);

  useEffect(() => {
    try { localStorage.setItem(NARRATOR_KEY, narratorOn ? '1' : '0'); } catch { /* ignore */ }
  }, [narratorOn]);

  const digest = useMemo(() => storySoFar(history, world), [history, world]);

  const deadLine = digest.dead
    .map((d) => `${d.name} (${d.deathTick !== null ? `T${d.deathTick}` : 'tick unknown'})`)
    .join(', ');

  // Project readout: name + status (+ progress while it's rising).
  const projectLine = digest.projects
    .map((p) =>
      p.status === 'under_construction' || p.status === 'planned'
        ? `${p.name} ${p.progress}% ${p.status === 'planned' ? 'planned' : 'building'}`
        : `${p.name} ${p.status}`,
    )
    .join(' · ');

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label="Story so far"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        {/* EM-082 a11y: a real heading for the digest section. */}
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">STORY SO FAR</h2>
        <button
          type="button"
          onClick={() => setNarratorOn((v) => !v)}
          aria-pressed={narratorOn}
          title={
            narratorOn
              ? 'Narrator display on — showing server narrator recaps when present'
              : 'Narrator display off — click to surface server narrator recaps'
          }
          className={`font-mono text-[10px] px-1.5 py-0.5 border rounded-sm cursor-pointer transition-colors duration-100
                      ${narratorOn
                        ? 'border-lab-acid text-lab-acid'
                        : 'border-lab-border text-lab-muted hover:border-lab-acid hover:text-lab-acid'}`}
        >
          NARRATOR {narratorOn ? 'ON' : 'OFF'}
        </button>
      </div>

      <div className="px-3 py-2 space-y-1.5">
        {/* Narrator recap — prominent when enabled; labeled off-state when the
            server has never emitted one (world.narrator.enabled is false). */}
        {narratorOn && (
          digest.narratorLatest ? (
            <blockquote className="border-l-2 border-lab-acid bg-lab-chrome/40 px-2 py-1.5">
              <p className="font-mono text-[11px] leading-relaxed text-lab-text italic">
                “{digest.narratorLatest.text ?? '[narrator recap]'}”
              </p>
              <footer className="font-mono text-[9px] text-lab-muted mt-1 uppercase tracking-wider">
                narrator · T{digest.narratorLatest.tick} · {digest.narratorCount} recap{digest.narratorCount === 1 ? '' : 's'}
              </footer>
            </blockquote>
          ) : (
            <div className="border-l-2 border-lab-border bg-lab-chrome/30 px-2 py-1.5 font-mono text-[10px] text-lab-muted">
              Narrator off on the server (world.narrator.enabled) — no recaps in this run.
            </div>
          )
        )}

        {/* Current drama — the HEADLINE of the digest (chat-first: this block
            tops the centerpiece column, so the lead line reads like one). */}
        {digest.drama ? (
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-[9px] uppercase tracking-wider text-lab-muted w-14 shrink-0">
              drama
            </span>
            <span className="font-mono text-[13px] leading-snug text-lab-text break-words min-w-0 font-medium">
              <span className="text-lab-warn font-semibold">[{digest.drama.label}]</span>{' '}
              {digest.drama.text}{' '}
              <span className="text-lab-muted text-[10px] tabular-nums">T{digest.drama.tick}</span>
            </span>
          </div>
        ) : (
          <DigestLine label="drama">
            <span className="text-lab-dim">all quiet so far</span>
          </DigestLine>
        )}

        {/* Roster: alive count + the dead with their death ticks. */}
        <DigestLine label="roster">
          <span className="text-lab-acid tabular-nums">
            {digest.aliveCount}/{digest.totalCount}
          </span>{' '}
          alive
          {digest.dead.length > 0 ? (
            <>
              {' · '}
              <span className="text-lab-danger">✦</span>{' '}
              <span className="text-lab-muted">{deadLine}</span>
            </>
          ) : (
            <span className="text-lab-dim"> · no deaths yet</span>
          )}
        </DigestLine>

        {/* Rules: active count + the newest law of the land. */}
        <DigestLine label="rules">
          {digest.activeRuleCount > 0 ? (
            <>
              <span className="tabular-nums">{digest.activeRuleCount}</span> active
              {digest.newestRuleText && (
                <span className="text-lab-muted"> · newest: “{digest.newestRuleText}”</span>
              )}
            </>
          ) : (
            <span className="text-lab-dim">no rules passed yet</span>
          )}
          {digest.ruleVoteInProgress && (
            <span className="text-lab-warn font-semibold"> · vote in progress</span>
          )}
        </DigestLine>

        {/* Projects: every W7 building and where it stands. */}
        <DigestLine label="projects">
          {digest.projects.length > 0 ? (
            <span className="text-lab-muted">{projectLine}</span>
          ) : (
            <span className="text-lab-dim">no projects yet</span>
          )}
        </DigestLine>
      </div>
    </section>
  );
}
