/**
 * BlindLineupContext (EM-309, Layer 1) — the shared reveal state for the
 * spectator model-taste-test.
 *
 * The provider owns the round: whether the feature is enabled (the
 * `blind_lineup.enabled` flag), the viewer's per-slot guesses, and whether the
 * round has been revealed. Deep display components (the model legend, the
 * roster strip, the feed chips) consume only the narrow `{ active, maskName }`
 * slice to hide model-name TEXT behind ??? while the round is live — the profile
 * COLORS stay, so the viewer can still map "the teal one" to a slot; they just
 * don't know teal's model until reveal.
 *
 * Everything here is browser-only React state. Nothing is serialized into the
 * world snapshot or event log, so the reveal never reaches the replay surface.
 * The default context value masks NOTHING, so components that render outside a
 * provider (e.g. in their own unit tests) behave exactly as before.
 */

import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { MASK, blindLineupEnabled } from '../../lib/blindLineup';

export interface BlindLineupContextValue {
  /** Feature flag on. */
  enabled: boolean;
  /** The round has been revealed (chips show their real models). */
  revealed: boolean;
  /** enabled && !revealed — while true, model-name text renders as ???. */
  active: boolean;
  /** Mask a model-name string: ??? while active, else the name unchanged. */
  maskName: (name: string | null | undefined) => string;
  /** profileName → guessed family (empty until the viewer picks). */
  guesses: Record<string, string>;
  /** Record (or clear, with '') a guess for a slot. */
  setGuess: (profileName: string, family: string) => void;
  /** Flip the round: chips reveal their real models. */
  reveal: () => void;
  /** Start a fresh round: re-hide the chips and clear guesses. */
  reset: () => void;
}

const DEFAULT_VALUE: BlindLineupContextValue = {
  enabled: false,
  revealed: false,
  active: false,
  maskName: (name) => name ?? '',
  guesses: {},
  setGuess: () => {},
  reveal: () => {},
  reset: () => {},
};

const BlindLineupContext = createContext<BlindLineupContextValue>(DEFAULT_VALUE);

/** Consume the reveal state. Safe outside a provider (masks nothing). */
export function useBlindLineup(): BlindLineupContextValue {
  return useContext(BlindLineupContext);
}

export function BlindLineupProvider({ children }: { children: ReactNode }) {
  // Flag read once per mount; a build either ships the mode or it doesn't.
  const [enabled] = useState(blindLineupEnabled);
  const [revealed, setRevealed] = useState(false);
  const [guesses, setGuesses] = useState<Record<string, string>>({});

  const active = enabled && !revealed;

  const maskName = useCallback(
    (name: string | null | undefined) => (active ? MASK : name ?? ''),
    [active],
  );

  const setGuess = useCallback((profileName: string, family: string) => {
    setGuesses((prev) => {
      const next = { ...prev };
      if (family) next[profileName] = family;
      else delete next[profileName];
      return next;
    });
  }, []);

  const reveal = useCallback(() => setRevealed(true), []);
  const reset = useCallback(() => {
    setRevealed(false);
    setGuesses({});
  }, []);

  const value = useMemo<BlindLineupContextValue>(
    () => ({ enabled, revealed, active, maskName, guesses, setGuess, reveal, reset }),
    [enabled, revealed, active, maskName, guesses, setGuess, reveal, reset],
  );

  return <BlindLineupContext.Provider value={value}>{children}</BlindLineupContext.Provider>;
}
