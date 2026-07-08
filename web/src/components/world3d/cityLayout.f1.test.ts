// EM-268 (F1) — resolveBuildingPositions: render-from-position + flag-off
// byte-identical fallback to assignBuildingLots.
//
// T6 consumer audit (recorded here per the build contract; no wiring needed):
//   The ONLY production caller of assignBuildingLots was CozyWorld.tsx:541
//   (the 3D village render), now switched to resolveBuildingPositions. A grep of
//   `web/src/components/map` + `web/src/inspector` found NO reader of an
//   individual building's *position*:
//     • WorldMap.tsx draws ONE footprint per PLACE (places.forEach →
//       drawBuilding at the place's pixel), using place coordinates + kind — it
//       never reads building.position, so it needs no F1 wiring.
//     • The inspector reads place ids / snapshots, not building placement.
//   Therefore the 3D path is the sole position-consumer and is fully wired. No
//   other consumer test is required.
import { describe, it, expect } from 'vitest';
import {
  computeCityPlan, assignBuildingLots, resolveBuildingPositions,
  FREE_PLACEMENT_ENABLED,
} from './cityLayout';
import type { Building } from '../../types';

const TOWN = [
  { id: 'plaza', name: 'Plaza', x: 500, y: 500, kind: 'social' },
  { id: 'market', name: 'Market', x: 300, y: 400, kind: 'commerce' },
];
const plan = computeCityPlan({ places: TOWN as any });
const centers = new Map(TOWN.map((p) => [p.id, { x: 0, z: 0 }]));

function mk(id: string, extra: Partial<Building> = {}): Building {
  return { id, name: id, kind: 'workshop', location: 'plaza', status: 'operational',
           ...extra } as Building;
}

describe('EM-268 F1 resolveBuildingPositions', () => {
  it('flag OFF ⇒ identical to assignBuildingLots (byte-identical)', () => {
    const bs = [mk('bld_a', { position: [3, -2] })];   // position present but flag off
    const viaWrapper = resolveBuildingPositions(plan, bs, centers);
    const viaBase = assignBuildingLots(plan, bs, centers);
    // Guard the invariant this test relies on:
    expect(FREE_PLACEMENT_ENABLED).toBe(false);
    expect([...viaWrapper.entries()]).toEqual([...viaBase.entries()]);
  });

  it('with a position + flag on ⇒ renders the world-frame position directly', () => {
    const b = mk('bld_a', { position: [7.5, -4.25] });
    const out = resolveBuildingPositions(plan, [b], centers, /* forceFlag */ true);
    expect(out.get('bld_a')).toEqual({ x: 7.5, z: -4.25 });   // no conversion
  });

  it('flag on but no position ⇒ falls back to assignBuildingLots', () => {
    const b = mk('bld_a');   // no position
    const out = resolveBuildingPositions(plan, [b], centers, true);
    const base = assignBuildingLots(plan, [b], centers);
    expect(out.get('bld_a')).toEqual(base.get('bld_a'));
  });
});
