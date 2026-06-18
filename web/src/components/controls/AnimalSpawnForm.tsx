/**
 * AnimalSpawnForm (EM-143) — GOD CONSOLE "ADD ANIMAL" / MENAGERIE section.
 *
 * A god-console form: a SPECIES picker (the 7-species catalog), an optional
 * NAME (lab-input, maxLength 24), a LOCATION picker (lab-select from
 * world.places), and a "Spawn animal" submit (lab-btn lab-btn-primary).
 *
 * lab-* tokens only — NO hardcoded hex, no design literals (design-token-guard
 * clean). Mirrors the SpawnForm flash-confirmation pattern. The species list is
 * the canonical frontend constant (ANIMAL_SPECIES_CATALOG) — must match the
 * backend ANIMAL_SPECIES_CATALOG exactly.
 *
 * Usage example:
 *   <AnimalSpawnForm
 *     world={world}
 *     onSpawn={(spec) => spawnAnimal(spec)}
 *   />
 */

import { useState, useCallback } from 'react';
import type { WorldState } from '../../types';
import { speciesEmoji } from '../world3d/worldSpace';

// ── Catalog (EM-143) — MUST match backend ANIMAL_SPECIES_CATALOG verbatim ──
export const ANIMAL_SPECIES_CATALOG = [
  'cat',
  'dog',
  'squirrel',
  'raccoon',
  'goat',
  'fox',
  'crow',
] as const;

export type AnimalSpawnSpec = {
  species: typeof ANIMAL_SPECIES_CATALOG[number];
  name?: string;
  location: string;
};

/** Label-cased display name for a species. */
function speciesLabel(species: string): string {
  return species.charAt(0).toUpperCase() + species.slice(1);
}

interface AnimalSpawnFormProps {
  world: WorldState | null;
  onSpawn: (spec: AnimalSpawnSpec) => void;
}

export function AnimalSpawnForm({ world, onSpawn }: AnimalSpawnFormProps) {
  const places = world?.places ?? [];
  const defaultLocation = places[0]?.id ?? '';

  const [species, setSpecies] = useState<typeof ANIMAL_SPECIES_CATALOG[number]>('cat');
  const [name, setName] = useState('');
  const [location, setLocation] = useState(defaultLocation);
  const [justSpawned, setJustSpawned] = useState<string | null>(null);

  // Keep the location dropdown valid if the world arrives after first render.
  if (!location && defaultLocation) setLocation(defaultLocation);

  const canSpawn = !!species && !!location;

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (!canSpawn) return;
      const trimmedName = name.trim();
      onSpawn({
        species,
        location,
        ...(trimmedName ? { name: trimmedName } : {}),
      });
      const label = trimmedName || speciesLabel(species);
      setJustSpawned(label);
      setName('');
      window.setTimeout(() => setJustSpawned(null), 2200);
    },
    [canSpawn, species, name, location, onSpawn],
  );

  return (
    <form
      className="p-2 space-y-2"
      onSubmit={handleSubmit}
      aria-label="Spawn an animal"
    >
      {/* Species picker */}
      <div className="space-y-1">
        <label
          htmlFor="animal-spawn-species"
          className="block font-mono text-[10px] text-lab-muted uppercase tracking-wider"
        >
          Species <span className="text-lab-acid">*</span>
        </label>
        <select
          id="animal-spawn-species"
          value={species}
          onChange={(e) =>
            setSpecies(e.target.value as typeof ANIMAL_SPECIES_CATALOG[number])
          }
          className="lab-select w-full text-[10px]"
          aria-label="Animal species"
        >
          {ANIMAL_SPECIES_CATALOG.map((s) => (
            <option key={s} value={s}>
              {speciesEmoji(s)} {speciesLabel(s)}
            </option>
          ))}
        </select>
      </div>

      {/* Name (optional) */}
      <div className="space-y-1">
        <label
          htmlFor="animal-spawn-name"
          className="block font-mono text-[10px] text-lab-muted uppercase tracking-wider"
        >
          Animal name <span className="text-lab-dim">(optional)</span>
        </label>
        <input
          id="animal-spawn-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Bandit"
          maxLength={24}
          className="lab-input w-full text-[11px]"
          autoComplete="off"
        />
      </div>

      {/* Location */}
      <div className="space-y-1">
        <label
          htmlFor="animal-spawn-location"
          className="block font-mono text-[10px] text-lab-muted uppercase tracking-wider"
        >
          Location <span className="text-lab-acid">*</span>
        </label>
        <select
          id="animal-spawn-location"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          className="lab-select w-full text-[10px]"
          aria-label="Animal spawn location"
        >
          {places.length === 0 && <option value="">—</option>}
          {places.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </div>

      {/* Submit */}
      <button
        type="submit"
        className="lab-btn lab-btn-primary w-full"
        disabled={!canSpawn}
        aria-label="Spawn animal"
      >
        {speciesEmoji(species)} SPAWN ANIMAL
      </button>

      {/* Flash confirmation (mirrors SpawnForm pattern) */}
      {justSpawned && (
        <p
          className="font-mono text-[10px] text-lab-acid text-center animate-flash"
          role="status"
          aria-live="polite"
        >
          {justSpawned} joined the village.
        </p>
      )}
    </form>
  );
}
