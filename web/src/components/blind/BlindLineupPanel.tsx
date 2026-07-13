/**
 * BlindLineupPanel (EM-309, Layer 1) — the spectator guess card.
 *
 * Lives in the left feed column (the centerpiece), directly under the digest,
 * as a collapsible section. It lists the models actually in play as anonymous
 * colored SLOTS, lets the viewer match each to a model family, then REVEALs —
 * the chips across the whole live view flip from ??? to their real models and
 * this card grades the round with a per-model-family accuracy scorecard that
 * accumulates across sessions (localStorage only).
 *
 * Renders nothing unless the `blind_lineup.enabled` flag is on. Everything is
 * browser state — no sim coupling, nothing on the replay surface.
 */

import { useEffect, useMemo, useState } from 'react';
import type { WorldState } from '../../types';
import {
  accumulate,
  gradeRound,
  lineupFamilies,
  lineupProfiles,
  loadScorecard,
  modelFamily,
  roundScore,
  saveScorecard,
  type Scorecard,
} from '../../lib/blindLineup';
import { useBlindLineup } from './BlindLineupContext';

interface BlindLineupPanelProps {
  world: WorldState | null;
}

const COLLAPSE_KEY = 'em.blindLineup.collapsed';

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

/** A → Model A, B → Model B … a stable, model-neutral slot label by index. */
function slotLabel(i: number): string {
  return `Model ${String.fromCharCode(65 + (i % 26))}${i >= 26 ? String.fromCharCode(65 + Math.floor(i / 26) - 1) : ''}`;
}

function cap(s: string): string {
  return s.length === 0 ? s : s[0].toUpperCase() + s.slice(1);
}

