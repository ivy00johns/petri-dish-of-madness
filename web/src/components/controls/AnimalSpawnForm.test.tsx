/**
 * AnimalSpawnForm tests (EM-143) — the MENAGERIE god-panel form.
 *
 * Covers:
 *  • species picker renders all 7 catalog species
 *  • submit calls onSpawn with {species, location, name?}
 *  • name is optional (absent when blank)
 *  • flash confirmation appears and clears
 *  • animalStyle() returns distinct values for all 7 species
 *  • animalStyle() falls back to cat for unknown species (FALLBACK GUARANTEE)
 *  • speciesEmoji() returns distinct values for all 7 species
 *  • speciesEmoji() falls back to 🐾 for unknown species
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AnimalSpawnForm, ANIMAL_SPECIES_CATALOG } from './AnimalSpawnForm';
import { animalStyle, speciesEmoji, ANIMAL_STYLES } from '../world3d/worldSpace';

// ── AnimalSpawnForm component ─────────────────────────────────────────────────

const PLACES = [
  { id: 'plaza', name: 'Central Plaza', x: 0, y: 0, kind: 'social' as const, description: '' },
  { id: 'market', name: 'Market', x: 0, y: 0, kind: 'work' as const, description: '' },
];

function renderForm(onSpawn = vi.fn()) {
  render(
    <AnimalSpawnForm
      world={{
        type: 'world_state',
        seq: 1,
        tick: 0,
        day: 0,
        running: true,
        tick_interval_seconds: 2,
        places: PLACES,
        agents: [],
        rules: [],
        profiles: [],
        buildings: [],
        animals: [],
        billboard: [],
      }}
      onSpawn={onSpawn}
    />,
  );
  return { onSpawn };
}

describe('AnimalSpawnForm — species picker (EM-143)', () => {
  it('renders all 7 catalog species as options', () => {
    renderForm();
    const select = screen.getByLabelText('Animal species');
    const options = Array.from(select.querySelectorAll('option')).map((o) => o.value);
    expect(options).toEqual([...ANIMAL_SPECIES_CATALOG]);
  });

  it('has all 7 species in the catalog constant', () => {
    expect(ANIMAL_SPECIES_CATALOG).toHaveLength(7);
    expect(ANIMAL_SPECIES_CATALOG).toContain('cat');
    expect(ANIMAL_SPECIES_CATALOG).toContain('dog');
    expect(ANIMAL_SPECIES_CATALOG).toContain('squirrel');
    expect(ANIMAL_SPECIES_CATALOG).toContain('raccoon');
    expect(ANIMAL_SPECIES_CATALOG).toContain('goat');
    expect(ANIMAL_SPECIES_CATALOG).toContain('fox');
    expect(ANIMAL_SPECIES_CATALOG).toContain('crow');
  });
});

describe('AnimalSpawnForm — submit (EM-143)', () => {
  it('calls onSpawn with species and location when submitted (name blank)', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await user.selectOptions(screen.getByLabelText('Animal species'), 'raccoon');
    await user.click(screen.getByRole('button', { name: 'Spawn animal' }));

    expect(onSpawn).toHaveBeenCalledTimes(1);
    const arg = onSpawn.mock.calls[0][0];
    expect(arg.species).toBe('raccoon');
    expect(arg.location).toBe('plaza'); // first place default
    expect(arg.name).toBeUndefined(); // omitted when blank
  });

  it('includes name in spec when name is filled', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await user.type(screen.getByLabelText(/Animal name/), 'Bandit');
    await user.selectOptions(screen.getByLabelText('Animal species'), 'fox');
    await user.click(screen.getByRole('button', { name: 'Spawn animal' }));

    const arg = onSpawn.mock.calls[0][0];
    expect(arg.name).toBe('Bandit');
    expect(arg.species).toBe('fox');
  });

  it('uses the location picker value', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await user.selectOptions(screen.getByLabelText('Animal spawn location'), 'market');
    await user.click(screen.getByRole('button', { name: 'Spawn animal' }));

    expect(onSpawn.mock.calls[0][0].location).toBe('market');
  });

  it('shows a flash confirmation after submit and clears name', async () => {
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText(/Animal name/), 'Zorro');
    await user.click(screen.getByRole('button', { name: 'Spawn animal' }));

    expect(screen.getByRole('status')).toHaveTextContent(/Zorro joined/);
    // Name input cleared
    expect(screen.getByLabelText(/Animal name/)).toHaveValue('');
  });

  it('does not include name key when name is only whitespace', async () => {
    const user = userEvent.setup();
    const { onSpawn } = renderForm();

    await user.type(screen.getByLabelText(/Animal name/), '   ');
    await user.click(screen.getByRole('button', { name: 'Spawn animal' }));

    expect(onSpawn.mock.calls[0][0].name).toBeUndefined();
  });
});

// ── animalStyle() ─────────────────────────────────────────────────────────────

describe('animalStyle() — 7 species + fallback (EM-143)', () => {
  it('returns a distinct body color for each new species', () => {
    const bodies = ['squirrel', 'raccoon', 'goat', 'fox', 'crow'].map(
      (s) => animalStyle(s).body,
    );
    // All distinct
    const set = new Set(bodies);
    expect(set.size).toBe(bodies.length);
    // All are not the cat default
    for (const b of bodies) {
      expect(b).not.toBe(ANIMAL_STYLES.cat.body);
    }
  });

  it('falls back to cat tint for unknown species (FALLBACK GUARANTEE)', () => {
    expect(animalStyle('dragon')).toEqual(ANIMAL_STYLES.cat);
    expect(animalStyle('')).toEqual(ANIMAL_STYLES.cat);
    expect(animalStyle('undefined')).toEqual(ANIMAL_STYLES.cat);
  });

  it('crow is near-black (body darker than #444)', () => {
    const crow = animalStyle('crow');
    const r = parseInt(crow.body.slice(1, 3), 16);
    const g = parseInt(crow.body.slice(3, 5), 16);
    const b = parseInt(crow.body.slice(5, 7), 16);
    expect(r + g + b).toBeLessThan(3 * 0x44); // 0x44 * 3 = 204
  });

  it('fox has a warm/orange body', () => {
    const fox = animalStyle('fox');
    const r = parseInt(fox.body.slice(1, 3), 16);
    const g = parseInt(fox.body.slice(3, 5), 16);
    const b = parseInt(fox.body.slice(5, 7), 16);
    // Red channel dominant (orange-red)
    expect(r).toBeGreaterThan(g);
    expect(r).toBeGreaterThan(b);
  });
});

// ── speciesEmoji() ────────────────────────────────────────────────────────────

describe('speciesEmoji() — 7 species + fallback (EM-143)', () => {
  it('returns a distinct emoji for each catalog species', () => {
    const emojis = ANIMAL_SPECIES_CATALOG.map((s) => speciesEmoji(s));
    const set = new Set(emojis);
    expect(set.size).toBe(ANIMAL_SPECIES_CATALOG.length);
  });

  it('returns 🐱 for cat and 🐶 for dog', () => {
    expect(speciesEmoji('cat')).toBe('🐱');
    expect(speciesEmoji('dog')).toBe('🐶');
  });

  it('returns correct emojis for the 5 new species', () => {
    expect(speciesEmoji('squirrel')).toBe('🐿️');
    expect(speciesEmoji('raccoon')).toBe('🦝');
    expect(speciesEmoji('goat')).toBe('🐐');
    expect(speciesEmoji('fox')).toBe('🦊');
    expect(speciesEmoji('crow')).toBe('🐦‍⬛');
  });

  it('falls back to 🐾 for unknown species (FALLBACK GUARANTEE)', () => {
    expect(speciesEmoji('dragon')).toBe('🐾');
    expect(speciesEmoji('')).toBe('🐾');
    expect(speciesEmoji('undefined')).toBe('🐾');
  });
});
