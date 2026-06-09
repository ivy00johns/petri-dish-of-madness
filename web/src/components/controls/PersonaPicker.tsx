/**
 * PersonaPicker (W11b EM-092) — the persona-library cards inside the spawn
 * form. Fed by GET /api/personas (api.openapi.yaml v1.4.0): each card shows
 * name, archetype, the one-line personality, and the suggested model profile.
 *
 * Picking a card notifies the form (which prefills name/personality/profile —
 * all still editable); picking the active card again deselects it. The states
 * are all labeled per the §7 empty-state rule:
 *   • mock mode        → "no backend — persona library unavailable"
 *   • fetch failure    → same labeled state (freeform spawn unaffected)
 *   • empty library    → "library is empty" (distinct from failure)
 *
 * Token-only styling; the suggested-profile chip takes the profile's
 * data-driven color (the established hex-only alpha-append idiom).
 */

import { useEffect, useState } from 'react';
import { inspectorApi } from '../../inspector/api';
import type { PersonaRow } from '../../inspector/api';
import type { ModelProfile } from '../../types';

type PersonaState =
  | { status: 'idle' } // mock mode — fetch short-circuited
  | { status: 'loading' }
  | { status: 'unreachable' }
  | { status: 'ready'; personas: PersonaRow[] };

export function usePersonaLibrary(mockMode: boolean): PersonaState {
  const [state, setState] = useState<PersonaState>(
    mockMode ? { status: 'idle' } : { status: 'loading' },
  );

  useEffect(() => {
    if (mockMode) {
      setState({ status: 'idle' });
      return;
    }
    let alive = true;
    setState({ status: 'loading' });
    void inspectorApi.personas().then((personas) => {
      if (!alive) return;
      setState(personas === null ? { status: 'unreachable' } : { status: 'ready', personas });
    });
    return () => {
      alive = false;
    };
  }, [mockMode]);

  return state;
}

export function PersonaPicker({
  state,
  selected,
  profiles,
  onPick,
}: {
  state: PersonaState;
  /** Name of the currently-picked persona, or null (freeform). */
  selected: string | null;
  profiles: ModelProfile[];
  /** Pick a card (or null when the active card is clicked again). */
  onPick: (persona: PersonaRow | null) => void;
}) {
  return (
    <div className="space-y-1">
      <span className="block font-mono text-[10px] text-lab-muted uppercase tracking-wider">
        Persona library
      </span>

      {state.status === 'loading' ? (
        <p className="m-0 font-mono text-[9px] text-lab-dim leading-snug">
          loading personas from /api/personas…
        </p>
      ) : state.status === 'idle' || state.status === 'unreachable' ? (
        // §7: labeled no-backend state — the freeform fields below still work.
        <p className="m-0 font-mono text-[9px] text-lab-dim leading-snug border border-lab-border px-1.5 py-1 rounded-sm">
          {state.status === 'idle'
            ? 'no backend (mock mode) — persona library unavailable; spawn freeform below.'
            : 'persona library unreachable (/api/personas) — spawn freeform below.'}
        </p>
      ) : state.personas.length === 0 ? (
        <p className="m-0 font-mono text-[9px] text-lab-dim leading-snug border border-lab-border px-1.5 py-1 rounded-sm">
          the persona library is empty (config/personas.yaml) — spawn freeform below.
        </p>
      ) : (
        <div
          className="flex flex-col gap-1 max-h-44 overflow-y-auto pr-0.5"
          role="listbox"
          aria-label="Persona library — pick a card to prefill the spawn form"
        >
          {state.personas.map((p) => {
            const active = selected === p.name;
            const prof = profiles.find((m) => m.name === p.suggested_profile);
            // Hex-only alpha-append idiom (matches the feed's profile badges).
            const chipColor = prof?.color && prof.color.startsWith('#') ? prof.color : null;
            return (
              <button
                key={p.name}
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => onPick(active ? null : p)}
                title={
                  active
                    ? `${p.name} selected — click to deselect (back to freeform)`
                    : `Prefill the form with ${p.name} (${p.archetype}); fields stay editable`
                }
                className={`text-left font-mono px-1.5 py-1 border rounded-sm cursor-pointer transition-colors duration-100
                            ${active
                              ? 'border-lab-acid bg-lab-acid/10'
                              : 'border-lab-border hover:border-lab-border-bright bg-lab-chrome/40'}`}
              >
                <span className="flex items-baseline justify-between gap-1">
                  <span className={`text-[11px] font-semibold ${active ? 'text-lab-acid' : 'text-lab-text'}`}>
                    {p.name}
                  </span>
                  <span className="text-[8px] uppercase tracking-wider text-lab-muted">
                    {p.archetype}
                  </span>
                </span>
                <span className="block text-[9px] text-lab-muted leading-snug line-clamp-2">
                  {p.personality}
                </span>
                {p.suggested_profile && (
                  <span
                    className={`mt-0.5 inline-block text-[8px] px-1 py-px border rounded-sm whitespace-nowrap ${chipColor ? '' : 'border-lab-border text-lab-muted'}`}
                    style={chipColor ? { color: chipColor, borderColor: chipColor + '50' } : undefined}
                  >
                    ⌁ {p.suggested_profile}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