export function BlindLineupPanel({ world }: BlindLineupPanelProps) {
  const { enabled, revealed, guesses, setGuess, reveal, reset } = useBlindLineup();
  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const [scorecard, setScorecard] = useState<Scorecard>(() => loadScorecard());

  useEffect(() => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
  }, [collapsed]);

  const profiles = useMemo(() => lineupProfiles(world), [world]);
  const families = useMemo(() => lineupFamilies(profiles), [profiles]);

  const results = useMemo(() => gradeRound(profiles, guesses), [profiles, guesses]);
  const score = useMemo(() => roundScore(results), [results]);

  if (!enabled) return null;

  const onReveal = () => {
    // Fold this round into the running per-family scorecard (localStorage only).
    const next = accumulate(loadScorecard(), gradeRound(profiles, guesses));
    saveScorecard(next);
    setScorecard(next);
    reveal();
  };

  const onNewRound = () => {
    reset();
  };

  const scoreFamilies = Object.keys(scorecard).sort();

  return (
    <section
      className="shrink-0 border-b border-lab-border bg-lab-surface"
      aria-label="Blind Lineup — guess which model each slot is"
    >
      <div className="lab-header flex items-center justify-between gap-2">
        <h2 className="m-0 font-mono text-xs font-semibold tracking-widest uppercase">
          🕵 BLIND LINEUP
        </h2>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-lab-dim normal-case tracking-normal">
            {revealed ? 'revealed' : `${score.answered}/${score.total} guessed`}
          </span>
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand the Blind Lineup panel' : 'Collapse the Blind Lineup panel'}
            title={collapsed ? 'Expand the Blind Lineup' : 'Collapse the Blind Lineup'}
            className="font-mono text-[10px] px-1.5 py-0.5 border border-lab-border text-lab-muted
                       hover:border-lab-acid hover:text-lab-acid rounded-sm cursor-pointer
                       transition-colors duration-100"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="px-3 py-2">
          {profiles.length === 0 ? (
            <p className="m-0 font-mono text-[10px] text-lab-dim leading-relaxed">
              No models on stage yet. Once agents start acting, their (hidden)
              models line up here to guess.
            </p>
          ) : (
            <>
              <p className="m-0 mb-2 font-mono text-[10px] text-lab-muted leading-relaxed">
                {revealed
                  ? 'Chips are live. Every ??? across the view flipped to its real model.'
                  : 'Every model chip is hidden. Match each colored slot to a model family, then reveal.'}
              </p>

              <ul className="m-0 p-0 list-none space-y-1.5">
                {profiles.map((p, i) => {
                  const r = results[i];
                  const guess = guesses[p.name] ?? '';
                  return (
                    <li
                      key={p.name}
                      className={`flex items-center gap-2 ${revealed ? 'blind-flip' : ''}`}
                      style={revealed ? ({ animationDelay: `${i * 110}ms` } as React.CSSProperties) : undefined}
                    >
                      {/* Color swatch — the persistent slot identity (never hidden). */}
                      <span
                        className="w-3 h-3 shrink-0 rounded-sm border border-lab-border"
                        style={{ backgroundColor: p.color }}
                        aria-hidden="true"
                      />

                      {!revealed ? (
                        <>
                          <span className="font-mono text-[11px] text-lab-text w-16 shrink-0">
                            {slotLabel(i)}
                          </span>
                          <label className="sr-only" htmlFor={`blind-guess-${i}`}>
                            Guess the model family for {slotLabel(i)}
                          </label>
                          <select
                            id={`blind-guess-${i}`}
                            value={guess}
                            onChange={(e) => setGuess(p.name, e.target.value)}
                            className="flex-1 min-w-0 font-mono text-[11px] bg-lab-chrome text-lab-text
                                       border border-lab-border rounded-sm px-1.5 py-0.5 cursor-pointer
                                       hover:border-lab-acid focus:border-lab-acid outline-none"
                            aria-label={`Guess for ${slotLabel(i)}`}
                          >
                            <option value="">— guess —</option>
                            {families.map((f) => (
                              <option key={f} value={f}>
                                {cap(f)}
                              </option>
                            ))}
                          </select>
                        </>
                      ) : (
                        <>
                          <span
                            className="font-mono text-[11px] font-semibold truncate max-w-[8rem]"
                            style={{ color: p.color }}
                            title={p.model_id}
                          >
                            {p.name}
                          </span>
                          <span className="font-mono text-[9px] text-lab-dim truncate flex-1 min-w-0">
                            {modelFamily(p)}
                          </span>
                          {r.guessedFamily == null ? (
                            <span className="font-mono text-[9px] text-lab-muted shrink-0" title="You didn't guess this slot">
                              — no guess
                            </span>
                          ) : (
                            <span
                              className="font-mono text-[10px] font-bold shrink-0"
                              style={{ color: r.correct ? 'var(--lab-acid)' : 'var(--lab-danger)' }}
                              title={`You guessed ${cap(r.guessedFamily)} — actually ${cap(r.actualFamily)}`}
                            >
                              {r.correct ? '✓' : `✗ ${cap(r.guessedFamily)}`}
                            </span>
                          )}
                        </>
                      )}
                    </li>
                  );
                })}
              </ul>

              {/* Actions */}
              <div className="mt-2.5 flex items-center gap-2">
                {!revealed ? (
                  <button
                    type="button"
                    onClick={onReveal}
                    className="font-mono text-[11px] font-semibold uppercase tracking-wider
                               px-2.5 py-1 border border-lab-acid text-lab-acid bg-lab-acid/10
                               hover:bg-lab-acid/20 rounded-sm cursor-pointer transition-colors"
                    title="Flip every ??? chip to its real model"
                  >
                    ▶ Reveal
                  </button>
                ) : (
                  <>
                    <span
                      className="font-mono text-[12px] font-bold"
                      style={{ color: score.correct === score.total && score.total > 0 ? 'var(--lab-acid)' : 'var(--lab-text)' }}
                    >
                      You matched {score.correct}/{score.total}
                    </span>
                    <button
                      type="button"
                      onClick={onNewRound}
                      className="ml-auto font-mono text-[10px] uppercase tracking-wider
                                 px-2 py-0.5 border border-lab-border-bright text-lab-text bg-lab-chrome
                                 hover:border-lab-acid hover:text-lab-acid rounded-sm cursor-pointer transition-colors"
                      title="Re-hide the chips and guess again"
                    >
                      ↻ New round
                    </button>
                  </>
                )}
              </div>

              {/* Cross-session per-family scorecard. */}
              {scoreFamilies.length > 0 && (
                <div className="mt-3 border-t border-lab-border/50 pt-2">
                  <h3 className="m-0 mb-1 font-mono text-[9px] font-semibold tracking-widest uppercase text-lab-muted">
                    Your accuracy by family
                  </h3>
                  <ul className="m-0 p-0 list-none space-y-0.5">
                    {scoreFamilies.map((fam) => {
                      const t = scorecard[fam];
                      const pct = t.seen > 0 ? Math.round((100 * t.correct) / t.seen) : 0;
                      return (
                        <li key={fam} className="flex items-center gap-2 font-mono text-[10px]">
                          <span className="text-lab-text w-20 shrink-0 truncate">{cap(fam)}</span>
                          <span className="flex-1 min-w-0 h-1.5 bg-lab-chrome rounded-full overflow-hidden">
                            <span
                              className="block h-full rounded-full bg-lab-acid-dim"
                              style={{ width: `${pct}%` }}
                            />
                          </span>
                          <span className="text-lab-muted tabular-nums shrink-0 w-16 text-right">
                            {t.correct}/{t.seen} · {pct}%
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
