/**
 * Scenery — low-poly ground charm scattered via instancing: grass tufts and
 * flower dots. Counts are modest (a few hundred max) to stay at 60fps.
 * Placement is deterministic (seeded) and avoids the immediate footprint of
 * each place.
 *
 * EM-111 (materials only): everything renders with the shared cached
 * warm-toon materials (toon.ts). Instanced batches share ONE material each —
 * passed via the `material` prop so instancing keeps working unchanged.
 *
 * EM-118: the old 16 individual trees moved to Foliage.tsx as a ~60-tree
 * instanced treeline with LOD; town props live in Props.tsx. Both mount in
 * CozyWorld next to this component.
 */

import { useMemo } from 'react';
import * as THREE from 'three';
import type { Place } from '../../types';
import { SIZE, placeToWorld, hashUnit } from './worldSpace';
import { insideWilderness, wildernessBound } from './foliageLayout';
import { toonMaterial } from './toon';

interface SceneryProps {
  places: Place[];
}

interface Scatter {
  x: number;
  z: number;
  scale: number;
  rot: number;
}

const GRASS_COUNT = 220;
const FLOWER_COUNT = 90;
// EM-118: grass warmed a touch toward the golden-hour terrain greens.
const GRASS_GREEN = '#7bab54';
const FLOWER_COLORS = ['#ff6f91', '#ffd166', '#f8f0fb', '#9b8cff'];

function scatter(
  count: number,
  prefix: string,
  places: Place[],
  minClear: number,
  spread: number,
): Scatter[] {
  const placePts = places.map(placeToWorld);
  // Wave D1 gate fix (EM-156): grass/flowers stay inside the historic-core
  // disc — the generated city ring owns the ground beyond it.
  const bound = wildernessBound(places);
  const out: Scatter[] = [];
  let attempts = 0;
  let i = 0;
  while (out.length < count && attempts < count * 8) {
    attempts++;
    const seed = `${prefix}-${i++}`;
    const x = (hashUnit(`${seed}-x`) - 0.5) * spread;
    const z = (hashUnit(`${seed}-z`) - 0.5) * spread;
    if (!insideWilderness(x, z, bound)) continue; // never on the city ring
    // keep clear of place centers
    const tooClose = placePts.some(
      (p) => Math.hypot(p.x - x, p.z - z) < minClear,
    );
    if (tooClose) continue;
    out.push({
      x,
      z,
      scale: 0.7 + hashUnit(`${seed}-s`) * 0.8,
      rot: hashUnit(`${seed}-r`) * Math.PI * 2,
    });
  }
  return out;
}

/** Instanced mesh that places `items` with per-instance transform. The whole
 *  batch shares ONE cached toon material (EM-111) via the `material` prop. */
function Instances({
  items,
  children,
  material,
  yOffset = 0,
}: {
  items: Scatter[];
  children: React.ReactNode;
  material: THREE.Material;
  yOffset?: number;
}) {
  const ref = useMemo(() => ({ current: null as THREE.InstancedMesh | null }), []);

  const setRef = (mesh: THREE.InstancedMesh | null) => {
    ref.current = mesh;
    if (!mesh) return;
    const dummy = new THREE.Object3D();
    items.forEach((it, i) => {
      dummy.position.set(it.x, yOffset * it.scale, it.z);
      dummy.rotation.set(0, it.rot, 0);
      dummy.scale.setScalar(it.scale);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
    });
    mesh.instanceMatrix.needsUpdate = true;
  };

  return (
    <instancedMesh
      ref={setRef}
      args={[undefined, undefined, items.length]}
      material={material}
      castShadow
      receiveShadow
    >
      {children}
    </instancedMesh>
  );
}

export function Scenery({ places }: SceneryProps) {
  const grass = useMemo(
    () => scatter(GRASS_COUNT, 'grass', places, 2.2, SIZE * 1.5),
    [places],
  );

  // Flowers split by color so each color is its own instanced batch.
  const flowerBatches = useMemo(() => {
    const all = scatter(FLOWER_COUNT, 'flower', places, 2.2, SIZE * 1.5);
    return FLOWER_COLORS.map((color, ci) => ({
      color,
      items: all.filter((_, i) => i % FLOWER_COLORS.length === ci),
    }));
  }, [places]);

  return (
    <group>
      {/* grass tufts — small green cones */}
      <Instances items={grass} yOffset={0.18} material={toonMaterial(GRASS_GREEN)}>
        <coneGeometry args={[0.14, 0.45, 5]} />
      </Instances>

      {/* flowers — tiny colored dots on stems (emissive glow preserved) */}
      {flowerBatches.map((b) => (
        <Instances
          key={b.color}
          items={b.items}
          yOffset={0.22}
          material={toonMaterial(b.color, { emissive: b.color, emissiveIntensity: 0.15 })}
        >
          <sphereGeometry args={[0.13, 8, 8]} />
        </Instances>
      ))}
    </group>
  );
}
