/**
 * Props — the EM-118 "lived-in town" pass: lamp posts with warm glowing heads
 * flanking the dirt paths, benches facing the plaza, rustic fence arcs on the
 * home edge, plus bushes, mushrooms (clustered near the wild commons), and
 * rocks toward the town edge.
 *
 * All placement is deterministic (foliageLayout: hashUnit + place geometry)
 * and respects the building-slot clearance model — near props sit inside
 * BAND_MIN of their place, wild props stay ≥ BAND_MAX from every center.
 * Every part is an instanced batch sharing one cached toon material, ~15 draw
 * calls total. The lamp heads glow via emissive only (no extra pointLights —
 * the 60fps bar beats per-lamp lighting).
 */

import { useMemo } from 'react';
import type { Place } from '../../types';
import { GOLDEN_HOUR, toonMaterial } from './toon';
import {
  layoutLamps,
  layoutBenches,
  layoutFences,
  layoutMushrooms,
  layoutWildScatter,
  BUSH_COUNT,
  ROCK_COUNT,
} from './foliageLayout';
import { InstancedScatter } from './InstancedScatter';

// Warm prop tints (golden-hour palette family).
const IRON = '#4a3b32';
const BENCH_WOOD = '#8a6242';
const FENCE_WOOD = '#9b7653';
const BUSH_A = '#5e9a4e';
const BUSH_B = '#6daa58';
const MUSHROOM_STEM = '#f1e6d4';
const MUSHROOM_CAP = '#c45a4a';
const ROCK = '#a39a8c';

export function TownProps({ places }: { places: Place[] }) {
  const lamps = useMemo(() => layoutLamps(places), [places]);
  const benches = useMemo(() => layoutBenches(places), [places]);
  const fences = useMemo(() => layoutFences(places), [places]);
  const mushrooms = useMemo(() => layoutMushrooms(places), [places]);
  const bushes = useMemo(() => layoutWildScatter(BUSH_COUNT, 'bush', places), [places]);
  const rocks = useMemo(() => layoutWildScatter(ROCK_COUNT, 'rock', places), [places]);

  // Two bush tones so the shrubbery doesn't read as copy-paste.
  const bushesA = useMemo(() => bushes.filter((_, i) => i % 2 === 0), [bushes]);
  const bushesB = useMemo(() => bushes.filter((_, i) => i % 2 === 1), [bushes]);

  return (
    <group>
      {/* ── Lamp posts: base + iron post + warm glowing head ──────────── */}
      <InstancedScatter items={lamps} material={toonMaterial(IRON)} offset={[0, 0.09, 0]}>
        <cylinderGeometry args={[0.16, 0.22, 0.18, 6]} />
      </InstancedScatter>
      <InstancedScatter items={lamps} material={toonMaterial(IRON)} offset={[0, 1.05, 0]}>
        <cylinderGeometry args={[0.05, 0.07, 1.9, 6]} />
      </InstancedScatter>
      <InstancedScatter
        items={lamps}
        material={toonMaterial(GOLDEN_HOUR.glow, {
          emissive: GOLDEN_HOUR.glow,
          emissiveIntensity: 1.8,
        })}
        offset={[0, 2.08, 0]}
        castShadow={false}
      >
        <sphereGeometry args={[0.17, 10, 8]} />
      </InstancedScatter>

      {/* ── Benches: seat + back + two legs, facing the plaza ─────────── */}
      <InstancedScatter items={benches} material={toonMaterial(BENCH_WOOD)} offset={[0, 0.46, 0]}>
        <boxGeometry args={[1.5, 0.1, 0.45]} />
      </InstancedScatter>
      <InstancedScatter
        items={benches}
        material={toonMaterial(BENCH_WOOD)}
        offset={[0, 0.78, 0.21]}
      >
        <boxGeometry args={[1.5, 0.45, 0.08]} />
      </InstancedScatter>
      <InstancedScatter items={benches} material={toonMaterial(IRON)} offset={[-0.58, 0.21, 0]}>
        <boxGeometry args={[0.12, 0.42, 0.4]} />
      </InstancedScatter>
      <InstancedScatter items={benches} material={toonMaterial(IRON)} offset={[0.58, 0.21, 0]}>
        <boxGeometry args={[0.12, 0.42, 0.4]} />
      </InstancedScatter>

      {/* ── Fence arcs: post + two rails per segment ──────────────────── */}
      <InstancedScatter items={fences} material={toonMaterial(FENCE_WOOD)} offset={[-1.0, 0.42, 0]}>
        <boxGeometry args={[0.13, 0.85, 0.13]} />
      </InstancedScatter>
      <InstancedScatter items={fences} material={toonMaterial(FENCE_WOOD)} offset={[0, 0.62, 0]}>
        <boxGeometry args={[2.15, 0.09, 0.06]} />
      </InstancedScatter>
      <InstancedScatter items={fences} material={toonMaterial(FENCE_WOOD)} offset={[0, 0.32, 0]}>
        <boxGeometry args={[2.15, 0.09, 0.06]} />
      </InstancedScatter>

      {/* ── Bushes: squashed spheres in two greens ────────────────────── */}
      <InstancedScatter
        items={bushesA}
        material={toonMaterial(BUSH_A)}
        offset={[0, 0.34, 0]}
        squash={0.72}
      >
        <sphereGeometry args={[0.55, 9, 7]} />
      </InstancedScatter>
      <InstancedScatter
        items={bushesB}
        material={toonMaterial(BUSH_B)}
        offset={[0, 0.34, 0]}
        squash={0.72}
      >
        <sphereGeometry args={[0.55, 9, 7]} />
      </InstancedScatter>

      {/* ── Mushrooms near the wild commons: stem + cap ───────────────── */}
      <InstancedScatter
        items={mushrooms}
        material={toonMaterial(MUSHROOM_STEM)}
        offset={[0, 0.14, 0]}
      >
        <cylinderGeometry args={[0.07, 0.1, 0.28, 6]} />
      </InstancedScatter>
      <InstancedScatter
        items={mushrooms}
        material={toonMaterial(MUSHROOM_CAP)}
        offset={[0, 0.33, 0]}
      >
        <coneGeometry args={[0.26, 0.24, 8]} />
      </InstancedScatter>

      {/* ── Rocks: squashed dodecahedra toward the wild edge ──────────── */}
      <InstancedScatter
        items={rocks}
        material={toonMaterial(ROCK)}
        offset={[0, 0.18, 0]}
        squash={0.62}
      >
        <dodecahedronGeometry args={[0.42, 0]} />
      </InstancedScatter>
    </group>
  );
}
